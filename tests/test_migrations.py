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
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg

from scripts.db import connect

REPO_ROOT = Path(__file__).resolve().parent.parent

DATASET_TIMESTAMPS = "0007_dataset_timestamps"
ORG_CREATED = "0008_organisation_created"
HARVEST_TIMESTAMPS = "0009_harvest_source_timestamps"
COLLECTION_DATE = "0010_collection_page_last_updated"
LLM_CREATED_AT = "0011_llm_created_at"
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


def _read_org_instants(url: str) -> dict[str, datetime | None]:
    """Read each sample organisation's created as a UTC-normalised instant."""
    out: dict[str, datetime | None] = {}
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(f"SET TIME ZONE '{SESSION_TZ}'")
        for slug in SAMPLES:
            cur.execute("SELECT created FROM organisations WHERE slug = %s", (slug,))
            got = cur.fetchone()[0]
            out[slug] = got.astimezone(UTC) if got is not None else None
    return out


def _read_harvest_instants(url: str, column: str) -> dict[str, datetime | None]:
    """Read each sample harvest source's `column` as a UTC-normalised
    instant. `column` is a literal from this module, never user input."""
    out: dict[str, datetime | None] = {}
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(f"SET TIME ZONE '{SESSION_TZ}'")
        for hs_id in SAMPLES:
            cur.execute(f"SELECT {column} FROM harvest_sources WHERE id = %s", (hs_id,))
            got = cur.fetchone()[0]
            out[hs_id] = got.astimezone(UTC) if got is not None else None
    return out


# date-only values plus a timestamp truncated to its date.
DATE_SAMPLES = {
    "date_only": ("2026-03-24", date(2026, 3, 24)),
    "naive_t": ("2010-07-09T16:02:42.310217", date(2010, 7, 9)),
    "empty": ("", None),
    "null": (None, None),
}


def _read_collection_dates(url: str) -> dict[str, date | None]:
    """Read each sample collection's page_last_updated as a plain date."""
    out: dict[str, date | None] = {}
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        for slug in DATE_SAMPLES:
            cur.execute("SELECT page_last_updated FROM collection_pages WHERE slug = %s", (slug,))
            out[slug] = cur.fetchone()[0]
    return out


def test_dataset_timestamps_are_pinned_to_utc(migration_db_url):
    """Every input shape converts to the exact same instant in UTC — not one
    shifted by the session timezone (Europe/London in summer). The reverse
    migration is lossy in *format* (space/Z become T) but must preserve the
    instant, so the round-trip is asserted too."""
    # Fresh DB: apply up to the last text-schema migration (0006) forwards
    # from empty. Going forward avoids having to unwind the irreversible
    # later migrations (0008+) just to get back to text columns.
    _migrate(migration_db_url, "explorer", PREVIOUS)

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


def test_organisation_created_is_pinned_to_utc(migration_db_url):
    """The organisations.created conversion (0008) has the same timezone
    trap as datasets — assert every input shape round-trips to UTC."""
    _migrate(migration_db_url, "explorer", DATASET_TIMESTAMPS)  # 0007: text created

    with psycopg.connect(migration_db_url) as conn, conn.cursor() as cur:
        cur.execute(f"SET TIME ZONE '{SESSION_TZ}'")
        for slug, (created, _expected) in SAMPLES.items():
            cur.execute("INSERT INTO organisations (slug, created) VALUES (%s, %s)", (slug, created))

    _migrate(migration_db_url, "explorer", ORG_CREATED)
    assert _read_org_instants(migration_db_url) == {slug: expected for slug, (_c, expected) in SAMPLES.items()}


def test_harvest_source_timestamps_are_pinned_to_utc(migration_db_url):
    """harvest_sources.created and last_run (0009) share the datasets/orgs
    timezone trap: both are space-separated naive UTC. Empty strings must
    become NULL (25 live last_run rows are empty) rather than fail the cast."""
    _migrate(migration_db_url, "explorer", ORG_CREATED)  # 0008: text timestamps

    with psycopg.connect(migration_db_url) as conn, conn.cursor() as cur:
        cur.execute(f"SET TIME ZONE '{SESSION_TZ}'")
        for hs_id, (value, _expected) in SAMPLES.items():
            cur.execute(
                "INSERT INTO harvest_sources (id, created, last_run) VALUES (%s, %s, %s)",
                (hs_id, value, value),
            )

    _migrate(migration_db_url, "explorer", HARVEST_TIMESTAMPS)
    expected = {hs_id: expected for hs_id, (_v, expected) in SAMPLES.items()}
    assert _read_harvest_instants(migration_db_url, "created") == expected
    assert _read_harvest_instants(migration_db_url, "last_run") == expected


def test_collection_page_last_updated_converts_to_date(migration_db_url):
    """collection_pages.page_last_updated (0010) is date-only: the cast is a
    plain `::date` (no timezone applies), and empty becomes NULL."""
    _migrate(migration_db_url, "explorer", HARVEST_TIMESTAMPS)  # 0009: text date

    insert = "INSERT INTO collection_pages (slug, collection, title, page_last_updated) VALUES (%s, 'test', 'Test', %s)"
    with psycopg.connect(migration_db_url) as conn, conn.cursor() as cur:
        for slug, (value, _expected) in DATE_SAMPLES.items():
            cur.execute(insert, (slug, value))

    _migrate(migration_db_url, "explorer", COLLECTION_DATE)
    # Every sample truncates to its date component; empty and null stay NULL.
    assert _read_collection_dates(migration_db_url) == {slug: expected for slug, (_v, expected) in DATE_SAMPLES.items()}


def _read_llm_instants(url: str, table: str) -> dict[str, datetime | None]:
    """Read each sample's created_at as a UTC-normalised instant. `table` is a
    literal from this module, never user input."""
    out: dict[str, datetime | None] = {}
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(f"SET TIME ZONE '{SESSION_TZ}'")
        for ckan_id in SAMPLES:
            cur.execute(
                f"SELECT t.created_at FROM {table} t JOIN datasets d ON d.id = t.dataset_id WHERE d.ckan_id = %s",
                (ckan_id,),
            )
            got = cur.fetchone()[0]
            out[ckan_id] = got.astimezone(UTC) if got is not None else None
    return out


def test_llm_created_at_is_pinned_to_utc(migration_db_url):
    """reviews/suggestions.created_at (0011) share the datasets timezone trap
    even though the live pipeline writes a trailing `Z` — assert every shape
    lands on the same UTC instant."""
    _migrate(migration_db_url, "explorer", COLLECTION_DATE)  # 0010: text created_at

    with psycopg.connect(migration_db_url) as conn, conn.cursor() as cur:
        cur.execute(f"SET TIME ZONE '{SESSION_TZ}'")
        for ckan_id, (value, _expected) in SAMPLES.items():
            cur.execute(
                "INSERT INTO datasets (ckan_id, org_slug) VALUES (%s, 'test-org') RETURNING id",
                (ckan_id,),
            )
            ds_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO reviews (dataset_id, created_at, json) VALUES (%s, %s, '{}')",
                (ds_id, value),
            )
            cur.execute(
                "INSERT INTO suggestions (dataset_id, created_at, json) VALUES (%s, %s, '{}')",
                (ds_id, value),
            )

    _migrate(migration_db_url, "explorer", LLM_CREATED_AT)
    expected = {ckan_id: expected for ckan_id, (_v, expected) in SAMPLES.items()}
    assert _read_llm_instants(migration_db_url, "reviews") == expected
    assert _read_llm_instants(migration_db_url, "suggestions") == expected


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
