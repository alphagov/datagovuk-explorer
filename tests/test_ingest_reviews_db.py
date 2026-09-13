"""Scratch-DB tests for the write path in ``scripts/ingest_reviews.py``.

``test_ingest_reviews.py`` covers parsing/dedup with no database. This file
runs the real ``ingest()`` (TRUNCATE + INSERT) against a throwaway migrated
database, so a column rename, an arity slip, or a field-mapping bug fails
here instead of at the next ``just ingest-reviews``. Never touches the dev
DB — see ``tests/conftest.py``.
"""

import json

from scripts import db
from scripts.ingest_reviews import ingest


def rec(dataset_id, **over):
    """A record with only the fields the write path reads."""
    r = {"dataset_id": dataset_id, "ok": True}
    r.update(over)
    return r


def test_ingest_round_trip(migrated_db_url):
    d = db.connect(migrated_db_url)
    try:
        d.prepare("INSERT INTO datasets (id, org_slug) VALUES (?, ?)").run("ir-1", "alpha")
        records = [
            rec(
                "ir-1",
                overall=3,
                scores={"findability": {"score": 2}},
                tags=["env", "climate"],
                suggested_title="T",
                suggested_description="D",
                theme="environment",
                theme_confidence="high",
                reviewed_at="2026-08-01T00:00:00Z",
            ),
            rec("ir-absent"),  # not in datasets -> dropped by the FK guard
        ]

        assert ingest(d, records) == 1

        assert d.prepare(
            "SELECT dataset_id, ok, overall, findability, metadata, resources,"
            ' tags, title, "desc", theme, theme_confidence, created_at'
            " FROM reviews",
        ).all() == [
            {
                "dataset_id": "ir-1",
                "ok": True,
                "overall": 3,
                "findability": 2,
                "metadata": None,
                "resources": None,
                "tags": json.dumps(["env", "climate"], ensure_ascii=False),
                "title": "T",
                "desc": "D",
                "theme": "environment",
                "theme_confidence": "high",
                "created_at": "2026-08-01T00:00:00Z",
            },
        ]
        # The raw JSONL record is kept verbatim in `json` for the views.
        stored = d.prepare("SELECT json FROM reviews").get()
        assert json.loads(stored["json"])["dataset_id"] == "ir-1"
    finally:
        d.close()


def test_ingest_is_idempotent(migrated_db_url):
    d = db.connect(migrated_db_url)
    try:
        d.prepare("INSERT INTO datasets (id, org_slug) VALUES (?, ?)").run("ir-2", "alpha")
        records = [rec("ir-2")]
        assert ingest(d, records) == 1
        assert ingest(d, records) == 1  # TRUNCATE, not append
        assert d.prepare("SELECT COUNT(*) AS n FROM reviews").get() == {"n": 1}
    finally:
        d.close()
