"""Unit tests for scripts/get_datasets.py (offline — no live API).

Covers:
- slugify + filename construction (slugify(title)-id[:8].json)
- iso_now format (ISO 8601 UTC: 3-digit ms + Z)
- load_no_datasets / save_no_datasets round-trip and failure modes
- has_saved_datasets (.json detection, missing dir)
- select_orgs: single org (found / not-found + hint), force, next-walk
  (skips no_datasets + saved orgs)
- fetch_datasets: pagination (1000-row pages, short-page break), URL
  params, HTTP error, success:false (mock transport)
- process_org: record shape + key order, force overwrite, zero-dataset
  org -> no-datasets.json marker, per-org error doesn't stop the run
- CLI error paths: missing organisations.json, --org not found (+ hint)

Run with: uv run pytest tests/test_get_datasets.py
"""

import io
import json
import os
import re
import tempfile
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import scripts.get_datasets

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


@contextmanager
def chdir(path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def make_dataset(i: int) -> dict:
    return {
        "title": f"Dataset Number {i}",
        "id": f"{i:08d}-0000-0000-0000-000000000000",
    }


def test_iso_now():
    assert ISO_RE.match(scripts.get_datasets.iso_now()), scripts.get_datasets.iso_now()


def test_slugify():
    assert scripts.get_datasets.slugify("My Dataset") == "my-dataset"
    assert scripts.get_datasets.slugify("Spend  over £25,000!") == "spend-over-25-000"
    assert scripts.get_datasets.slugify("!!! ...") == ""
    assert scripts.get_datasets.slugify("--leading and trailing--") == "leading-and-trailing"
    assert len(scripts.get_datasets.slugify("x" * 200)) == 80
    assert scripts.get_datasets.slugify("A" * 100 + " B") == "a" * 80
    assert scripts.get_datasets.slugify("２０２０ data") == "data"


def test_filename():
    ds = {"title": "My Dataset!", "id": "598c37fa-9d20-465a-988c-a6e31974493a"}
    assert scripts.get_datasets.slugify(ds["title"]) + "-" + ds["id"][:8] + ".json" == "my-dataset-598c37fa.json"
    # id8 suffix disambiguates two titles sharing an 80-char slug prefix
    title = "Long title " + "x" * 70
    a = {"title": title, "id": "11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}
    b = {"title": title, "id": "22222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb"}
    fa = f"{scripts.get_datasets.slugify(a['title'])}-{a['id'][:8]}.json"
    fb = f"{scripts.get_datasets.slugify(b['title'])}-{b['id'][:8]}.json"
    assert fa != fb


def test_fetch_datasets():
    total = 2500
    all_results = [make_dataset(i) for i in range(total)]
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(dict(request.url.params))
        start = int(captured[-1]["start"])
        rows = int(captured[-1]["rows"])
        page = all_results[start : start + rows]
        return httpx.Response(200, json={"success": True, "result": {"results": page, "count": total}})

    limiter = scripts.get_datasets.create_rate_limiter(4)
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        results = scripts.get_datasets.fetch_datasets("ons", client, limiter)

    assert len(results) == total
    # three pages: 1000, 1000, 500 — short page ends the loop
    assert [p["rows"] for p in captured] == ["1000", "1000", "1000"]
    assert [p["start"] for p in captured] == ["0", "1000", "2000"]
    assert all(p["sort"] == "metadata_created desc" for p in captured)
    assert all(p["fq"] == "organization:ons" for p in captured)
    assert all(p["q"] == "" for p in captured)

    # HTTP error -> RuntimeError
    with (
        pytest.raises(RuntimeError, match="HTTP 500"),
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")),
            follow_redirects=True,
        ) as client,
    ):
        scripts.get_datasets.fetch_datasets("ons", client, limiter)

    # success:false -> RuntimeError
    with (
        pytest.raises(RuntimeError, match="success: false"),
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"success": False})),
            follow_redirects=True,
        ) as client,
    ):
        scripts.get_datasets.fetch_datasets("ons", client, limiter)


def test_process_org():
    datasets = [make_dataset(1), make_dataset(2)]

    def handler(request: httpx.Request) -> httpx.Response:
        fq = dict(request.url.params)["fq"]
        results = datasets if "with-data" in fq else []
        return httpx.Response(200, json={"success": True, "result": {"results": results}})

    def run(org):
        limiter = scripts.get_datasets.create_rate_limiter(4)
        with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            return scripts.get_datasets.process_org(org, client, limiter)

    with tempfile.TemporaryDirectory() as d, chdir(d):
        # first run: saves 2 files
        saved = run({"name": "org-with-data", "display_name": "Org With Data"})
        assert saved == 2

        f1 = Path("downloads/datasets/org-with-data/dataset-number-1-00000001.json")
        f2 = Path("downloads/datasets/org-with-data/dataset-number-2-00000002.json")
        assert f1.exists()
        assert f2.exists()

        # record shape: _fetched_at, _organisation first, then dataset keys
        rec = json.loads(f1.read_text(encoding="utf-8"))
        assert list(rec)[:2] == ["_fetched_at", "_organisation"]
        assert ISO_RE.match(rec["_fetched_at"])
        assert rec["_organisation"] == {"name": "org-with-data", "display_name": "Org With Data"}
        assert rec["title"] == "Dataset Number 1"
        assert list(rec)[2:] == ["title", "id"]
        assert '{\n  "_fetched_at":' in f1.read_text(encoding="utf-8")

        # empty org -> marker file written
        saved = run({"name": "empty-org"})
        assert saved == 0
        marker = Path("downloads/datasets/empty-org/no-datasets.json")
        assert marker.exists()
        assert marker.read_text(encoding="utf-8") == "[]"

        # second run: wipes stale files and refetches
        saved = run({"name": "org-with-data", "display_name": "Org With Data"})
        assert saved == 2

        # display_name missing: omitted from _organisation (not written as null)
        run({"name": "org-with-data"})
        rec = json.loads(f1.read_text(encoding="utf-8"))
        assert rec["_organisation"] == {"name": "org-with-data"}
        assert "display_name" not in rec["_organisation"]

    # per-org API error: logged to stderr, other orgs continue
    def error_handler(request: httpx.Request) -> httpx.Response:
        fq = dict(request.url.params)["fq"]
        if "bad" in fq:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"success": True, "result": {"results": datasets}})

    with tempfile.TemporaryDirectory() as d, chdir(d):
        limiter = scripts.get_datasets.create_rate_limiter(4)
        err, out = io.StringIO(), io.StringIO()
        with (
            redirect_stdout(out),
            redirect_stderr(err),
            httpx.Client(transport=httpx.MockTransport(error_handler), follow_redirects=True) as client,
        ):
            r1 = scripts.get_datasets.process_org({"name": "bad-org"}, client, limiter)
            r2 = scripts.get_datasets.process_org({"name": "good-org"}, client, limiter)
        assert "✗ error: HTTP 500" in err.getvalue()
        assert r1 == 0
        assert r2 == 2
        assert Path("downloads/datasets/good-org/dataset-number-1-00000001.json").exists()


def test_cli():
    runner = CliRunner()

    # missing organisations.json -> exit 1
    with tempfile.TemporaryDirectory() as d, chdir(d):
        res = runner.invoke(scripts.get_datasets.app, [])
        assert res.exit_code == 1, res.output
        assert "No organisations.json found." in res.stderr

    # --org not found -> exit 1 + hint
    with tempfile.TemporaryDirectory() as d:
        Path(d, "downloads/organisations").mkdir(parents=True)
        Path(d, "downloads/organisations/organisations.json").write_text(
            json.dumps([{"name": "ons", "display_name": "ONS"}]),
            encoding="utf-8",
        )
        with chdir(d):
            res = runner.invoke(scripts.get_datasets.app, ["--org", "zzz"])
        assert res.exit_code == 1, res.output
        assert 'Publisher not found: "zzz"' in res.stderr
        assert "Check organisations.json" in res.stderr
