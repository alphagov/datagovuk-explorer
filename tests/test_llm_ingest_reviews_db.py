"""Scratch-DB tests for the write path in ``scripts/llm/ingest_reviews.py``.

``test_llm_ingest_reviews.py`` covers parsing/dedup with no database. This file
runs the real ``ingest()`` (TRUNCATE + INSERT) against a throwaway migrated
database, so a column rename, an arity slip, or a field-mapping bug fails
here instead of at the next ``just ingest-reviews``. Never touches the dev
DB — see ``tests/conftest.py``.
"""

import json
from datetime import UTC, datetime

from scripts import db
from scripts.llm.ingest_reviews import ingest


def rec(dataset_id, **over):
    """A record with only the fields the write path reads."""
    r = {"dataset_id": dataset_id, "ok": True}
    r.update(over)
    return r


def test_ingest_round_trip(migrated_db_url):
    d = db.connect(migrated_db_url)
    try:
        pk = d.prepare(
            "INSERT INTO datasets (ckan_id, org_slug) VALUES (?, ?) RETURNING id",
        ).get("ir-1", "alpha")["id"]
        records = [
            rec(
                "ir-1",
                **{"title-description": {"score": 2}},
                reviewed_at="2026-08-01T00:00:00Z",
            ),
            rec("ir-absent"),  # not in datasets -> dropped by the FK guard
        ]

        assert ingest(d, records) == 1

        assert d.prepare(
            "SELECT dataset_id, findability, resources, created_at FROM reviews",
        ).all() == [
            {
                "dataset_id": pk,
                "findability": 2,
                "resources": None,
                "created_at": datetime(2026, 8, 1, tzinfo=UTC),
            },
        ]
        stored = d.prepare("SELECT json FROM reviews").get()
        assert json.loads(stored["json"])["dataset_id"] == "ir-1"
    finally:
        d.close()


def test_ingest_is_idempotent(migrated_db_url):
    d = db.connect(migrated_db_url)
    try:
        d.prepare(
            "INSERT INTO datasets (ckan_id, org_slug) VALUES (?, ?)",
        ).run("ir-2", "alpha")
        records = [rec("ir-2")]
        assert ingest(d, records) == 1
        assert ingest(d, records) == 1  # TRUNCATE, not append
        assert d.prepare("SELECT COUNT(*) AS n FROM reviews").get() == {"n": 1}
    finally:
        d.close()
