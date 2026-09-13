"""Scratch-DB tests for the write path in ``scripts/ingest_link_errors.py``.

``test_ingest_link_errors.py`` covers CSV parsing offline. This file runs
the real ``ingest()`` (TRUNCATE + dynamic-COLUMNS INSERT) against a
throwaway migrated database, so the hand-copied column list can't drift
from the table unnoticed. Never touches the dev DB — see ``tests/conftest.py``.
"""

from scripts import db
from scripts.ingest_link_errors import COLUMNS, ingest


def row(**over):
    """A parsed row with every column set; override the ones under test.

    ``parse_row`` always returns every COLUMNS key, so the helper matches
    that shape — a missing key here would be a KeyError, which is the point.
    """
    r = dict.fromkeys(COLUMNS, "")
    r.update(
        {
            "package_id": "pkg",
            "resource_id": "res",
            "http_status": 200,
            "to_delete": False,
            "checked_at": "2026-08-01T00:00:00Z",
        },
    )
    r.update(over)
    return r


def test_ingest_round_trip(migrated_db_url):
    d = db.connect(migrated_db_url)
    try:
        rows = [
            row(
                package_id="p1",
                resource_id="r1",
                http_status=404,
                category="Not found",
                org_name="Alpha",
            ),
            # A resolved link: no HTTP response, flagged for deletion.
            row(package_id="p2", resource_id="r2", http_status=None, to_delete=True, category="OK"),
        ]

        assert ingest(d, iter(rows)) == 2

        assert d.prepare(
            "SELECT package_id, resource_id, http_status, to_delete, category, org_name,"
            " checked_at FROM link_errors ORDER BY package_id",
        ).all() == [
            {
                "package_id": "p1",
                "resource_id": "r1",
                "http_status": 404,
                "to_delete": False,
                "category": "Not found",
                "org_name": "Alpha",
                "checked_at": "2026-08-01T00:00:00Z",
            },
            {
                "package_id": "p2",
                "resource_id": "r2",
                "http_status": None,
                "to_delete": True,
                "category": "OK",
                "org_name": "",  # empty CSV cells stay '' (byte-for-byte)
                "checked_at": "2026-08-01T00:00:00Z",
            },
        ]
    finally:
        d.close()


def test_ingest_is_idempotent(migrated_db_url):
    d = db.connect(migrated_db_url)
    try:
        rows = [row(package_id="p3", resource_id="r3")]
        assert ingest(d, iter(rows)) == 1
        assert ingest(d, iter(rows)) == 1  # TRUNCATE, not append
        assert d.prepare("SELECT COUNT(*) AS n FROM link_errors").get() == {"n": 1}
    finally:
        d.close()
