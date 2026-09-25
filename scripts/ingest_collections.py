#!/usr/bin/env python3
"""Load data/collections/**/*.md into the `collections` table.

Parses YAML frontmatter + markdown body from each collection file, then
loads Search Console clicks from data/datagovuk-pages.csv for view counts.

Idempotent: TRUNCATEs `collections` then reloads.

Usage: python -m scripts.ingest_collections
       DATABASE_URL=postgresql://localhost:5432/other python -m scripts.ingest_collections
"""

import csv
import json
import re
import sys
from pathlib import Path

import httpx
import yaml

from scripts.db import connect, database_url

COLLECTIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "collections"
VIEWS_FILE = Path(__file__).resolve().parent.parent / "data" / "datagovuk-pages.csv"

EMBED_URL = "http://localhost:8080/v1/embeddings"
EMBED_MODEL = "bge-base-en-v1.5"
BGE_PREFIX = "Represent this sentence for searching relevant passages: "
_WS_RE = re.compile(r"\s+")

_COLLECTION_URL_RE = re.compile(
    r"https://www\.data\.gov\.uk/collections/(.+)",
)

# Search Console sometimes reports a collection page under its category-level
# path instead of the full slug. Map those shortened paths to the real slug.
_SLUG_ALIASES = {
    "people": "people/births",
    "business-and-economy": "business-and-economy/uk-trade",
    "environment": "environment/weather",
    "government": "government-and-parliament/election-results",
    "land-and-property": "land-and-property/uk-house-prices",
    "transport": "transport/road-traffic",
    "early-years": "early-years/childcare-providers",
}


def parse_collection(path: Path, base: Path) -> dict:
    """Parse a single markdown collection file into a record dict."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}

    _, raw_meta, *rest = text.split("---", 2)
    if not rest:
        return {}

    meta = yaml.safe_load(raw_meta) or {}
    body = rest[0].strip()

    rel = path.relative_to(base).with_suffix("")
    slug = str(rel)
    category = rel.parts[0]

    return {
        "slug": slug,
        "category": category,
        "title": meta.get("title", ""),
        "description": body or None,
        "websites": meta.get("websites") or None,
        "api": meta.get("api") or None,
        "dataset": meta.get("dataset") or None,
        "page_last_updated": meta.get("page-last-updated") or None,
        "visualisation_data": meta.get("visualisation-data") or None,
        "status": meta.get("status") or None,
    }


def load_all_collections() -> list[dict]:
    """Parse every .md file under data/collections/."""
    records = []
    for path in sorted(COLLECTIONS_DIR.rglob("*.md")):
        rec = parse_collection(path, COLLECTIONS_DIR)
        if rec:
            records.append(rec)
    return records


def load_collection_views() -> dict[str, int]:
    """Read Search Console clicks for /collections/ URLs.

    Returns {slug: total_clicks} where slug matches the collection file
    path (e.g. "environment/air-quality").
    """
    if not VIEWS_FILE.exists():
        return {}

    result: dict[str, int] = {}
    with VIEWS_FILE.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            m = _COLLECTION_URL_RE.match(row["Landing Page"])
            if not m:
                continue
            clicks = int(row["Url Clicks"])
            if clicks <= 0:
                continue
            slug = m.group(1)
            slug = _SLUG_ALIASES.get(slug, slug)
            result[slug] = result.get(slug, 0) + clicks
    return result


def ingest(db, records: list[dict], views: dict[str, int]) -> int:
    """Truncate + insert all collection records; returns inserted count."""

    def _run(tx) -> None:
        tx.exec("TRUNCATE collections CASCADE")
        stmt = tx.prepare(
            """INSERT INTO collections
               (slug, category, title, description, websites, api, dataset,
                page_last_updated, visualisation_data, status, views)
               VALUES (?, ?, ?, ?, ?::jsonb, ?::jsonb, ?::jsonb, ?, ?, ?, ?)""",
        )
        for r in records:
            stmt.run(
                r["slug"],
                r["category"],
                r["title"],
                r["description"],
                json.dumps(r["websites"], ensure_ascii=False) if r["websites"] else None,
                json.dumps(r["api"], ensure_ascii=False) if r["api"] else None,
                json.dumps(r["dataset"], ensure_ascii=False) if r["dataset"] else None,
                r["page_last_updated"],
                r["visualisation_data"],
                r["status"],
                views.get(r["slug"], 0),
            )

    db.transaction(_run)
    return len(records)


def build_collection_embeddings(db, records: list[dict]) -> int:
    """Embed collection title+description via llama-server and write to
    collection_embeddings. Returns the number of embeddings written, or 0
    if llama-server is unreachable."""
    texts = []
    slugs = []
    for r in records:
        notes_short = (r["description"] or "")[:500]
        t = f"{BGE_PREFIX}{r['title']} {notes_short}"
        t = _WS_RE.sub(" ", t).strip()
        if t == BGE_PREFIX.strip():
            continue
        texts.append(t)
        slugs.append(r["slug"])

    if not texts:
        return 0

    try:
        with httpx.Client(timeout=60) as client:
            res = client.post(
                EMBED_URL,
                json={"input": texts, "model": EMBED_MODEL},
                headers={"Content-Type": "application/json"},
            )
            res.raise_for_status()
    except (httpx.ConnectError, httpx.HTTPStatusError) as e:
        print(f"llama-server not available ({e}) — skipping collection embeddings.", file=sys.stderr)
        return 0

    data = res.json()["data"]

    def _write(tx) -> None:
        tx.exec("TRUNCATE collection_embeddings")
        stmt = tx.prepare(
            "INSERT INTO collection_embeddings(slug, embedding) VALUES (?, ?::vector)",
        )
        for i, slug in enumerate(slugs):
            vec = data[i]["embedding"]
            stmt.run(slug, f"[{','.join(str(v) for v in vec)}]")

    db.transaction(_write)
    return len(slugs)


def main() -> None:
    records = load_all_collections()
    if not records:
        print("No collection files found — nothing to do.", file=sys.stderr)
        sys.exit(1)

    views = load_collection_views()
    with_views = sum(1 for r in records if r["slug"] in views)
    print(
        f"Loaded {len(records)} collection(s) from {COLLECTIONS_DIR.name}/; "
        f"{len(views)} slug(s) have Search Console views ({with_views} matched).",
    )

    db = connect(database_url())
    try:
        n = ingest(db, records, views)
        print(f"Inserted {n} row(s) into collections.")

        n_emb = build_collection_embeddings(db, records)
        if n_emb:
            print(f"Wrote {n_emb} collection embedding(s).")
        else:
            print("No collection embeddings written (llama-server may not be running).")
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, KeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
