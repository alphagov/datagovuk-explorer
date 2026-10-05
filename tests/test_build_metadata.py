"""Unit tests for scripts/build_metadata.py (offline — no database)."""

import json
import os

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/test-db")

import scripts.build_metadata as bm


def test_field_value_str():
    assert bm.field_value_str(None) == "(empty)"
    assert bm.field_value_str("") == "(empty)"
    assert bm.field_value_str("hello") == "hello"
    assert bm.field_value_str("x" * 501) == "x" * 500 + "..."
    assert bm.field_value_str(v=True) == "true"
    assert bm.field_value_str(1.0) == "1"
    assert bm.field_value_str(3) == "3"
    assert bm.field_value_str([]) == "(empty)"
    assert bm.field_value_str([1, 2]) == "[1,2]"  # compact separators
    assert bm.field_value_str({}) == "(empty)"
    assert bm.field_value_str({"a": 1}) == '{"a":1}'
    # long arrays/objects truncated at 500 (no '...' suffix — only strings
    # get the ellipsis); compact separators like JSON.stringify
    compact = json.dumps(list(range(100)), separators=(",", ":"))
    assert bm.field_value_str(list(range(100))) == compact[:500]
    truncated = bm.field_value_str(list(range(1000)))
    assert len(truncated) == 500
    assert not truncated.endswith("...")
