"""Build pgvector embeddings for the datasets table via llama-server.

Reads the LLM-suggested title/theme/tags/description for each dataset (the
suggestions table, joined by CKAN guid) and writes the 768-dim embedding to
dataset_embeddings, with embedding_map recording which ckan_id owns which
rowid.

The map is keyed on the CKAN guid (not datasets.id, which the CKAN ingest
reassigns), so a new ingest does not orphan or delete existing vectors. By
default the build is incremental: it only embeds datasets that don't have a
vector yet. Pass --force to re-embed everything (e.g. after suggestions
changed), which truncates and rebuilds from scratch.

Start llama-server first (see LLAMA_SERVER below, or `just llama-server`).

Usage: python scripts/build_embeddings.py [--force]
       DATABASE_URL=postgresql://localhost:5432/other python scripts/build_embeddings.py
"""

import argparse
import json
import sys
import time

import httpx

from scripts.db import connect, database_url
from scripts.embed_text import format_document

# ---------------------------------------------------------------------------
# llama-server config
# ---------------------------------------------------------------------------
# Start llama-server first with:
# --pooling mean: EmbeddingGemma pools with the mean token embedding (BGE used
#   cls); leaving it unset falls back to the GGUF metadata, but be explicit.
# --ubatch-size 2048: avoids the "n_batch > n_ubatch" assertion that caps both
#   at 512, reducing GPU dispatch count ~4x for our 256-text batches.
# --ctx-size 8192: 1024 tokens per slot (8 parallel) — plenty for the 500-char
#   descriptions. Without it llama.cpp uses the model's 2048-token training
#   context, leaving only 256 tokens per slot.
# --parallel 8: 8 sequences processed per forward pass (vs default 4).
LLAMA_SERVER = (
    "llama-server -m llm/embeddinggemma-300m-qat-Q8_0.gguf "
    "--embeddings --pooling mean --embd-normalize 2 --gpu-layers all "
    "--ctx-size 8192 --ubatch-size 2048 --parallel 8 --port 8080"
)

EMBED_URL = "http://localhost:8080/v1/embeddings"
DIM = 768
BATCH = 256
MODEL = "embeddinggemma-300m"
TIMEOUT = 600

DATABASE_URL = database_url()

# --force rebuild: the embedding tables are migration-owned (0001); this
# script repopulates, never creates.
TRUNCATE_SQL = "TRUNCATE TABLE embedding_map, dataset_embeddings CASCADE"

# Drop the HNSW index before bulk-loading embeddings and recreate it after.
# Incremental HNSW maintenance during individual INSERTs degrades from ~180
# rows/s at the start to ~30 rows/s by 67k rows, adding ~30-40 minutes to a
# full rebuild. A single bulk CREATE INDEX takes ~5 minutes and produces the
# same result. Only used for a full build (--force or the first run); small
# incremental backfills keep the index in place.
DROP_HNSW_SQL = "DROP INDEX IF EXISTS idx_dataset_embeddings_hnsw"
CREATE_HNSW_SQL = "CREATE INDEX idx_dataset_embeddings_hnsw ON dataset_embeddings USING hnsw (embedding vector_l2_ops)"

# Datasets that have an LLM suggestion but no stored vector yet — everything
# the incremental build needs to embed. Only datasets with resources are
# reviewed/suggested (see scripts/llm/common.py) and so only those can be
# embedded; the filter makes that explicit.
SELECT_NEW_SQL = """
SELECT d.ckan_id, s.title, d.title AS orig_title, s.theme, s.tags, s.desc, d.notes
FROM datasets d
JOIN suggestions s ON s.dataset_ckan_id = d.ckan_id
LEFT JOIN embedding_map m ON m.dataset_ckan_id = d.ckan_id
WHERE m.rowid IS NULL
  AND d.resource_count > 0
ORDER BY d.id
"""


def _format_tags(tags_json: str | None) -> str:
    """Parse a JSON-array tags string into a comma-separated string, or ''."""
    if not tags_json:
        return ""
    try:
        items = json.loads(tags_json)
        return ", ".join(str(t) for t in items) if items else ""
    except (ValueError, TypeError):
        return ""


def build_texts(rows: list[dict]) -> list[str | None]:
    """Build EmbeddingGemma document texts from LLM-suggested fields.

    rows: [{ckan_id, title, theme, tags, desc}, ...] — all from the
    suggestions table. The title becomes the document title; description
    (truncated to 500 chars), theme and tags make up the document body.
    Whitespace collapsed, trimmed. Items with no title and no body become
    None.
    """

    texts: list[str | None] = []
    for r in rows:
        title = (r.get("title") or r.get("orig_title") or "").strip()
        desc_short = (r.get("desc") or r.get("notes") or "")[:500]
        theme = (r.get("theme") or "").strip()
        tags = _format_tags(r.get("tags"))

        parts = []
        if desc_short:
            parts.append(desc_short)
        if theme:
            parts.append(f"Theme: {theme}.")
        if tags:
            parts.append(f"Tags: {tags}.")

        texts.append(format_document(title, " ".join(parts)))
    return texts


def assemble_batch(
    texts: list[str | None],
    batch_start: int,
    batch_end: int,
) -> tuple[list[str], list[int]]:
    """Collect the non-null texts in a batch window.

    Returns (input_texts, orig_index): the texts to POST, and the position
    of each in the full texts array — response embeddings are aligned back
    to their rows via orig_index (and texts skipped here become zero
    vectors, written by the caller).
    """

    input_texts: list[str] = []
    orig_index: list[int] = []
    for i in range(batch_start, batch_end):
        if texts[i] is not None:
            input_texts.append(texts[i])
            orig_index.append(i)
    return input_texts, orig_index


def embed_batch(
    client: httpx.Client,
    db,
    texts: list[str | None],
    rows: list[dict],
    batch_start: int,
    batch_end: int,
    start_rowid: int,
) -> None:
    """Embed one batch and write its rows.

    Null texts are skipped in the request and stored as zero vectors; every
    other row gets embedding = the response vector. rowids continue above
    the existing embeddings (start_rowid is the current max, 0 on a full
    build) so incremental runs append rather than overwrite.
    """

    if batch_start >= batch_end:
        return

    input_texts, _orig_index = assemble_batch(texts, batch_start, batch_end)

    res = client.post(
        EMBED_URL,
        json={"input": input_texts, "model": MODEL},
        headers={"Content-Type": "application/json"},
    )
    if not res.is_success:
        try:
            body = res.json()
        except ValueError:
            body = {"error": {"message": res.reason_phrase}}
        raise RuntimeError(f"HTTP {res.status_code}: {json.dumps(body)[:200]}")

    data = res.json()["data"]

    def _write(tx) -> None:
        insert_emb = tx.prepare(
            "INSERT INTO dataset_embeddings(rowid, embedding) VALUES (?, ?::vector)",
        )
        insert_map = tx.prepare(
            "INSERT INTO embedding_map(rowid, dataset_ckan_id) VALUES (?, ?)",
        )
        emb_idx = 0
        for i in range(batch_start, batch_end):
            rowid = start_rowid + i + 1
            if texts[i] is not None:
                vec_arr = data[emb_idx]["embedding"]
                emb_idx += 1
            else:
                vec_arr = [0] * DIM  # zero vector for null texts
            # pgvector expects the '[...]' literal; str(float) is the
            # shortest round-trip repr.
            insert_emb.run(rowid, f"[{','.join(str(v) for v in vec_arr)}]")
            insert_map.run(rowid, rows[i]["ckan_id"])

    db.transaction(_write)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="truncate and re-embed every dataset (use after suggestions change)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    print("Opening db...", file=sys.stderr)
    db = connect(DATABASE_URL)
    try:
        if args.force:
            db.exec(TRUNCATE_SQL)
            existing = 0
        else:
            count_row = db.prepare("SELECT COUNT(*) AS n FROM embedding_map").get()
            existing = count_row["n"] if count_row else 0

        rows = db.prepare(SELECT_NEW_SQL).all()
        print(f"datasets to embed: {len(rows)} ({existing} already stored)", file=sys.stderr)
        if not rows:
            print("Nothing new to embed.", file=sys.stderr)
            return

        rows = [dict(r) for r in rows]
        texts = build_texts(rows)
        max_row = db.prepare("SELECT COALESCE(MAX(rowid), 0) AS n FROM embedding_map").get()
        start_rowid = max_row["n"] if max_row else 0

        # A full build (--force or the first run) bulk-loads without the HNSW
        # index; a small incremental backfill keeps it and pays only the
        # per-row insert cost.
        rebuild_index = args.force or existing == 0
        if rebuild_index:
            db.exec(DROP_HNSW_SQL)
            print("HNSW index dropped; will rebuild after inserts.", file=sys.stderr)

        print("Computing embeddings via llama-server...", file=sys.stderr)

        log_every = 20  # batches between progress lines
        start_time = time.time()
        with httpx.Client(follow_redirects=True, timeout=TIMEOUT) as client:
            for batch_num, batch_start in enumerate(range(0, len(texts), BATCH)):
                batch_end = min(batch_start + BATCH, len(texts))
                embed_batch(client, db, texts, rows, batch_start, batch_end, start_rowid)

                done = batch_end
                if batch_num % log_every == 0 or done >= len(texts):
                    elapsed = (time.time() - start_time) / 60
                    print(
                        f"  {done}/{len(texts)} ({elapsed:.1f} min)...",
                        file=sys.stderr,
                    )

        elapsed = (time.time() - start_time) / 60
        print(
            f"Embeddings done: {len(texts)} datasets in {elapsed:.1f} min.",
            file=sys.stderr,
        )

        if rebuild_index:
            print("Rebuilding HNSW index (this takes ~5 min)...", file=sys.stderr)
            t_idx = time.time()
            db.exec(CREATE_HNSW_SQL)
            print(
                f"HNSW index rebuilt in {(time.time() - t_idx) / 60:.1f} min.",
                file=sys.stderr,
            )

        total_elapsed = (time.time() - start_time) / 60
        print(f"Done: total {total_elapsed:.1f} min.", file=sys.stderr)
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except (httpx.HTTPError, RuntimeError, ValueError, OSError) as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)
