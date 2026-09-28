"""Scratch-DB tests for the write path in ``scripts/llm/ingest_suggestions.py``.

Runs the real ``ingest()`` (TRUNCATE + INSERT) against a throwaway migrated
database, so a column rename, an arity slip, or a field-mapping bug fails
here instead of at the next ``just ingest-suggestions``. Never touches the
dev DB — see ``tests/conftest.py``.
"""

import json

from scripts import db
from scripts.llm.ingest_suggestions import ingest


def rec(dataset_id, **over):
    """A record with only the fields the write path reads."""
    r = {"dataset_id": dataset_id, "ok": True}
    r.update(over)
    return r


def test_ingest_round_trip(migrated_db_url):
    d = db.connect(migrated_db_url)
    try:
        d.prepare("INSERT INTO datasets (id, org_slug) VALUES (?, ?)").run("is-1", "alpha")
        records = [
            rec(
                "is-1",
                suggested_theme="environment",
                suggested_theme_confidence="high",
                suggested_tags=["env", "climate"],
                suggested_title="T",
                suggested_description="D",
                classified_at="2026-08-01T00:00:00Z",
            ),
            rec("is-absent"),  # not in datasets -> dropped by the FK guard
        ]

        assert ingest(d, records) == 1

        assert d.prepare(
            'SELECT dataset_id, ok, theme, theme_confidence, tags, title, "desc", created_at FROM suggestions',
        ).all() == [
            {
                "dataset_id": "is-1",
                "ok": True,
                "theme": "environment",
                "theme_confidence": "high",
                "tags": json.dumps(["env", "climate"], ensure_ascii=False),
                "title": "T",
                "desc": "D",
                "created_at": "2026-08-01T00:00:00Z",
            },
        ]
        stored = d.prepare("SELECT json FROM suggestions").get()
        assert json.loads(stored["json"])["dataset_id"] == "is-1"
    finally:
        d.close()


def test_ingest_is_idempotent(migrated_db_url):
    d = db.connect(migrated_db_url)
    try:
        d.prepare("INSERT INTO datasets (id, org_slug) VALUES (?, ?)").run("is-2", "alpha")
        records = [rec("is-2")]
        assert ingest(d, records) == 1
        assert ingest(d, records) == 1  # TRUNCATE, not append
        assert d.prepare("SELECT COUNT(*) AS n FROM suggestions").get() == {"n": 1}
    finally:
        d.close()
