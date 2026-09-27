"""Unit tests for scripts/ingest_reviews.py (offline — no DB).

Covers the deterministic parts:
- load_records: missing dir, corrupt-file skip, walks org subdirs
- _subscore / _int: malformed-scores handling for the typed columns

The write path (TRUNCATE + insert into reviews, idempotency, FK against
datasets) is covered by tests/test_ingest_reviews_db.py against a scratch
migrated database.
Run with: uv run pytest tests/test_ingest_reviews.py
"""

import json
import tempfile
from pathlib import Path

import scripts.ingest_reviews as ir


def rec(dataset_id, n, org_slug="alpha"):
    """A minimal record — the fields load/dedup care about."""
    return {
        "dataset_id": dataset_id,
        "title": f"Title {n}",
        "org_slug": org_slug,
        "ok": True,
        "overall": n % 6,
        "reviewed_at": f"2026-08-01T00:00:0{n}.000Z",
    }


def test_load_records_missing_dir():
    assert ir.load_records(Path("/nonexistent")) == []


def test_load_records():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        org_dir = base / "alpha"
        org_dir.mkdir()

        (org_dir / "title-1-aaaaaaaa.json").write_text(
            json.dumps(rec("a", 1)),
            encoding="utf-8",
        )
        (org_dir / "corrupt.json").write_text("not json", encoding="utf-8")
        (org_dir / "title-3-cccccccc.json").write_text(
            json.dumps(rec("c", 3)),
            encoding="utf-8",
        )

        org_dir2 = base / "beta"
        org_dir2.mkdir()
        (org_dir2 / "title-2-bbbbbbbb.json").write_text(
            json.dumps(rec("b", 2, org_slug="beta")),
            encoding="utf-8",
        )

        records = ir.load_records(base)
        assert len(records) == 3
        ids = [r["dataset_id"] for r in records]
        assert "a" in ids
        assert "b" in ids
        assert "c" in ids


def test_typed_column_helpers():
    # _subscore pulls scores.<key>.score; malformed -> None
    r = {
        "scores": {
            "findability": {"score": 4},
            "metadata": "not a dict",
            "resources": {"score": None},
        },
    }
    assert ir._subscore(r, "findability") == 4
    assert ir._subscore(r, "metadata") is None
    assert ir._subscore(r, "resources") is None
    assert ir._subscore({}, "findability") is None

    # _int keeps ints only (bools are ints in Python — records use real ints)
    assert ir._int(3) == 3
    assert ir._int(None) is None
    assert ir._int("3") is None
