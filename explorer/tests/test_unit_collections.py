"""Unit tests for collections-specific logic.

_parse_filters: collection whitelist validation — the only collections-unique
guard (shared infrastructure: paginate, parse_sort, facet_where are covered
in their own unit-test files).

_collection_clause: the SQL clause builder for the collection facet.
"""

from django.test import RequestFactory

from explorer.queries.collections import _collection_clause
from explorer.views.collections import COLLECTION_LABELS, _parse_filters

_rf = RequestFactory()


def _req(qs=""):
    return _rf.get(f"/{qs}")


# --- _parse_filters ---


def test_parse_filters_no_collection():
    assert _parse_filters(_req()).collection is None


def test_parse_filters_valid_collection():
    for key in COLLECTION_LABELS:
        assert _parse_filters(_req(f"?collection={key}")).collection == key, key


def test_parse_filters_invalid_collection_rejected():
    assert _parse_filters(_req("?collection=bogus")).collection is None


def test_parse_filters_empty_collection_treated_as_none():
    assert _parse_filters(_req("?collection=")).collection is None


# --- _collection_clause ---


def test_collection_clause_active():
    clauses, params = _collection_clause({"collection": "environment"})
    assert clauses == ["c.collection = %s"]
    assert params == ["environment"]


def test_collection_clause_self_excluded():
    clauses, params = _collection_clause({"collection": "environment"}, exclude="collection")
    assert clauses == []
    assert params == []


def test_collection_clause_inactive():
    clauses, params = _collection_clause({})
    assert clauses == []
    assert params == []
