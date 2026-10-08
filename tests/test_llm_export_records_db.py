"""Scratch-DB tests for scripts/llm/export_records.py.

The DB can hold reviews/suggestions restored from a dump while the
downloads/<table>/ file dirs are empty. Because the ingest scripts are
TRUNCATE + reload, exporting the DB rows back to files is what makes a
subsequent `review`/`suggest` + `ingest-*` lossless. These tests seed the DB
via the real ingest path, export it, and assert:

- the files land where review/suggest look for processed ids
- the exported JSON is byte-for-byte the stored record
- re-ingesting the exported files rebuilds the same rows

Never touches the dev DB — see tests/conftest.py.
"""

import json

from scripts import db
from scripts.llm.common import load_processed_ids
from scripts.llm.export_records import export_table
from scripts.llm.ingest_reviews import ingest as ingest_reviews, load_records as load_review_files
from scripts.llm.ingest_suggestions import ingest as ingest_suggestions, load_records as load_suggestion_files

REVIEW_ID = "aaaaaaaa-1111-1111-1111-111111111111"
SUGGESTION_ID = "bbbbbbbb-2222-2222-2222-222222222222"


def _seed_dataset(d, ckan_id):
    d.prepare("INSERT INTO datasets (ckan_id, org_slug) VALUES (?, ?)").run(ckan_id, "alpha")


_REVIEW = {
    "dataset_id": REVIEW_ID,
    "title": "Export Review Test",
    "org_slug": "alpha",
    "org_display_name": "Alpha",
    "model": "test-model",
    "reviewed_at": "2026-08-01T00:00:00.000Z",
    "ok": True,
    "title-description": {"score": 3, "issues": ["Missing context"]},
    "resources": {"score": 4, "issues": []},
    "input": {"title": "Export Review Test"},
}

_SUGGESTION = {
    "dataset_id": SUGGESTION_ID,
    "title": "Export Suggestion Test",
    "org_slug": "alpha",
    "org_display_name": "Alpha",
    "model": "test-model",
    "classified_at": "2026-08-01T00:00:00.000Z",
    "ok": True,
    "suggested_theme": "environment",
    "suggested_theme_confidence": "high",
    "suggested_tags": ["tag-one", "tag-two"],
    "suggested_title": "A clearer title",
    "suggested_description": "A clearer description.",
}


def test_export_reviews_round_trip(migrated_db_url, tmp_path):
    d = db.connect(migrated_db_url)
    try:
        _seed_dataset(d, REVIEW_ID)
        assert ingest_reviews(d, [_REVIEW]) == 1

        assert export_table(d, "reviews", tmp_path, overwrite=False) == (1, 0)

        # One file, in the layout `review`/`ingest-reviews` expect.
        files = list((tmp_path / "reviews").rglob("*.json"))
        assert len(files) == 1
        assert json.loads(files[0].read_text(encoding="utf-8")) == _REVIEW

        # `just review` will now see it as already processed.
        ok, _attempted = load_processed_ids(tmp_path / "reviews")
        assert REVIEW_ID in ok

        # Re-ingesting the exported file rebuilds the row (no data loss).
        assert ingest_reviews(d, load_review_files(tmp_path / "reviews")) == 1

        # Existing files are left alone unless --force.
        assert export_table(d, "reviews", tmp_path, overwrite=False) == (0, 1)
        assert export_table(d, "reviews", tmp_path, overwrite=True) == (1, 0)
    finally:
        d.close()


def test_export_suggestions_round_trip(migrated_db_url, tmp_path):
    d = db.connect(migrated_db_url)
    try:
        _seed_dataset(d, SUGGESTION_ID)
        assert ingest_suggestions(d, [_SUGGESTION]) == 1

        assert export_table(d, "suggestions", tmp_path, overwrite=False) == (1, 0)

        files = list((tmp_path / "suggestions").rglob("*.json"))
        assert len(files) == 1
        assert json.loads(files[0].read_text(encoding="utf-8")) == _SUGGESTION

        ok, _attempted = load_processed_ids(tmp_path / "suggestions")
        assert SUGGESTION_ID in ok

        assert ingest_suggestions(d, load_suggestion_files(tmp_path / "suggestions")) == 1
        assert export_table(d, "suggestions", tmp_path, overwrite=False) == (0, 1)
    finally:
        d.close()
