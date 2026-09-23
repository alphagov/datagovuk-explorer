"""Unit tests for scripts/get_organisations.py (offline — no live API).

Covers the deterministic parts, mirroring tests/test_get_harvest_sources.py:
- get_organisations: the cheap names call, then paged all_fields fetches in
  chunks of PAGE_SIZE, with the right pagination params
- error paths: HTTP error, success:false on the names call and on a page
- write_json round-trip
- main(): end-to-end happy path writes organisations.json, incl. the
  display_name/package_count fallbacks

Run with: uv run python -m pytest tests/test_get_organisations.py
"""

import json

import httpx
import pytest

import scripts.get_organisations

PAGE_SIZE = scripts.get_organisations.PAGE_SIZE


def make_org(i: int) -> dict:
    return {
        "id": f"org-{i:04d}",
        "name": f"org-{i}",
        "display_name": f"Org {i}",
        "description": f"Description for org {i}",
        "package_count": i,
    }


def test_get_organisations_pages_with_all_fields():
    total = 60  # 3 pages at PAGE_SIZE=25
    orgs = [make_org(i) for i in range(total)]
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "all_fields" not in request.url.params:
            # the cheap names call: no all_fields, no pagination
            return httpx.Response(
                200,
                json={"success": True, "result": [o["name"] for o in orgs]},
            )
        captured.append(dict(request.url.params))
        offset = int(captured[-1]["offset"])
        limit = int(captured[-1]["limit"])
        return httpx.Response(200, json={"success": True, "result": orgs[offset : offset + limit]})

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        result = scripts.get_organisations.get_organisations(client)

    assert result == orgs
    # paginated at PAGE_SIZE with offset stepping, all_fields requested
    assert [p["limit"] for p in captured] == [str(PAGE_SIZE)] * 3
    assert [p["offset"] for p in captured] == ["0", "25", "50"]
    assert all(p["all_fields"] == "true" for p in captured)


def test_get_organisations_empty_list_makes_no_page_calls():
    """No orgs → no rate-limited page requests at all."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json={"success": True, "result": []})

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        assert scripts.get_organisations.get_organisations(client) == []

    assert len(calls) == 1  # the names call only
    assert "all_fields" not in calls[0]


def test_error_paths():
    def http_error(request):
        return httpx.Response(500, text="boom")

    def bad_success(request):
        return httpx.Response(200, json={"success": False})

    # success:false on the names call
    with (
        pytest.raises(RuntimeError, match="Failed to fetch org names"),
        httpx.Client(
            transport=httpx.MockTransport(bad_success),
            follow_redirects=True,
        ) as client,
    ):
        scripts.get_organisations.get_organisations(client)

    # HTTP error on a page (names call succeeds first)
    def names_ok_page_error(request):
        if "all_fields" in request.url.params:
            return httpx.Response(500, text="boom")
        return httpx.Response(
            200,
            json={"success": True, "result": ["org-0", "org-1"]},
        )

    with (
        pytest.raises(RuntimeError, match="HTTP 500"),
        httpx.Client(
            transport=httpx.MockTransport(names_ok_page_error),
            follow_redirects=True,
        ) as client,
    ):
        scripts.get_organisations.get_organisations(client)

    # success:false on a page
    def names_ok_page_bad_success(request):
        if "all_fields" in request.url.params:
            return httpx.Response(200, json={"success": False})
        return httpx.Response(
            200,
            json={"success": True, "result": ["org-0", "org-1"]},
        )

    with (
        pytest.raises(RuntimeError, match="success: false"),
        httpx.Client(
            transport=httpx.MockTransport(names_ok_page_bad_success),
            follow_redirects=True,
        ) as client,
    ):
        scripts.get_organisations.get_organisations(client)


def test_write_json_roundtrip(tmp_path):
    orgs = [make_org(1), make_org(2)]
    path = tmp_path / "organisations.json"
    scripts.get_organisations.write_json(orgs, str(path))
    loaded = json.loads(path.read_text())
    assert loaded == orgs


def test_main_writes_file(tmp_path, monkeypatch):
    """End-to-end via main(): writes downloads/organisations.json."""
    orgs = [
        make_org(1),
        # display_name absent → falls back to name; package_count None → "?"
        {"id": "org-0002", "name": "org-2", "description": None},
    ]

    downloads_dir = tmp_path / "downloads"
    monkeypatch.setattr(scripts.get_organisations, "DOWNLOADS_DIR", downloads_dir)

    def handler(request: httpx.Request) -> httpx.Response:
        if "all_fields" in request.url.params:
            return httpx.Response(200, json={"success": True, "result": orgs})
        return httpx.Response(
            200,
            json={"success": True, "result": [o["name"] for o in orgs]},
        )

    real_client = scripts.get_organisations.httpx.Client

    def fake_client(**kw):
        return real_client(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        )

    monkeypatch.setattr(scripts.get_organisations.httpx, "Client", fake_client)

    scripts.get_organisations.main()  # must not raise

    out = downloads_dir / "organisations.json"
    assert out.exists()
    assert json.loads(out.read_text()) == orgs
