"""Migration regression tests.

The text→timestamptz conversion work is complete and was squashed into a
single ``0001_initial`` (see docs/time-and-dates-plan.md), so the old
round-trip conversion tests (which migrated to intermediate revisions) are
gone. These tests guard the two things that outlive the conversion:

- the initial migration builds the *typed* schema directly, and still
  creates the raw ``mv_org_aggregates`` matview and the unread text column;
- the pipeline connection (``scripts/db.py``) pins its session to UTC, so
  the naive ISO strings the ingest scripts pass through land as the intended
  instant rather than shifted by the server's local zone.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from scripts.db import connect

REPO_ROOT = Path(__file__).resolve().parent.parent

# Tables whose timestamp columns must be real types, not text.
TYPED_COLUMNS = {
    "datasets": {
        "metadata_created": "timestamp with time zone",
        "metadata_modified": "timestamp with time zone",
    },
    "organisations": {"created": "timestamp with time zone"},
    "harvest_sources": {
        "created": "timestamp with time zone",
        "last_run": "timestamp with time zone",
    },
    "reviews": {"created_at": "timestamp with time zone"},
    "suggestions": {"created_at": "timestamp with time zone"},
    "collection_pages": {"page_last_updated": "date"},
}


def _migrate(url: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 — args are fixed literals from this module
        [sys.executable, "manage.py", "migrate", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
    )


def _column_type(cur, table: str, column: str) -> str:
    cur.execute(
        "SELECT data_type FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone()[0]


def test_initial_migration_builds_typed_schema(migration_db_url):
    """A fresh database gets the typed schema from the single initial
    migration — no text timestamps left (except the intentionally-unread
    ``links.created``), and the raw matview is present."""
    _migrate(migration_db_url)

    with psycopg.connect(migration_db_url) as conn, conn.cursor() as cur:
        for table, columns in TYPED_COLUMNS.items():
            for column, expected in columns.items():
                assert _column_type(cur, table, column) == expected, f"{table}.{column}"

        # links.created is deliberately left text (nothing reads it).
        assert _column_type(cur, "links", "created") == "text"

        cur.execute("SELECT count(*) FROM pg_matviews WHERE matviewname = 'mv_org_aggregates'")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM pg_tables WHERE tablename = 'org_link_health'")
        assert cur.fetchone()[0] == 1


def test_pipeline_connection_stores_naive_strings_as_utc(migration_db_url):
    """scripts/db.py pins the session timezone to UTC, so the pipeline's
    naive ISO strings land as the same wall-clock instant."""
    d = connect(migration_db_url)
    try:
        assert d.prepare("SHOW TimeZone").get() == {"TimeZone": "UTC"}
        d.exec("CREATE TEMP TABLE tz_probe (ts timestamptz)")
        d.prepare("INSERT INTO tz_probe (ts) VALUES (?)").run("2010-07-09T16:02:42.310217")
        got = d.prepare("SELECT ts FROM tz_probe").get()["ts"]
    finally:
        d.close()
    assert got.astimezone(UTC) == datetime(2010, 7, 9, 16, 2, 42, 310217, tzinfo=UTC)
