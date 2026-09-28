"""Unit tests for scripts/llm/common.py (offline — no live LLM, no DB).

Covers the deterministic shared parts:
- constants: EXTRAS_WHITELIST
- truncate / strip_html / digest_resource / build_digest (whitelist
  filtering, truncation, resource digest + _note, org fallback chain, tags
  object-vs-string, key order)
- extract_json: fence stripping, first-{-to-last-} slicing, error paths
- load_processed_ids / write_record: ok vs attempted sets, corrupt-file
  skip, per-dataset JSON files
- send_request (mock transport): auth header + thinking only when an API
  key is present, request key order, HTTP-error truncation, empty content
- run_workers: concurrency cap honoured, each row processed exactly once

Run with: uv run pytest tests/test_llm_common.py
"""

import json
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/test-db")

import httpx
import pytest

import scripts.llm.common as lc


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------
def fake_row(
    pkg,
    id_="11111111-1111-1111-1111-111111111111",
    org="test-org",
    title="Test Dataset",
):
    return {
        "id": id_,
        "title": title,
        "org_slug": org,
        "org_display_name": "Test Org",
        "json": pkg,
    }


def _dummy_build_prompt(digest: dict) -> list[dict]:
    return [
        {"role": "system", "content": "test"},
        {"role": "user", "content": json.dumps(digest)},
    ]


def _ok_response(**overrides) -> httpx.Response:
    reply = {"result": "ok"}
    reply.update(overrides)
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(reply)}}]},
    )


def chat_handler(responses):
    calls = []
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        i = state["n"]
        state["n"] += 1
        fn = responses[i] if i < len(responses) else responses[-1]
        return fn(request) if callable(fn) else fn

    handler.calls = calls
    return handler


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
def test_constants():
    assert len(lc.EXTRAS_WHITELIST) > 0
    assert lc.EXTRAS_WHITELIST["frequency-of-update"] == "update_frequency"
    assert lc.EXTRAS_WHITELIST["update_frequency"] == "update_frequency"
    assert lc.EXTRAS_WHITELIST["licence"] == "licence_statement"
    assert lc.RETRIES == 2
    assert lc.REMOTE_CONCURRENCY == 50
    assert lc.MAX_TOKENS == 2048
    assert lc.TEMPERATURE == 0.2


# ---------------------------------------------------------------------------
# Pure string helpers
# ---------------------------------------------------------------------------
def test_truncate():
    assert lc.truncate(None, 5) is None
    assert lc.truncate("short", 10) == "short"
    assert lc.truncate("longer than ten", 5) == "longe…"
    assert lc.truncate("abc", 3) == "abc"
    assert lc.truncate(s=True, n=10) == "true"
    assert lc.truncate(s=False, n=10) == "false"
    assert lc.truncate(123, 10) == "123"


def test_strip_html():
    assert lc.strip_html("<p>Hello</p>") == "Hello"
    assert lc.strip_html("A &amp; B") == "A & B"
    assert lc.strip_html("A&nbsp;&nbsp;B") == "A B"
    assert lc.strip_html("line1\n\n  line2\tline3") == "line1 line2 line3"
    assert lc.strip_html("<b>x</b> &amp; <i>y</i>") == "x & y"
    assert lc.strip_html(None) == ""
    assert lc.strip_html("") == ""


def test_digest_resource():
    r = {
        "format": "CSV",
        "name": "Data",
        "description": "d",
        "url": "http://x",
        "size": 5,
        "created": "2020-01-02T03:04:05Z",
    }
    out = lc.digest_resource(r)
    assert list(out) == ["format", "name", "description", "url", "created"]
    assert out["format"] == "CSV"
    assert out["created"] == "2020-01-02"
    assert lc.digest_resource({"url": "u"}) == {"format": None, "url": "u"}
    assert lc.digest_resource({"format": ""}) == {"format": None}
    out = lc.digest_resource({"format": "x", "name": "n" * 300})
    assert out["name"] == "n" * 200 + "…"
    assert "size" not in out
    assert "created" not in out
    assert lc.digest_resource({"format": "x", "name": 0, "size": 0}) == {"format": "x"}


# ---------------------------------------------------------------------------
# build_digest
# ---------------------------------------------------------------------------
def test_build_digest_extras_and_resources():
    pkg = {
        "title": "T",
        "extras": [
            {"key": "frequency-of-update", "value": "monthly"},
            {"key": "unknown-key", "value": "ignored"},
            {"key": "publisher", "value": "x" * 2500},
        ],
        "resources": [{"format": "CSV", "name": f"r{i}"} for i in range(10)],
        "num_resources": 10,
    }
    d = lc.build_digest(pkg)
    assert d["extras"] == {
        "update_frequency": "monthly",
        "publisher": "x" * 2000 + "…",
    }
    assert len(d["resources"]) == 9
    assert d["resources"][-1] == {"_note": "…and 2 more resources"}
    assert d["resources"][0] == {"format": "CSV", "name": "r0"}

    pkg2 = {**pkg, "resources": [{"format": "CSV"} for _ in range(10)]}
    del pkg2["num_resources"]
    d2 = lc.build_digest(pkg2)
    assert d2["resources"][-1] == {"_note": "…and 2 more resources"}

    d3 = lc.build_digest(
        {"title": "T", "resources": [{"format": "CSV"} for _ in range(8)]},
    )
    assert len(d3["resources"]) == 8
    assert all("_note" not in r for r in d3["resources"])


def _small():
    return {"title": "T", "resources": []}


def test_build_digest_fields():
    pkg = {
        "title": "  My <b>Dataset</b>  ",
        "_organisation": {"name": "x", "display_name": "Org A"},
        "organization": {"title": "Org B"},
        "theme-primary": "environment",
        "license_title": "OGL",
        "isopen": False,
        "metadata_created": "2019-06-01T10:00:00Z",
        "metadata_modified": "2021-12-31T23:59:59Z",
        "notes": "Some <p>notes</p>   with&nbsp;spaces",
        "tags": ["a", {"name": "b"}, "c"],
        "resources": [],
    }
    d = lc.build_digest(pkg)
    assert d["title"] == "  My <b>Dataset</b>  "
    assert d["organisation"] == "Org A"
    assert d["theme"] == "environment"
    assert d["licence"] == "OGL"
    assert d["open_licence"] is False
    assert d["created"] == "2019-06-01"
    assert d["last_modified"] == "2021-12-31"
    assert d["description"] == "Some notes with spaces"
    assert d["tags"] == ["a", "b", "c"]

    d = lc.build_digest(
        {**_small(), "organization": {"title": "Org B"}, "_organisation": {"name": "x"}},
    )
    assert d["organisation"] == "Org B"
    d = lc.build_digest({**_small(), "organization": {"title": "Org B"}})
    assert d["organisation"] == "Org B"
    d = lc.build_digest(_small())
    assert d["organisation"] is None

    pkg2 = {**_small(), "tags": [f"t{i}" for i in range(12)]}
    assert len(lc.build_digest(pkg2)["tags"]) == 10

    assert list(d.keys()) == [
        "title",
        "organisation",
        "theme",
        "licence",
        "open_licence",
        "created",
        "last_modified",
        "description",
        "tags",
        "resources",
        "extras",
    ]


# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------
def test_extract_json():
    assert lc.extract_json('{"a": 1}') == {"a": 1}
    assert lc.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert lc.extract_json('```JSON\n{"a": 1}```') == {"a": 1}
    assert lc.extract_json('```\n{"a": 1}\n```') == {"a": 1}
    assert lc.extract_json(
        'Sure! Here you go: ```json\n{"a": 1}``` hope that helps',
    ) == {"a": 1}
    assert lc.extract_json('prefix {"a": 1, "b": {"c": 2}} suffix') == {
        "a": 1,
        "b": {"c": 2},
    }
    for bad in ("no json here", "```json\n```", ""):
        with pytest.raises(ValueError, match="no JSON object found in reply"):
            lc.extract_json(bad)
    with pytest.raises(json.JSONDecodeError):
        lc.extract_json('{"a": }')


# ---------------------------------------------------------------------------
# Per-dataset file store
# ---------------------------------------------------------------------------
def test_load_processed_ids():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        ok, attempted = lc.load_processed_ids(Path(d) / "nonexistent")
        assert ok == set()
        assert attempted == set()

        org = out / "test-org"
        org.mkdir()
        (org / "a-aaaaaaaa.json").write_text(
            '{"dataset_id":"a","ok":true}',
            encoding="utf-8",
        )
        (org / "b-bbbbbbbb.json").write_text(
            '{"dataset_id":"b","ok":false,"error":"boom"}',
            encoding="utf-8",
        )
        (org / "corrupt.json").write_text("not json", encoding="utf-8")
        (org / "c-cccccccc.json").write_text(
            '{"dataset_id":"c","ok":true}',
            encoding="utf-8",
        )
        ok, attempted = lc.load_processed_ids(out)
        assert ok == {"a", "c"}
        assert attempted == {"a", "b", "c"}


def test_write_record():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        lc.write_record(out, {"dataset_id": "aaaaaaaa-1111", "ok": True, "org_slug": "alpha", "title": "My Dataset"})
        lc.write_record(
            out,
            {"dataset_id": "bbbbbbbb-2222", "ok": False, "org_slug": "beta", "title": "Other", "note": "£—…"},
        )

        a = out / "alpha" / "my-dataset-aaaaaaaa.json"
        b = out / "beta" / "other-bbbbbbbb.json"
        assert a.exists()
        assert b.exists()
        rec_a = json.loads(a.read_text(encoding="utf-8"))
        assert rec_a["dataset_id"] == "aaaaaaaa-1111"
        assert rec_a["ok"] is True
        rec_b = json.loads(b.read_text(encoding="utf-8"))
        assert rec_b["note"] == "£—…"


# ---------------------------------------------------------------------------
# send_request
# ---------------------------------------------------------------------------
def test_send_request_remote():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return _ok_response()

    with make_client(handler) as client:
        content = lc.send_request(client, "http://llm", "secret", "m1", {"title": "T"}, _dummy_build_prompt)
    assert json.loads(content) == {"result": "ok"}

    assert captured["auth"] == "Bearer secret"
    body = captured["body"]
    assert list(body) == ["model", "messages", "thinking", "max_tokens", "temperature"]
    assert body["thinking"] == {"type": "disabled"}
    assert body["max_tokens"] == 2048
    assert body["temperature"] == 0.2
    assert len(body["messages"]) == 2


def test_send_request_local():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return _ok_response()

    with make_client(handler) as client:
        lc.send_request(client, "http://llm", "", "m1", {"title": "T"}, _dummy_build_prompt)
    assert captured["auth"] is None
    assert "thinking" not in captured["body"]
    assert list(captured["body"]) == ["model", "messages", "max_tokens", "temperature"]


def test_send_request_errors():
    handler = chat_handler([httpx.Response(429, text="rate limited " + "x" * 300)])
    with make_client(handler) as client:
        with pytest.raises(lc.LLMError, match="HTTP 429: ") as exc:
            lc.send_request(client, "http://llm", "", "m", {"title": "T"}, _dummy_build_prompt)
        assert exc.value.status == 429
        assert str(exc.value).startswith("HTTP 429: ")
        assert str(exc.value).endswith("…")

    handler = chat_handler(
        [httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})],
    )
    with make_client(handler) as client:
        with pytest.raises(lc.LLMError) as exc:
            lc.send_request(client, "http://llm", "", "m", {"title": "T"}, _dummy_build_prompt)
        assert str(exc.value) == "empty reply content (max_tokens may be too low)"

    handler = chat_handler(
        [
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": '  {"a":1}  '}}]},
            ),
        ],
    )
    with make_client(handler) as client:
        content = lc.send_request(client, "http://llm", "", "m", {"title": "T"}, _dummy_build_prompt)
    assert content == '{"a":1}'


# ---------------------------------------------------------------------------
# run_workers concurrency
# ---------------------------------------------------------------------------
def test_run_workers_concurrency():
    rows = [fake_row({"title": f"T{i}"}, id_=f"{i:08d}-0000-0000-0000-000000000000") for i in range(6)]
    state = {"active": 0, "max": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["active"] += 1
        state["max"] = max(state["max"], state["active"])
        time.sleep(0.05)
        state["active"] -= 1
        return _ok_response()

    summary = {"ok": 0, "failed": 0}
    processed = []

    def fake_process_one(  # noqa: PLR0913
        config, row, i, total, *, show_progress, summary, summary_lock=None,
    ):
        lc.send_request(
            config.client, config.base_url, config.api_key, config.model,
            {"title": "T"}, _dummy_build_prompt,
        )
        with (summary_lock if summary_lock else lc.nullcontext()):
            summary["ok"] += 1
            processed.append(row["id"])

    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        with make_client(handler) as client:
            lc.run_workers(
                lc.LLMConfig(client, "http://llm", "", "m", out),
                rows,
                3,
                show_progress=False,
                summary=summary,
                process_one=fake_process_one,
            )

    assert summary == {"ok": 6, "failed": 0}
    assert len(processed) == 6
    assert set(processed) == {r["id"] for r in rows}
    assert state["max"] == 3


def test_run_workers_caps_to_row_count():
    rows = [fake_row({"title": "T"}, id_=f"{i:08d}-0000-0000-0000-000000000000") for i in range(2)]
    state = {"active": 0, "max": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["active"] += 1
        state["max"] = max(state["max"], state["active"])
        time.sleep(0.01)
        state["active"] -= 1
        return _ok_response()

    summary = {"ok": 0, "failed": 0}

    def fake_process_one(  # noqa: PLR0913
        config, row, i, total, *, show_progress, summary, summary_lock=None,
    ):
        lc.send_request(
            config.client, config.base_url, config.api_key, config.model,
            {"title": "T"}, _dummy_build_prompt,
        )
        with (summary_lock if summary_lock else lc.nullcontext()):
            summary["ok"] += 1

    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        with make_client(handler) as client:
            lc.run_workers(
                lc.LLMConfig(client, "http://llm", "", "m", out),
                rows,
                50,
                show_progress=False,
                summary=summary,
                process_one=fake_process_one,
            )
    assert state["max"] == 2
