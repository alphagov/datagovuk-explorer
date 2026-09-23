"""Unit tests for scripts/get_harvest_sources.py (offline — no live API).

Covers the deterministic parts:
- load_organisation_ids: reads org IDs from organisations.json, error on missing
- get_harvest_sources: one call per org with organization_id filter,
  tags each source with the org it came from, dedupes by source id
- error paths: HTTP error, success:false
- write_json round-trip
- main(): end-to-end happy path writes harvest_sources.json

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
        transport=httpx.MockTransport(handler), follow_redirects=True,
    ) as client:
        sources = scripts.get_harvest_sources.get_harvest_sources(client, lambda: None, org_ids)

    assert requested == org_ids
    assert len(sources) == 2
    by_id = {s["id"]: s for s in sources}
    assert set(by_id) == {"src-0001", "src-0002"}
    assert by_id["src-0001"]["organization_id"] == "org-0002"
    assert by_id["src-0002"]["organization_id"] == "org-0002"
    assert by_id["src-0001"]["title"] == "Harvest Source 1"


def test_error_paths():
    def http_error(request):
        return httpx.Response(500, text="boom")

    def bad_success(request):
        return httpx.Response(200, json={"success": False})

    with (
        pytest.raises(RuntimeError, match="HTTP 500"),
        httpx.Client(
            transport=httpx.MockTransport(http_error), follow_redirects=True,
        ) as client,
    ):
        scripts.get_harvest_sources.get_harvest_sources(client, lambda: None, ["org-0001"])

    with (
        pytest.raises(RuntimeError, match="success: false"),
        httpx.Client(
            transport=httpx.MockTransport(bad_success), follow_redirects=True,
        ) as client,
    ):
        scripts.get_harvest_sources.get_harvest_sources(client, lambda: None, ["org-0001"])


def test_write_json_roundtrip(tmp_path):
    sources = [make_source(1, "org-0001"), make_source(2, "org-0002")]
    path = tmp_path / "harvest_sources.json"
    scripts.get_harvest_sources.write_json(sources, str(path))
    loaded = json.loads(path.read_text())
    assert loaded == sources


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
            transport=httpx.MockTransport(handler), follow_redirects=True,
        )

    monkeypatch.setattr(scripts.get_harvest_sources.httpx, "Client", fake_client)

    scripts.get_harvest_sources.main()

    out = downloads_dir / "harvest_sources.json"
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert len(loaded) == 1
    assert loaded[0]["organization_id"] == "org-0001"
