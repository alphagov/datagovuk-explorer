"""Scratch-DB tests for the last_run write path in
scripts/build_harvester_stats.py.

last_run is timestamptz now, but the source value is text from the harvest
record's json, so the build must cast it and map both the empty string and
the literal "None" (what the CKAN API writes) to NULL — either would raise
on the cast. The pipeline connection is UTC-pinned (scripts/db.py), so a
naive source timestamp lands as the same wall-clock instant.
"""

import json
from datetime import UTC, datetime

from scripts.build_harvester_stats import build
from scripts.db import connect
from scripts.ingest_ckan import TRUNCATE_SQL


def _insert_source(db, hs_id: str, last_harvest_request) -> None:
    status = {} if last_harvest_request is None else {"last_harvest_request": last_harvest_request}
    db.prepare("INSERT INTO harvest_sources (id, title, json) VALUES (?, ?, ?)").run(
        hs_id,
        hs_id,
        json.dumps({"status": status}),
    )


def test_build_casts_last_run_and_maps_empty_and_none_to_null(migrated_db_url):
    """A valid naive timestamp casts to the same UTC instant; "", the
    literal "None", and a missing key all become NULL rather than raising."""
    db = connect(migrated_db_url)
    try:
        db.exec(TRUNCATE_SQL)
        _insert_source(db, "hs-valid", "2011-06-03 10:47:22.294146")
        _insert_source(db, "hs-empty", "")
        _insert_source(db, "hs-none-str", "None")
        _insert_source(db, "hs-missing", None)
        db.prepare("INSERT INTO datasets (ckan_id, org_slug, harvest_source_id) VALUES (?, ?, ?)").run(
            "d1",
            "council-a",
            "hs-valid",
        )

        n = build(db)

        rows = {
            r["id"]: (r["last_run"], r["dataset_count"])
            for r in db.prepare("SELECT id, last_run, dataset_count FROM harvest_sources").all()
        }
    finally:
        db.close()

    assert n == 4
    assert rows["hs-valid"] == (datetime(2011, 6, 3, 10, 47, 22, 294146, tzinfo=UTC), 1)
    assert rows["hs-empty"][0] is None
    assert rows["hs-none-str"][0] is None
    assert rows["hs-missing"][0] is None
