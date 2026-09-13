"""Scratch-DB tests for the write path in ``scripts/build_series.py``.

``test_build_series.py`` covers series detection offline. This file runs the
real ``_write_series()`` against a throwaway migrated database: the two
INSERTs, the ``RETURNING id`` join, and the derived ``dataset_count`` /
``org_count``. Never touches the dev DB — see ``tests/conftest.py``.
"""

from scripts import db
from scripts.build_series import TRUNCATE_SQL, _write_series


def ds(dataset_id, title, org_slug, org_display_name, date=None):
    """A dataset dict as ``build_all_series`` emits it (``date`` only when
    the row came from a date-suffix cluster)."""
    row = {
        "id": dataset_id,
        "title": title,
        "org_slug": org_slug,
        "org_display_name": org_display_name,
    }
    if date is not None:
        row["date"] = date
    return row


def test_write_series_round_trip(migrated_db_url):
    d = db.connect(migrated_db_url)
    try:
        d.exec(TRUNCATE_SQL)
        all_series = [
            {
                "root_title": "Conservation Areas",
                "type": "template",
                "datasets": [
                    ds("bs-1", "Conservation Areas", "alpha", "Alpha"),
                    ds("bs-2", "conservation areas", "beta", "Beta"),
                    ds("bs-3", "CONSERVATION AREAS", "alpha", "Alpha"),
                ],
            },
            {
                "root_title": "Expenditure",
                "type": "timeseries",
                "datasets": [
                    ds("bs-4", "Expenditure 2020", "alpha", "Alpha", date="2020"),
                    ds("bs-5", "Expenditure 2021", "alpha", "Alpha", date="2021"),
                ],
            },
        ]

        d.transaction(lambda tx: _write_series(tx, all_series))

        # dataset_count is len(datasets); org_count dedups org_slug (alpha
        # appears twice in series 1).
        assert d.prepare(
            "SELECT id, root_title, type, dataset_count, org_count FROM series ORDER BY id",
        ).all() == [
            {
                "id": 1,
                "root_title": "Conservation Areas",
                "type": "template",
                "dataset_count": 3,
                "org_count": 2,
            },
            {
                "id": 2,
                "root_title": "Expenditure",
                "type": "timeseries",
                "dataset_count": 2,
                "org_count": 1,
            },
        ]

        assert d.prepare(
            "SELECT series_id, dataset_id, dataset_title, date_suffix, org_slug,"
            " org_display_name FROM series_datasets ORDER BY series_id, dataset_id",
        ).all() == [
            {
                "series_id": 1,
                "dataset_id": "bs-1",
                "dataset_title": "Conservation Areas",
                "date_suffix": None,  # exact-title rows carry no date
                "org_slug": "alpha",
                "org_display_name": "Alpha",
            },
            {
                "series_id": 1,
                "dataset_id": "bs-2",
                "dataset_title": "conservation areas",
                "date_suffix": None,
                "org_slug": "beta",
                "org_display_name": "Beta",
            },
            {
                "series_id": 1,
                "dataset_id": "bs-3",
                "dataset_title": "CONSERVATION AREAS",
                "date_suffix": None,
                "org_slug": "alpha",
                "org_display_name": "Alpha",
            },
            {
                "series_id": 2,
                "dataset_id": "bs-4",
                "dataset_title": "Expenditure 2020",
                "date_suffix": "2020",
                "org_slug": "alpha",
                "org_display_name": "Alpha",
            },
            {
                "series_id": 2,
                "dataset_id": "bs-5",
                "dataset_title": "Expenditure 2021",
                "date_suffix": "2021",
                "org_slug": "alpha",
                "org_display_name": "Alpha",
            },
        ]
    finally:
        d.close()
