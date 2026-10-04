"""Unit tests for scripts/llm/review.py (offline — no live LLM, no DB).

Covers:
- build_prompt: system/user roles, no theme interpolation needed
- process_one: ok/failed record shapes + key order, score validation,
  429 backoff, progress output
- CLI error paths: --limit 0, missing env, remote --concurrency 0, local
  health-check down

Run with: uv run pytest tests/test_llm_review.py
"""

import io
import json
import os
import tempfile
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/test-db")

import httpx
from typer.testing import CliRunner

import scripts.llm.common as lc
import scripts.llm.review as rv
from tests.llm_helpers import PatchedSleep, chat_handler, fake_row, make_client, read_record


def review_reply(**overrides) -> httpx.Response:
    review = {
        "title-description": {"score": 4, "issues": []},
        "resources": {"score": 2, "issues": ["Few formats"]},
    }
    review.update(overrides)
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(review)}}]},
    )


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------
def test_build_prompt():
    digest = {"title": "X", "organisation": None}
    messages = rv.build_prompt(digest)
    assert len(messages) == 2
    assert messages[0] == {
        "role": "system",
        "content": rv.SYSTEM_CONTENT.format(today=datetime.now(tz=UTC).date().isoformat()),
    }
    assert messages[1]["role"] == "user"

    content = messages[1]["content"]
    digest_json = json.dumps(digest, indent=1, ensure_ascii=False)
    assert digest_json in content
    assert "title-description" in content
    assert "resources" in content
    # No theme interpolation in review prompt
    assert "${themeList}" not in content
    assert "${themeKeys}" not in content


# ---------------------------------------------------------------------------
# process_one
# ---------------------------------------------------------------------------
def test_process_one_ok_record():
    row = fake_row({"title": "T", "resources": [{"format": "CSV"}]})
    summary = {"ok": 0, "failed": 0}
    handler = chat_handler([review_reply()])

    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        with make_client(handler) as client:
            rv.process_one(
                lc.LLMConfig(client, "http://llm", "", "m1", out),
                row,
                0,
                1,
                show_progress=False,
                summary=summary,
            )
        rec = read_record(out)
        assert list(rec) == [
            "dataset_id",
            "title",
            "org_slug",
            "org_display_name",
            "model",
            "reviewed_at",
            "ok",
            "title-description",
            "resources",
            "input",
        ]
        assert rec["dataset_id"] == row["ckan_id"]
        assert rec["org_slug"] == "test-org"
        assert rec["org_display_name"] == "Test Org"
        assert rec["model"] == "m1"
        assert rec["ok"] is True
        assert rec["reviewed_at"].endswith("Z")
        assert summary == {"ok": 1, "failed": 0}
        assert len(handler.calls) == 1


def test_process_one_failed():
    cases = [
        (httpx.Response(500, text="boom"), "HTTP 500: boom"),
    ]
    for reply, err in cases:
        row = fake_row({"title": "T"})
        summary = {"ok": 0, "failed": 0}
        handler = chat_handler([reply, reply, reply])

        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            with make_client(handler) as client:
                rv.process_one(
                    lc.LLMConfig(client, "http://llm", "", "m", out),
                    row,
                    0,
                    1,
                    show_progress=False,
                    summary=summary,
                )
            rec = read_record(out)
        assert rec["ok"] is False
        assert rec["error"] == err
        assert summary == {"ok": 0, "failed": 1}
        assert len(handler.calls) == 3


def test_process_one_429_backoff():
    row = fake_row({"title": "T"})
    summary = {"ok": 0, "failed": 0}
    handler = chat_handler(
        [
            httpx.Response(429, text="slow down"),
            httpx.Response(429, text="slow down"),
            review_reply(),
        ],
    )

    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        with PatchedSleep() as ps, make_client(handler) as client:
            rv.process_one(
                lc.LLMConfig(client, "http://llm", "", "m", out),
                row,
                0,
                1,
                show_progress=False,
                summary=summary,
            )
        rec = read_record(out)
    assert rec["ok"] is True
    assert len(handler.calls) == 3
    assert ps.delays == [2000, 4000]


def test_process_one_progress():
    row = fake_row({"title": "Nice Title"}, title="Nice Title")
    summary = {"ok": 0, "failed": 0}
    handler = chat_handler([review_reply()])
    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        with make_client(handler) as client, redirect_stdout(buf):
            rv.process_one(
                lc.LLMConfig(client, "http://llm", "", "m", out),
                row,
                0,
                1,
                show_progress=True,
                summary=summary,
            )
    line = buf.getvalue().strip()
    assert line == "[1/1] scores td=4 res=2 | test-org/Nice Title"


# ---------------------------------------------------------------------------
# CLI error paths
# ---------------------------------------------------------------------------
def test_cli():
    runner = CliRunner()
    clear_env = {
        "LLM": "",
        "LLM_BASE_URL": "",
        "LLM_MODEL": "",
        "LOCAL_BASE_URL": "",
        "LOCAL_MODEL": "",
        "ANTHROPIC_AUTH_TOKEN": "",
        "ANTHROPIC_API_KEY": "",
    }

    res = runner.invoke(rv.app, ["--limit", "0"], env=clear_env)
    assert res.exit_code == 1, res.output
    assert "--limit must be >= 1" in res.stderr

    res = runner.invoke(rv.app, ["--limit", "1"], env=clear_env)
    assert res.exit_code == 1, res.output
    assert "LOCAL_MODEL and LOCAL_BASE_URL" in res.stderr

    res = runner.invoke(rv.app, ["--limit", "1"], env={**clear_env, "LLM": "k"})
    assert res.exit_code == 1, res.output
    assert "LLM_MODEL and LLM_BASE_URL" in res.stderr

    res = runner.invoke(
        rv.app,
        ["--concurrency", "0", "--limit", "1"],
        env={**clear_env, "LLM": "k", "LLM_BASE_URL": "http://x", "LLM_MODEL": "m"},
    )
    assert res.exit_code == 1, res.output
    assert "--concurrency must be >= 1" in res.stderr

    res = runner.invoke(
        rv.app,
        ["--limit", "1"],
        env={
            **clear_env,
            "LOCAL_BASE_URL": "http://127.0.0.1:59999",
            "LOCAL_MODEL": "m",
        },
    )
    assert res.exit_code == 1, res.output
    assert "Cannot reach the model server at http://127.0.0.1:59999" in res.stderr
    assert "Start the server configured by LOCAL_BASE_URL" in res.stderr
    assert "Error: 1" not in res.stderr
