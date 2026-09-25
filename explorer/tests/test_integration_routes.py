"""One parametrized smoke over every route in config/urls.py.

Each route renders against the seeded fixture DB; the assertion is only that
the page responds (200). Content/data contracts live at the query layer
(test_integration_queries.py) and the small page-unique behaviour suite
(test_integration_view_behavior.py) — this is route wiring + template render
coverage.

Non-default `?sort=&dir=` and `?page=2` variants are included (respond-only)
so those branches can't crash green.
"""

import pytest

from explorer.queries.reports import REPORTS

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


# Every dynamic route uses a known fixture id (root conftest.py FIXTURE).
BASE_ROUTES = [
    ("/", {}),
    ("/health", {}),
    ("/organisation/alpha", {}),
    ("/organisations", {}),
    ("/harvesters", {}),
    ("/harvester/hs1", {}),
    ("/links", {}),
    ("/links/status", {}),
    ("/datasets", {}),
    ("/collections", {}),
    ("/dataset/alpha/d01", {}),
    ("/series", {}),
    ("/series/1", {}),
    ("/metadata", {}),
    ("/metadata/top/type", {}),
    ("/reviews", {}),
    ("/suggestions", {}),
    ("/search", {"q": "flood"}),
    ("/search/publishers", {"q": "alpha"}),
    ("/search/datasets", {"q": "flood"}),
    ("/api/publishers", {"q": "al"}),
    # Duplicate-content detail mode (?hash=) — see root conftest.py's
    # DatasetContentHash fixture (d01/d09 share "hash-shared-d01-d09").
    ("/report/datasets-duplicate-content", {"hash": "hash-shared-d01-d09"}),
]

# Respond-only: exercise a non-default sort/dir and a page-2 branch per
# sortable route (one case per route; no order/content assertions).
SORTABLE_ROUTES = [
    ("/organisations", {"sort": "dataset_count", "dir": "desc"}),
    ("/harvesters", {"sort": "dataset_count", "dir": "desc"}),
    ("/harvester/hs1", {"sort": "metadata_modified", "dir": "desc"}),
    ("/links", {"sort": "name", "dir": "desc"}),
    ("/links/status", {"sort": "url", "dir": "desc"}),
    ("/datasets", {"sort": "resources", "dir": "desc"}),
    ("/collections", {"sort": "title", "dir": "asc"}),
    ("/organisation/alpha", {"sort": "metadata_modified", "dir": "desc"}),
    ("/reviews", {"sort": "overall", "dir": "desc"}),
    ("/suggestions", {"sort": "confidence", "dir": "desc"}),
    ("/series", {"sort": "dataset_count", "dir": "desc"}),
]


@pytest.mark.parametrize(("path", "params"), BASE_ROUTES)
def test_route_responds(client, path, params):
    response = client.get(path, params)
    assert response.status_code == 200, f"{path} {params} -> {response.status_code}"


@pytest.mark.parametrize(("path", "sort_params"), SORTABLE_ROUTES)
def test_route_responds_non_default_sort_and_page(client, path, sort_params):
    assert client.get(path, sort_params).status_code == 200, f"{path} {sort_params}"
    assert client.get(path, {"page": "2"}).status_code == 200, f"{path} ?page=2"


@pytest.mark.parametrize("key", [report["key"] for report in REPORTS])
def test_every_report_route_responds(client, key):
    response = client.get(f"/report/{key}")
    assert response.status_code == 200, f"/report/{key} -> {response.status_code}"


def test_unknown_route_404s(client):
    assert client.get("/report/no-such-report").status_code == 404
    assert client.get("/organisation/no-such-org").status_code == 404
    assert client.get("/harvester/no-such-source").status_code == 404
    assert client.get("/dataset/alpha/no-such-dataset").status_code == 404
    assert client.get("/series/abc").status_code == 404
    assert client.get("/metadata/bogus/type").status_code == 404
