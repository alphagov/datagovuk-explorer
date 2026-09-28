"""Unit tests for scripts/llm/ingest_suggestions.py (offline — no DB).

Covers the deterministic parts:
- load_records: missing dir, corrupt-file skip, walks org subdirs

Run with: uv run pytest tests/test_llm_ingest_suggestions.py
"""

import json
import tempfile
from pathlib import Path

import scripts.llm.ingest_suggestions as isug


def rec(dataset_id, n, org_slug="alpha"):
    """A minimal record — the fields load cares about."""
    return {
        "dataset_id": dataset_id,
        "title": f"Title {n}",
        "org_slug": org_slug,
        "ok": True,
        "classified_at": f"2026-08-01T00:00:0{n}.000Z",
        "suggested_theme": "environment",
        "suggested_theme_confidence": "medium",
        "suggested_tags": ["tag-one"],
        "suggested_title": "",
        "suggested_description": "",
    }


def test_load_records_missing_dir():
    assert isug.load_records(Path("/nonexistent")) == []


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

        records = isug.load_records(base)
        assert len(records) == 3
        ids = [r["dataset_id"] for r in records]
        assert "a" in ids
        assert "b" in ids
        assert "c" in ids
