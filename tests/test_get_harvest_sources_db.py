"""Scratch-DB tests for the org-activity read in scripts/get_harvest_sources.py.

An org is active when it has a dataset modified within the lookback window,
so the script re-checks it for a newly added harvest source.
"""

from datetime import UTC, datetime, timedelta

from scripts.db import connect
from scripts.get_harvest_sources import active_org_slugs
from scripts.ingest_ckan import TRUNCATE_SQL


def _insert_dataset(db, ckan_id: str, org_slug: str, modified: str) -> None:
    db.prepare("INSERT INTO datasets (ckan_id, org_slug, metadata_modified) VALUES (?, ?, ?)").run(
        ckan_id,
        org_slug,
        modified,
    )


def test_active_org_slugs_uses_the_modified_window(migrated_db_url):
    now = datetime.now(UTC)
    db = connect(migrated_db_url)
    try:
        db.exec(TRUNCATE_SQL)
        _insert_dataset(db, "d1", "recent", (now - timedelta(days=1)).isoformat())
        _insert_dataset(db, "d2", "old", (now - timedelta(days=60)).isoformat())
    finally:
        db.close()

    assert active_org_slugs(30, url=migrated_db_url) == {"recent"}
    assert active_org_slugs(90, url=migrated_db_url) == {"recent", "old"}


def test_active_org_slugs_empty_window_is_empty_not_none(migrated_db_url):
    """Datasets exist but none changed in the window — a genuine quiet
    period, not an unavailable DB, so it must stay an empty set."""
    now = datetime.now(UTC)
    db = connect(migrated_db_url)
    try:
        db.exec(TRUNCATE_SQL)
        _insert_dataset(db, "d1", "old", (now - timedelta(days=400)).isoformat())
    finally:
        db.close()

    assert active_org_slugs(30, url=migrated_db_url) == set()


def test_active_org_slugs_empty_table_falls_back(migrated_db_url):
    """A migrated-but-never-built DB has no datasets; that must read as
    unavailable (None) so the caller walks every org instead of skipping
    them all as inactive."""
    db = connect(migrated_db_url)
    try:
        db.exec(TRUNCATE_SQL)
    finally:
        db.close()

    assert active_org_slugs(30, url=migrated_db_url) is None
