#!/usr/bin/env python3
"""Compute pgvector embeddings for the datasets table via llama-server.

One-off: reads id, title, notes from the datasets table (populated by
build_db.py), computes 768-dim embeddings through llama-server
(bge-base-en-v1.5), and writes them to dataset_embeddings (the vector) and
embedding_map (the dataset -> rowid map) via pgvector.

Start the server first — the exact llama-server invocation is in
scripts/embeddings.py (LLAMA_SERVER).

Usage: python scripts/embed_only.py
       DATABASE_URL=postgresql://localhost:5432/other python scripts/embed_only.py
"""

import json
import re
import sys
import time

import httpx

from scripts.db import connect, database_url
from scripts.embeddings import (
    BATCH,
    BGE_PREFIX,
    DIM,
    EMBED_URL,
    MODEL,
    TIMEOUT,
)

DATABASE_URL = database_url()

# Collapse all whitespace runs (Unicode \s, including NBSP) to single spaces.
_WS_RE = re.compile(r"\s+")


# The embedding tables are migration-owned (0001 + 0002's vector column);
# this script truncates + repopulates, never creates.
TRUNCATE_SQL = "TRUNCATE TABLE embedding_map, dataset_embeddings CASCADE"

# Drop the HNSW index before bulk-loading embeddings and recreate it after.
# Incremental HNSW maintenance during individual INSERTs degrades from ~180
# rows/s at the start to ~30 rows/s by 67k rows, adding ~30-40 minutes to a
# full rebuild. A single bulk CREATE INDEX takes ~5 minutes and produces the
# same result.
DROP_HNSW_SQL = "DROP INDEX IF EXISTS idx_dataset_embeddings_hnsw"
CREATE_HNSW_SQL = (
    "CREATE INDEX idx_dataset_embeddings_hnsw "
    "ON dataset_embeddings USING hnsw (embedding vector_l2_ops)"
)


def build_texts(rows: list[dict]) -> list[str | None]:
    """Build BGE-prefixed input texts.

    rows: [{id, title, notes}, ...]. Per row: notes truncated to 500
    chars, whitespace collapsed to single spaces, trimmed. Empty texts
    become None (a row with an empty title embeds the bare prefix).
    """

    texts: list[str | None] = []
    for r in rows:
        notes_short = (r["notes"] or "")[:500]
        t = f"{BGE_PREFIX}{r['title']} {notes_short}"
        texts.append(_WS_RE.sub(" ", t).strip() or None)
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
) -> None:
    """Embed one batch and write its rows.

    Null texts are skipped in the request and stored as zero vectors; every
    other row gets embedding = the response vector.
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
            "INSERT INTO embedding_map(rowid, dataset_id) VALUES (?, ?)",
        )
        emb_idx = 0
        for i in range(batch_start, batch_end):
            rowid = i + 1  # dense ids from 1
            if texts[i] is not None:
                vec_arr = data[emb_idx]["embedding"]
                emb_idx += 1
            else:
                vec_arr = [0] * DIM  # zero vector for null texts
            # pgvector expects the '[...]' literal; str(float) is the
            # shortest round-trip repr.
            insert_emb.run(rowid, f"[{','.join(str(v) for v in vec_arr)}]")
            insert_map.run(rowid, rows[i]["id"])

    db.transaction(_write)


def main() -> None:
    print("Opening db...", file=sys.stderr)
    db = connect(DATABASE_URL)
    try:
        # Truncate + repopulate the embedding tables (migration-owned).
        db.exec(TRUNCATE_SQL)

        # Drop the HNSW index before bulk-loading — incremental maintenance is
        # O(n log n) overall and adds 30-40 min on a 67k-row rebuild.
        db.exec(DROP_HNSW_SQL)
        print("HNSW index dropped; will rebuild after inserts.", file=sys.stderr)

        rows = db.prepare("SELECT id, title, notes FROM datasets").all()
        print(f"datasets to embed: {len(rows)}", file=sys.stderr)

        rows = [dict(r) for r in rows]
        texts = build_texts(rows)

        print("Computing embeddings via llama-server...", file=sys.stderr)

        LOG_EVERY = 20  # batches between progress lines
        start_time = time.time()
        with httpx.Client(follow_redirects=True, timeout=TIMEOUT) as client:
            for batch_num, batch_start in enumerate(range(0, len(texts), BATCH)):
                batch_end = min(batch_start + BATCH, len(texts))
                embed_batch(client, db, texts, rows, batch_start, batch_end)

                done = batch_end
                if batch_num % LOG_EVERY == 0 or done >= len(texts):
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
