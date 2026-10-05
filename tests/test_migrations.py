"""Migration regression tests for the text→timestamptz conversions.

The timezone trap: casting a naive text value straight to timestamptz uses
the session TimeZone (the dev server defaults to Europe/London), silently
shifting every summer timestamp by an hour. These tests rewind a scratch
database to the previous migration, insert the real-world formats, migrate
forward, and assert the instants are UTC-pinned. They also guard the
pipeline write path (``scripts/db.py``), which passes naive strings straight
into the now-typed columns.

The dedicated ``migration_db_url`` DB keeps the rewind from disturbing the
fully-migrated database the other scratch-DB tests share.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from scripts.db import connect

REPO_ROOT = Path(__file__).resolve().parent.parent

DATASET_TIMESTAMPS = "0007_dataset_timestamps"
PREVIOUS = "0006_harvest_sources_stats_columns"

# The dev server's timezone — deliberately not UTC, so a naive cast that
# relied on the session zone would fail these assertions.
SESSION_TZ = "Europe/London"


def _migrate(url: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 — args are fixed literals from this module
        [sys.executable, "manage.py", "migrate", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
    )


def _insert_dataset(cur, ckan_id: str, created, modified) -> None:
    cur.execute(
        "INSERT INTO datasets (ckan_id, org_slug, metadata_created, metadata_modified) VALUES (%s, %s, %s, %s)",
        (ckan_id, "test-org", created, modified),
    )


# One row per real-world input shape (see the conversion CASE in 0007).
SAMPLES = {
    "naive_t": ("2010-07-09T16:02:42.310217", datetime(2010, 7, 9, 16, 2, 42, 310217, tzinfo=UTC)),
    "space_sep": ("2011-06-03 10:47:22.294146", datetime(2011, 6, 3, 10, 47, 22, 294146, tzinfo=UTC)),
    "zulu": ("2026-09-29T15:31:55.505Z", datetime(2026, 9, 29, 15, 31, 55, 505000, tzinfo=UTC)),
    "date_only": ("2026-03-24", datetime(2026, 3, 24, tzinfo=UTC)),
    "offset": ("2021-01-31T23:30:00-05:00", datetime(2021, 2, 1, 4, 30, tzinfo=UTC)),
    "empty": ("", None),
    "null": (None, None),
}


def _read_instants(url: str) -> dict[str, datetime | None]:
    """Read each sample's metadata_created as a UTC-normalised instant."""
    out: dict[str, datetime | None] = {}
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(f"SET TIME ZONE '{SESSION_TZ}'")
        for ckan_id in SAMPLES:
            cur.execute("SELECT metadata_created FROM datasets WHERE ckan_id = %s", (ckan_id,))
            got = cur.fetchone()[0]
            out[ckan_id] = got.astimezone(UTC) if got is not None else None
    return out


def test_dataset_timestamps_are_pinned_to_utc(migration_db_url):
    """Every input shape converts to the exact same instant in UTC — not one
    shifted by the session timezone (Europe/London in summer). The reverse
    migration is lossy in *format* (space/Z become T) but must preserve the
    instant, so the round-trip is asserted too."""
    _migrate(migration_db_url)  # full schema
    _migrate(migration_db_url, "explorer", PREVIOUS)  # columns back to text

    with psycopg.connect(migration_db_url) as conn, conn.cursor() as cur:
        cur.execute(f"SET TIME ZONE '{SESSION_TZ}'")
        for ckan_id, (created, _expected) in SAMPLES.items():
            _insert_dataset(cur, ckan_id, created, created)

    _migrate(migration_db_url, "explorer", DATASET_TIMESTAMPS)
    forward = _read_instants(migration_db_url)
    assert forward == {ckan_id: expected for ckan_id, (_c, expected) in SAMPLES.items()}

    # Reverse back to text, then forward again: the instants must survive.
    _migrate(migration_db_url, "explorer", PREVIOUS)
    _migrate(migration_db_url, "explorer", DATASET_TIMESTAMPS)
    assert _read_instants(migration_db_url) == forward


def test_pipeline_connection_stores_naive_strings_as_utc(migration_db_url):
    """scripts/db.py pins the session timezone to UTC, so the pipeline's
    naive ISO strings land as the same wall-clock instant."""
    _migrate(migration_db_url)  # idempotent — ensure the latest schema
    d = connect(migration_db_url)
    try:
        assert d.prepare("SHOW TimeZone").get() == {"TimeZone": "UTC"}
        d.exec("CREATE TEMP TABLE tz_probe (ts timestamptz)")
        d.prepare("INSERT INTO tz_probe (ts) VALUES (?)").run("2010-07-09T16:02:42.310217")
        got = d.prepare("SELECT ts FROM tz_probe").get()["ts"]
    finally:
        d.close()
    assert got.astimezone(UTC) == datetime(2010, 7, 9, 16, 2, 42, 310217, tzinfo=UTC)
