"""Unit tests for scripts/get_harvest_sources.py (offline — no live API).

Covers the deterministic parts:
- load_organisation_ids: reads org IDs from organisations.json, error on missing
- load_cached: wrapper format + missing file
- select_org_ids: new (not checked) + active selection, --full, DB fallback
- active_org_slugs: no DATABASE_URL -> None (walk every org)
- merge_sources: checked orgs replaced, unchecked carried forward
- get_harvest_sources: one call per org with organization_id filter,
  tags each source with the org it came from, dedupes by source id
- error paths: HTTP error, success:false
- write_json round-trip
- main(): end-to-end happy path writes the cache; carry-forward across runs

Run with: uv run python -m pytest tests/test_get_harvest_sources.py
"""

import json

import httpx
import pytest

import scripts.get_harvest_sources


def make_source(i: int, org_id: str) -> dict:
    return {
        "id": f"src-{i:04d}",
        "title": f"Harvest Source {i}",
        "url": f"https://example.com/{i}.xml",
        "type": "gemini-single",
        "active": True,
        "publisher_id": "",
        "organization_id": org_id,
    }


def test_load_organisation_ids(tmp_path, monkeypatch):
    orgs = [{"id": "org-0001", "name": "Alpha"}, {"id": "org-0002", "name": "Beta"}]
    dl = tmp_path / "downloads"
    dl.mkdir()
    (dl / "organisations.json").write_text(json.dumps(orgs))
    monkeypatch.setattr(scripts.get_harvest_sources, "DOWNLOADS_DIR", dl)
    assert scripts.get_harvest_sources.load_organisation_ids() == ["org-0001", "org-0002"]


def test_load_organisation_ids_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(scripts.get_harvest_sources, "DOWNLOADS_DIR", tmp_path / "nope")
    with pytest.raises(RuntimeError, match="not found"):
        scripts.get_harvest_sources.load_organisation_ids()


def test_get_harvest_sources_tags_and_dedupes():
    org_ids = ["org-0001", "org-0002", "org-0003"]
    per_org = {
        "org-0001": [make_source(1, "org-0001")],
        "org-0002": [make_source(1, "org-0002"), make_source(2, "org-0002")],
        "org-0003": [],
    }
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        org_id = request.url.params["organization_id"]
        requested.append(org_id)
        return httpx.Response(200, json={"success": True, "result": per_org[org_id]})

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        sources = scripts.get_harvest_sources.get_harvest_sources(client, lambda: None, org_ids)

    assert requested == org_ids
    assert len(sources) == 2
    by_id = {s["id"]: s for s in sources}
    assert set(by_id) == {"src-0001", "src-0002"}
    assert by_id["src-0001"]["organization_id"] == "org-0002"
    assert by_id["src-0002"]["organization_id"] == "org-0002"
    assert by_id["src-0001"]["title"] == "Harvest Source 1"


def test_error_paths(monkeypatch):
    # Retryable failures sleep between attempts — don't slow the test down.
    monkeypatch.setattr(scripts.get_harvest_sources.time, "sleep", lambda _: None)

    def http_error(request):
        return httpx.Response(500, text="boom")

    def bad_success(request):
        return httpx.Response(200, json={"success": False})

    # 500 is retryable, so it is retried MAX_ATTEMPTS times and then gives up
    # with an HTTPError rather than the immediate RuntimeError used for a
    # non-retryable status.
    attempts = []

    def counting_http_error(request):
        attempts.append(request.url.params["organization_id"])
        return http_error(request)

    with (
        pytest.raises(httpx.HTTPError, match="HTTP 500"),
        httpx.Client(
            transport=httpx.MockTransport(counting_http_error),
            follow_redirects=True,
        ) as client,
    ):
        scripts.get_harvest_sources.get_harvest_sources(client, lambda: None, ["org-0001"])

    assert len(attempts) == scripts.get_harvest_sources.MAX_ATTEMPTS

    with (
        pytest.raises(RuntimeError, match="success: false"),
        httpx.Client(
            transport=httpx.MockTransport(bad_success),
            follow_redirects=True,
        ) as client,
    ):
        scripts.get_harvest_sources.get_harvest_sources(client, lambda: None, ["org-0001"])


def test_retries_transient_errors_then_succeeds(monkeypatch):
    monkeypatch.setattr(scripts.get_harvest_sources.time, "sleep", lambda _: None)
    attempts = []

    def flaky(request):
        attempts.append(request.url.params["organization_id"])
        if len(attempts) < scripts.get_harvest_sources.MAX_ATTEMPTS:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(
            200,
            json={"success": True, "result": [make_source(1, "org-0001")]},
        )

    with httpx.Client(
        transport=httpx.MockTransport(flaky),
        follow_redirects=True,
    ) as client:
        sources = scripts.get_harvest_sources.get_harvest_sources(client, lambda: None, ["org-0001"])

    assert len(attempts) == scripts.get_harvest_sources.MAX_ATTEMPTS
    assert [s["id"] for s in sources] == ["src-0001"]


def test_non_retryable_status_fails_immediately():
    attempts = []

    def not_found(request):
        attempts.append(request.url.params["organization_id"])
        return httpx.Response(404, text="nope")

    with (
        pytest.raises(RuntimeError, match="HTTP 404"),
        httpx.Client(
            transport=httpx.MockTransport(not_found),
            follow_redirects=True,
        ) as client,
    ):
        scripts.get_harvest_sources.get_harvest_sources(client, lambda: None, ["org-0001"])

    assert len(attempts) == 1


def test_write_json_roundtrip(tmp_path):
    sources = [make_source(1, "org-0001"), make_source(2, "org-0002")]
    path = tmp_path / "harvest_sources.json"
    scripts.get_harvest_sources.write_json(sources, str(path))
    loaded = json.loads(path.read_text())
    assert loaded == sources


def _orgs() -> list[dict]:
    return [
        {"id": "org-0001", "name": "alpha"},
        {"id": "org-0002", "name": "beta"},
        {"id": "org-0003", "name": "gamma"},
        {"id": "org-0004", "name": "delta"},
    ]


def test_load_cached_new_format(tmp_path, monkeypatch):
    dl = tmp_path / "downloads"
    dl.mkdir()
    payload = {
        "orgs": {
            "org-0001": [{"id": "s1", "organization_id": "org-0001"}],
            "org-0002": [],
        },
    }
    (dl / "harvest_sources.json").write_text(json.dumps(payload))
    monkeypatch.setattr(scripts.get_harvest_sources, "DOWNLOADS_DIR", dl)
    assert scripts.get_harvest_sources.load_cached() == payload["orgs"]


def test_load_cached_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(scripts.get_harvest_sources, "DOWNLOADS_DIR", tmp_path / "nope")
    assert scripts.get_harvest_sources.load_cached() == {}


def test_select_org_ids_picks_new_and_active(monkeypatch):
    checked = {"org-0001", "org-0002", "org-0003"}
    monkeypatch.setattr(scripts.get_harvest_sources, "active_org_slugs", lambda days: {"beta"})
    # org-0001/0003 known + dormant -> skip; org-0002 known + active; org-0004 new.
    assert scripts.get_harvest_sources.select_org_ids(
        _orgs(),
        checked,
        active_days=30,
    ) == ["org-0002", "org-0004"]


def test_select_org_ids_full_returns_every_org(monkeypatch):
    def boom(*_a, **_kw):
        raise AssertionError("full must not consult the DB")

    monkeypatch.setattr(scripts.get_harvest_sources, "active_org_slugs", boom)
    assert scripts.get_harvest_sources.select_org_ids(
        _orgs(),
        set(),
        active_days=30,
        full=True,
    ) == ["org-0001", "org-0002", "org-0003", "org-0004"]


def test_select_org_ids_falls_back_to_every_org(monkeypatch):
    monkeypatch.setattr(scripts.get_harvest_sources, "active_org_slugs", lambda days: None)
    assert scripts.get_harvest_sources.select_org_ids(
        _orgs(),
        {"org-0001"},
        active_days=30,
    ) == ["org-0001", "org-0002", "org-0003", "org-0004"]


def test_active_org_slugs_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert scripts.get_harvest_sources.active_org_slugs(30) is None


def test_merge_sources_replaces_checked_orgs_and_carries_the_rest():
    cached = {
        "org-0001": [make_source(1, "org-0001")],  # checked, still present
        "org-0002": [make_source(2, "org-0002")],  # unchecked -> carried
        "org-0003": [make_source(3, "org-0003")],  # checked, deleted upstream
        "org-9999": [make_source(9, "org-9999")],  # org gone from orgs.json
    }
    fetched = [make_source(1, "org-0001")]
    merged = scripts.get_harvest_sources.merge_sources(
        cached,
        fetched,
        {"org-0001", "org-0003"},
        {"org-0001", "org-0002", "org-0003"},
    )
    assert set(merged) == {"org-0001", "org-0002", "org-0003"}
    assert [s["id"] for s in merged["org-0001"]] == ["src-0001"]
    assert [s["id"] for s in merged["org-0002"]] == ["src-0002"]
    assert merged["org-0003"] == []


def test_main_writes_file(tmp_path, monkeypatch):
    orgs = [{"id": "org-0001", "name": "Alpha"}, {"id": "org-0002", "name": "Beta"}]
    sources = [make_source(1, "org-0001")]

    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    (downloads_dir / "organisations.json").write_text(json.dumps(orgs))
    monkeypatch.setattr(scripts.get_harvest_sources, "DOWNLOADS_DIR", downloads_dir)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("organization_id") == "org-0001":
            return httpx.Response(200, json={"success": True, "result": sources})
        return httpx.Response(200, json={"success": True, "result": []})

    real_client = scripts.get_harvest_sources.httpx.Client

    def fake_client(**kw):
        return real_client(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        )

    monkeypatch.setattr(scripts.get_harvest_sources.httpx, "Client", fake_client)

    scripts.get_harvest_sources.main(full=True)

    out = downloads_dir / "harvest_sources.json"
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert set(loaded["orgs"]) == {"org-0001", "org-0002"}
    assert [s["organization_id"] for s in loaded["orgs"]["org-0001"]] == ["org-0001"]
    assert loaded["orgs"]["org-0002"] == []


def test_main_carries_unchecked_orgs_forward(tmp_path, monkeypatch):
    orgs = [{"id": "org-0001", "name": "Alpha"}, {"id": "org-0002", "name": "Beta"}]
    cached = {
        "orgs": {
            "org-0001": [],
            "org-0002": [make_source(2, "org-0002")],
        },
    }
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    (downloads_dir / "organisations.json").write_text(json.dumps(orgs))
    (downloads_dir / "harvest_sources.json").write_text(json.dumps(cached))
    monkeypatch.setattr(scripts.get_harvest_sources, "DOWNLOADS_DIR", downloads_dir)
    # Only org-0001 is selected this run; org-0002's cached source rides along.
    monkeypatch.setattr(scripts.get_harvest_sources, "select_org_ids", lambda *a, **k: ["org-0001"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "result": [make_source(1, "org-0001")]})

    real_client = scripts.get_harvest_sources.httpx.Client

    def fake_client(**kw):
        return real_client(transport=httpx.MockTransport(handler), follow_redirects=True)

    monkeypatch.setattr(scripts.get_harvest_sources.httpx, "Client", fake_client)

    scripts.get_harvest_sources.main()

    loaded = json.loads((downloads_dir / "harvest_sources.json").read_text())
    assert set(loaded["orgs"]) == {"org-0001", "org-0002"}
    assert [s["id"] for s in loaded["orgs"]["org-0001"]] == ["src-0001"]
    assert [s["id"] for s in loaded["orgs"]["org-0002"]] == ["src-0002"]
