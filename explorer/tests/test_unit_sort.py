"""Unit tests for explorer.sort.sort_resources — the in-place sorter behind
the dataset page's resource table (?sort=...).

Plain lists of dicts, no DB: these lock in the ordering the table relies on —
natural (case-insensitive, numeric-aware) text, missing values last, and the
last_modified → created fallback.
"""

from explorer.sort import sort_resources


def _names(rows):
    return [r["name"] for r in rows]


def test_text_sort_is_case_insensitive_and_numeric_aware():
    rows = [{"name": "zebra"}, {"name": "Dataset 10"}, {"name": "dataset 2"}, {"name": "Apple"}]
    sort_resources(rows, "name", "asc")
    assert _names(rows) == ["Apple", "dataset 2", "Dataset 10", "zebra"]


def test_desc_reverses_order():
    rows = [{"name": "b"}, {"name": "c"}, {"name": "a"}]
    sort_resources(rows, "name", "desc")
    assert _names(rows) == ["c", "b", "a"]


def test_position_sort_puts_missing_last():
    rows = [{"name": "b", "position": 2}, {"name": "c"}, {"name": "a", "position": 1}]
    sort_resources(rows, "position", "asc")
    assert _names(rows) == ["a", "b", "c"]


def test_size_sort_is_numeric_with_non_numeric_last():
    rows = [{"name": "big", "size": 1000}, {"name": "none"}, {"name": "small", "size": 200}]
    sort_resources(rows, "size", "asc")
    assert _names(rows) == ["small", "big", "none"]


def test_last_modified_falls_back_to_created():
    rows = [
        {"name": "a", "last_modified": "2021-01-01"},
        {"name": "b", "created": "2020-01-01"},
        {"name": "c", "last_modified": "2022-01-01"},
    ]
    sort_resources(rows, "last_modified", "asc")
    assert _names(rows) == ["b", "a", "c"]
