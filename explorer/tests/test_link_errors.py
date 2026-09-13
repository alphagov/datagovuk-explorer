"""Interim live view tests for /links/errors (plan Phase 5 will replace them).

The query-layer tests moved to ``test_integration_link_errors.py`` (fixture
DB). What is left here is the render/template coverage that still reads the
live dev DB — Phase 5 rewrites it into the fixture-backed behaviour suite
(``test_integration_view_behavior.py``) and deletes it. Until then it is
gated behind the ``live`` marker so ``just test`` never runs it.
"""

import re

import pytest

from explorer.queries.link_errors import link_errors_facet_counts, link_errors_stats

pytestmark = [pytest.mark.live, pytest.mark.usefixtures("db_ready")]


@pytest.fixture(scope="module")
def link_errors_loaded():
    """The link_errors table exists and has rows (migration + ingest ran)."""
    try:
        n = link_errors_stats()["total"]
    except Exception as e:  # noqa: BLE001 — table missing / DB not migrated
        pytest.skip(f"link_errors table unavailable: {e}")
    if not n:
        pytest.skip("link_errors is empty — run: just ingest-link-errors")
    return n


def _squash(html: str) -> str:
    """Collapse whitespace runs to single spaces — djlint reflows long
    template tags/attributes onto several lines, so rendered markup carries
    harmless newlines the exact-match assertions must not trip on."""
    return re.sub(r"\s+", " ", html)


def _has_badge(html: str, cls: str, label: str) -> bool:
    """A harvest-state badge span with the given class and label — the
    harvested badge optionally carries a title (its harvest source), so
    the match allows for that attribute."""
    return (
        re.search(
            rf'<span class="badge {cls}"(?: title="[^"]*")?>\s*{re.escape(label)}\s*</span>',
            _squash(html),
        )
        is not None
    )


def test_link_errors_view(client, link_errors_loaded):
    r = client.get("/links/errors")
    html = _squash(r.content.decode())
    assert r.status_code == 200
    assert "Link errors" in html

    assert '<h1 class="nav-link nav-link--active" aria-current="page">Errors</h1>' in html
    assert '<a href="/links" class="nav-link">Links</a>' in html
    assert f"{link_errors_loaded:,} errors" in html

    assert _has_badge(client.get("/links/errors?harvested=harvested").content.decode(), "badge-harvested", "Harvested")
    assert _has_badge(client.get("/links/errors?harvested=manual").content.decode(), "badge-manual", "Manual")
    assert _has_badge(client.get("/links/errors?harvested=unknown").content.decode(), "badge-unknown", "Unknown")

    ok = _squash(client.get("/links/errors?category=OK").content.decode())
    assert "link-errors-row--ok" in ok
    assert '<span class="status status--ok"' in ok

    assert '<td class="col-text">Yes</td>' in _squash(
        client.get("/links/errors?sort=to_delete&dir=desc").content.decode(),
    )
    assert '<td class="col-text">No</td>' in _squash(
        client.get("/links/errors?sort=to_delete&dir=asc").content.decode(),
    )

    yes = _squash(client.get("/links/errors?to_delete=yes").content.decode())
    assert "filter-pill" in yes
    assert 'class="facet-group" aria-label="Filter by the remove-link recommendation"' in yes
    assert '<td class="col-text">No</td>' not in yes

    assert 'class="facet-group" aria-label="Filter by domain"' in html
    assert "No URL" in html
    assert "More domains" in html
    assert 'aria-label="Search domains"' in html
    assert 'aria-label="Search publishers"' in html
    assert html.count('class="facet-search-input"') == 2
    assert "/static/facet-search.js" in html
    all_hosts = _squash(client.get("/links/errors?domains=all").content.decode())
    assert "Fewer domains" in all_hosts
    no_url = _squash(client.get("/links/errors?domain=__none__").content.decode())
    assert 'class="filter-pill"' in no_url

    assert 'class="facet-group" aria-label="Filter by publisher"' in html
    assert "More publishers" in html
    all_pubs = _squash(client.get("/links/errors?publishers=all").content.decode())
    assert "Fewer publishers" in all_pubs

    top = link_errors_facet_counts({})["publishers"][0]
    assert top["name"] in html
    pub_rows = _squash(client.get("/links/errors", {"publisher": top["value"]}).content.decode())
    assert f'<a href="/organisation/{top["value"]}">{top["name"]}</a>' in pub_rows


def test_link_errors_filters_and_pills(client, link_errors_loaded):
    r = client.get("/links/errors?status=404&category=NOT_FOUND")
    assert r.status_code == 200
    assert "404 Not found" in r.content.decode()
    assert 'class="filter-pill"' in r.content.decode()

    r = client.get("/links/errors?status=__none__")
    assert r.status_code == 200
    assert "No response" in r.content.decode()

    assert client.get("/links/errors?page=99999").status_code == 200
