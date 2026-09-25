"""Unit tests for collections-specific logic.

_parse_filters: category whitelist validation — the only collections-unique
guard (shared infrastructure: paginate, parse_sort, facet_where are covered
in their own unit-test files).

_category_clause: the SQL clause builder for the category facet.
"""

from django.test import RequestFactory

from explorer.queries.collections import _category_clause
from explorer.views.collections import CATEGORY_LABELS, _parse_filters

_rf = RequestFactory()


def _req(qs=""):
    return _rf.get(f"/{qs}")


# --- _parse_filters ---


def test_parse_filters_no_category():
    assert _parse_filters(_req()).category is None


def test_parse_filters_valid_category():
    for key in CATEGORY_LABELS:
        assert _parse_filters(_req(f"?category={key}")).category == key, key


def test_parse_filters_invalid_category_rejected():
    assert _parse_filters(_req("?category=bogus")).category is None


def test_parse_filters_empty_category_treated_as_none():
    assert _parse_filters(_req("?category=")).category is None


# --- _category_clause ---


def test_category_clause_active():
    clauses, params = _category_clause({"category": "environment"})
    assert clauses == ["c.category = %s"]
    assert params == ["environment"]


def test_category_clause_self_excluded():
    clauses, params = _category_clause({"category": "environment"}, exclude="category")
    assert clauses == []
    assert params == []


def test_category_clause_inactive():
    clauses, params = _category_clause({})
    assert clauses == []
    assert params == []
