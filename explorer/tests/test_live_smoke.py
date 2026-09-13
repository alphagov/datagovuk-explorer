"""Opt-in smoke against the full live dev database.

Run with ``just test-live``. These checks prove the real snapshot is loaded
and a few pages render — nothing that depends on exact content or counts, so
they don't break when the data is rebuilt.

The fixture DB rewrites the default connection, so live and fixture tests
cannot share a pytest session; that is why this layer is a separate marker
rather than part of ``just test``.
"""

import pytest
from django.db import connection

from explorer.queries.datasets import DATASET_TOTAL
from explorer.queries.reports import REPORTS

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def _unblock_live_db(django_db_blocker):
    """The live layer reads the real DB directly (no test database)."""
    with django_db_blocker.unblock():
        yield


def _live_dataset_count():
    """Fail loudly if the live DB is missing or empty — `just test-live` is
    an explicit request for the snapshot, not a silent skip to green. Also
    guards against running after the fixture DB rewrote the connection
    (e.g. `just test-all`), which would otherwise look green against the
    seed."""
    name = connection.settings_dict["NAME"]
    assert not str(name).startswith("test_"), (
        f"live smoke is reading the test database ({name}); run `just test-live` alone"
    )
    with connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM datasets")
        count = cur.fetchone()[0]
    assert count > 0, "live database is empty — run the pipeline (just build-db)"
    return count


def test_snapshot_is_loaded():
    count = _live_dataset_count()
    assert DATASET_TOTAL.get()["n"] == count


def test_key_pages_respond(client):
    _live_dataset_count()
    for path in (
        "/",
        "/datasets",
        "/links",
        "/links/errors",
        "/organisations",
        "/harvesters",
        "/reviews",
        "/suggestions",
    ):
        assert client.get(path).status_code == 200, path


def test_every_report_responds(client):
    _live_dataset_count()
    for report in REPORTS:
        assert client.get(f"/report/{report['key']}").status_code == 200, report["key"]
