"""Scratch-DB tests for the dataset_content_hash write path in
scripts/build_db.py.

Runs the real INSERT_DATASET_CONTENT_HASH_SQL (via
_populate_dataset_content_hash) against a throwaway migrated database:
normalisation of title/notes whitespace+case, the resource-URL set
(order-independent, query-string/fragment/trailing-slash stripped,
deduped), and that datasets with no links still get a hash. Never touches
the dev DB — see tests/conftest.py.
"""

from scripts.build_db import TRUNCATE_SQL, _populate_dataset_content_hash
from scripts.db import connect


def insert_dataset(db, id_, title, notes, org_slug="council-a"):
    db.prepare(
        "INSERT INTO datasets (id, org_slug, title, notes) VALUES (?, ?, ?, ?)",
    ).run(id_, org_slug, title, notes)


def insert_link(db, dataset_id, url):
    db.prepare(
        "INSERT INTO links (dataset_id, org_slug, url) VALUES (?, 'council-a', ?)",
    ).run(dataset_id, url)


def hashes(db) -> dict:
    rows = db.prepare("SELECT dataset_id, content_hash FROM dataset_content_hash").all()
    return {r["dataset_id"]: r["content_hash"] for r in rows}


def test_identical_content_hashes_match(migrated_db_url):
    db = connect(migrated_db_url)
    try:
        db.exec(TRUNCATE_SQL)
        insert_dataset(db, "d1", "Tree Preservation Orders", "All TPOs in the borough")
        insert_dataset(db, "d2", "Tree Preservation Orders", "All TPOs in the borough")
        insert_link(db, "d1", "https://example.com/tpo.csv")
        insert_link(db, "d2", "https://example.com/tpo.csv")

        _populate_dataset_content_hash(db)
        h = hashes(db)

        assert h["d1"] == h["d2"]
    finally:
        db.close()


def test_whitespace_and_case_are_normalised(migrated_db_url):
    db = connect(migrated_db_url)
    try:
        db.exec(TRUNCATE_SQL)
        insert_dataset(db, "d1", "Tree Preservation Orders", "All TPOs  in the borough")
        insert_dataset(db, "d2", "  tree   preservation orders", "all tpos in the borough")
        insert_link(db, "d1", "https://example.com/tpo.csv")
        insert_link(db, "d2", "HTTPS://EXAMPLE.COM/tpo.csv")

        _populate_dataset_content_hash(db)
        h = hashes(db)

        assert h["d1"] == h["d2"]
    finally:
        db.close()


def test_url_query_string_fragment_and_trailing_slash_ignored(migrated_db_url):
    db = connect(migrated_db_url)
    try:
        db.exec(TRUNCATE_SQL)
        insert_dataset(db, "d1", "Bins", "Collection schedule")
        insert_dataset(db, "d2", "Bins", "Collection schedule")
        insert_link(db, "d1", "https://example.com/bins.csv")
        insert_link(db, "d2", "https://example.com/bins.csv/?utm_source=x#section")

        _populate_dataset_content_hash(db)
        h = hashes(db)

        assert h["d1"] == h["d2"]
    finally:
        db.close()


def test_url_set_is_order_independent_and_deduped(migrated_db_url):
    db = connect(migrated_db_url)
    try:
        db.exec(TRUNCATE_SQL)
        insert_dataset(db, "d1", "Bins", "Collection schedule")
        insert_dataset(db, "d2", "Bins", "Collection schedule")
        insert_link(db, "d1", "https://example.com/a.csv")
        insert_link(db, "d1", "https://example.com/b.csv")
        # d2: same two URLs, reverse insertion order, plus a duplicate of
        # one of them (repeated resources shouldn't change the hash).
        insert_link(db, "d2", "https://example.com/b.csv")
        insert_link(db, "d2", "https://example.com/a.csv")
        insert_link(db, "d2", "https://example.com/a.csv")

        _populate_dataset_content_hash(db)
        h = hashes(db)

        assert h["d1"] == h["d2"]
    finally:
        db.close()


def test_different_content_hashes_differ(migrated_db_url):
    db = connect(migrated_db_url)
    try:
        db.exec(TRUNCATE_SQL)
        insert_dataset(db, "d1", "Tree Preservation Orders", "All TPOs in the borough")
        insert_dataset(db, "d2", "Allotment Waiting Lists", "Current waiting list positions")
        insert_link(db, "d1", "https://example.com/tpo.csv")
        insert_link(db, "d2", "https://example.com/allotments.csv")

        _populate_dataset_content_hash(db)
        h = hashes(db)

        assert h["d1"] != h["d2"]
    finally:
        db.close()


def test_dataset_with_no_links_still_gets_a_hash(migrated_db_url):
    db = connect(migrated_db_url)
    try:
        db.exec(TRUNCATE_SQL)
        insert_dataset(db, "d1", "No resources here", "Just metadata, no links")

        n = _populate_dataset_content_hash(db)
        h = hashes(db)

        assert n == 1
        assert h["d1"] is not None
    finally:
        db.close()


def test_populate_returns_row_count(migrated_db_url):
    db = connect(migrated_db_url)
    try:
        db.exec(TRUNCATE_SQL)
        insert_dataset(db, "d1", "Bins", "Collection schedule")
        insert_dataset(db, "d2", "Allotments", "Waiting list")

        n = _populate_dataset_content_hash(db)

        assert n == 2
    finally:
        db.close()
