"""Scratch-DB tests for the embedding write path.

``test_build_embeddings.py`` covers the text/request core offline. This file
runs the real SQL against a throwaway migrated database and locks in the two
properties that make embeddings survive a CKAN re-ingest:

- embedding_map is keyed on the CKAN guid with no datasets FK, so deleting or
  rebuilding a dataset does not cascade its vector away
- the incremental SELECT only picks up datasets that have no vector yet

Never touches the dev database — see ``tests/conftest.py``.
"""

import os

# scripts.build_embeddings reads DATABASE_URL at import time; tests connect
# through the migrated_db_url fixture instead, so a dummy is enough.
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/test-db")

import scripts.build_embeddings as be
from scripts import db

ZERO_VECTOR = "[" + ",".join(["0"] * be.DIM) + "]"
CKAN_A = "test-embedding-ckan-a"
CKAN_B = "test-embedding-ckan-b"
LINKLESS = "test-embedding-linkless"


class _FakeResponse:
    is_success = True

    def __init__(self, n):
        self._n = n

    def json(self):
        return {"data": [{"embedding": [0.5] * be.DIM} for _ in range(self._n)]}


class _FakeClient:
    """Stand-in for httpx.Client — returns one embedding per input text."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json, headers):
        self.last_input = json["input"]
        return _FakeResponse(len(json["input"]))


def _seed_dataset(d, ckan_id, title, resource_count=1):
    d.prepare(
        "INSERT INTO datasets (ckan_id, org_slug, title, resource_count) VALUES (?, ?, ?, ?)",
    ).run(ckan_id, "alpha", title, resource_count)
    d.prepare(
        "INSERT INTO suggestions (dataset_ckan_id, title, json) VALUES (?, ?, '{}')",
    ).run(ckan_id, title)


def _cleanup(d):
    d.prepare("DELETE FROM datasets WHERE ckan_id IN (?, ?, ?)").run(CKAN_A, CKAN_B, LINKLESS)
    d.prepare("DELETE FROM suggestions WHERE dataset_ckan_id IN (?, ?, ?)").run(CKAN_A, CKAN_B, LINKLESS)
    d.exec("TRUNCATE TABLE embedding_map, dataset_embeddings")


def _count(d, sql: str, *params) -> int:
    """A COUNT(*) scalar — `.get()` is Optional, so unwrap it explicitly."""
    row = d.prepare(sql).get(*params)
    assert row is not None
    return row["n"]


def test_embed_batch_writes_ckan_id(migrated_db_url):
    """embed_batch maps rowid -> dataset_ckan_id, extending past start_rowid."""
    d = db.connect(migrated_db_url)
    try:
        _cleanup(d)
        rows: list[dict] = [
            {"ckan_id": CKAN_A, "title": "Alpha"},
            {"ckan_id": CKAN_B, "title": "Beta"},
            {"ckan_id": "test-embedding-empty", "title": None, "orig_title": None, "desc": None, "notes": None},
        ]
        texts = be.build_texts(rows)

        be.embed_batch(_FakeClient(), d, texts, rows, 0, 3, start_rowid=5)  # type: ignore[arg-type]

        assert d.prepare("SELECT rowid, dataset_ckan_id FROM embedding_map ORDER BY rowid").all() == [
            {"rowid": 6, "dataset_ckan_id": CKAN_A},
            {"rowid": 7, "dataset_ckan_id": CKAN_B},
            {"rowid": 8, "dataset_ckan_id": "test-embedding-empty"},
        ]
        # One vector per row (the empty text stored as a zero vector).
        assert _count(d, "SELECT count(*) AS n FROM dataset_embeddings") == 3
    finally:
        _cleanup(d)
        d.close()


def test_embeddings_survive_dataset_delete(migrated_db_url):
    """Deleting the dataset leaves the vector and its ckan_id mapping intact."""
    d = db.connect(migrated_db_url)
    try:
        _cleanup(d)
        d.prepare("INSERT INTO datasets (ckan_id, org_slug) VALUES (?, ?)").run(CKAN_A, "alpha")
        d.prepare("INSERT INTO embedding_map (rowid, dataset_ckan_id) VALUES (1, ?)").run(CKAN_A)
        d.prepare("INSERT INTO dataset_embeddings (rowid, embedding) VALUES (1, ?::vector)").run(ZERO_VECTOR)

        # The ingest rebuild does exactly this (TRUNCATE datasets ... CASCADE).
        d.prepare("DELETE FROM datasets WHERE ckan_id = ?").run(CKAN_A)

        assert (
            _count(
                d,
                "SELECT count(*) AS n FROM embedding_map WHERE dataset_ckan_id = ?",
                CKAN_A,
            )
            == 1
        )
        assert _count(d, "SELECT count(*) AS n FROM dataset_embeddings") == 1
    finally:
        _cleanup(d)
        d.close()


def test_select_new_skips_already_embedded(migrated_db_url):
    """An incremental build only sees linked datasets without a vector."""
    d = db.connect(migrated_db_url)
    try:
        _cleanup(d)
        _seed_dataset(d, CKAN_A, "Alpha")
        _seed_dataset(d, CKAN_B, "Beta")
        # A link-less dataset is never reviewed/suggested, but guard the rule.
        _seed_dataset(d, LINKLESS, "No links", resource_count=0)

        selected = d.prepare(be.SELECT_NEW_SQL).all()
        assert {r["ckan_id"] for r in selected} == {CKAN_A, CKAN_B}

        d.prepare("INSERT INTO embedding_map (rowid, dataset_ckan_id) VALUES (1, ?)").run(CKAN_A)
        selected = d.prepare(be.SELECT_NEW_SQL).all()
        assert {r["ckan_id"] for r in selected} == {CKAN_B}
    finally:
        _cleanup(d)
        d.close()
