"""Shared helpers for the LLM script tests (test_review.py, test_suggest.py)."""

import json
from pathlib import Path

import httpx

import scripts.llm.common as lc


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


class PatchedSleep:
    def __init__(self):
        self.delays = []

    def __enter__(self):
        self._orig = lc.sleep

        def fake_sleep(ms):
            self.delays.append(ms)

        lc.sleep = fake_sleep
        return self

    def __exit__(self, *exc):
        lc.sleep = self._orig


def read_record(out_dir: Path) -> dict:
    files = list(out_dir.rglob("*.json"))
    assert len(files) == 1, f"expected 1 file, got {len(files)}: {files}"
    return json.loads(files[0].read_text(encoding="utf-8"))
