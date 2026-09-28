#!/usr/bin/env python3
"""One LLM call per dataset: quality scores (findability + resources).

Reads datasets from the quality index, sends a curated digest to the
model, and writes one JSON file per dataset to downloads/reviews/<org>/.
Each record has:

  scores   — title-description, resources (0-5 + issues)

Remote mode reads the API key from the LLM env var; local mode targets a
llama.cpp server using LOCAL_MODEL and LOCAL_BASE_URL from .env.

Usage:
  python scripts/review.py                       # 20 random datasets
  python scripts/review.py --limit 50
  python scripts/review.py --org environment-agency
  python scripts/review.py --dataset <id> --dataset <id2>
  python scripts/review.py --dataset <id> --include-reviewed

Env vars:
  LLM            API key for remote LLM
  LLM_MODEL      remote model id
  LLM_BASE_URL   remote API base URL
  LOCAL_MODEL    local model id
  LOCAL_BASE_URL local API base URL

This script opens its own DB connection via connect() from scripts/db, the
same pattern as the other pipeline scripts — it never touches Django.
"""

import json
import shutil
import sys
import threading
from pathlib import Path
from typing import Annotated

import httpx
import typer

from scripts.llm_common import (
    LLMConfig,
    ReviewError,
    build_digest,
    cli_resolve_config,
    fetch_record,
    iso_now,
    record_base,
    record_summary,
    run,
    write_record,
)

app = typer.Typer(add_completion=False)

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "downloads" / "reviews"


# ---------------------------------------------------------------------------
# Review prompt — quality scores only
# ---------------------------------------------------------------------------
SYSTEM_CONTENT = """You are a data-quality reviewer for data.gov.uk,
        the UK open data portal. You evaluate dataset metadata against open-data
        best practice.

        Be specific and evidence-based — every score must reference the
        metadata provided. Be critical but fair: a
        small public-sector dataset published as a monthly CSV can be high quality.
        Flag unexplained jargon or technical language that a non-specialist could
        not understand.

        Descriptions and resource URLs are sent in full. If a dataset has more than
        8 resources, only the first 8 are shown; very long extra values may be
        trimmed. Never criticise these digest limits — judge only what is present.

        Never invent facts."""

RUBRIC = """## Quality review

Every dimension starts at score 5. Deduct points only for specific, named
problems — every deduction must cite the concrete issue that caused it.
Return issues as an array of concise strings, one issue per item.
If there are no issues, set issues to an empty array [].

**title-description**

Review the title and description only.

The title is the most important signal. It should tell a reader what the
dataset contains. Reference codes and identifiers are fine — they help
specialists find the right record. What hurts is a title that is vague,
meaningless or actively misleading. Dates in the title are good if they
don't conflict with other metadata.

The description should expand on the title with enough context to decide
whether the dataset is relevant. Penalise unexpanded acronyms (e.g.
"MBES" without saying "multibeam echo sounder"). Overuse of jargon is bad
But do not flag proper nouns, equipment names or place names as jargon —
domain-specific named things are expected in specialist datasets.

**resources**

Data files in sensible formats (CSV/GeoJSON/XLSX etc.).
HTML alone can be ok in context (eg it represents API documentation).
Resources should have clear names and a declared format. A resource
with no name, no format or no description is poorly catalogued — the
more of these are missing, the lower the score.
Do not penalise National Archives links.
You cannot access URLs so never comment on whether they work or download."""

SCHEMA = """
Respond with ONE JSON object, no markdown fences, no commentary. Schema:

{
  "scores": {
    "title-description": { "score": <int 0-5>, "issues": ["<concise issue>", ...] },
    "resources":   { "score": <int 0-5>, "issues": ["<concise issue>", ...] }
  }
}"""


def build_prompt(digest: dict) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_CONTENT},
        {
            "role": "user",
            "content": (
                "Evaluate the following dataset metadata.\n"
                f"{RUBRIC}\n\n"
                "Dataset metadata (JSON):\n"
                f"{json.dumps(digest, indent=1, ensure_ascii=False)}\n"
                f"{SCHEMA}\n\n"
                "Now return the review JSON."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Validation + per-dataset processing
# ---------------------------------------------------------------------------
def _validate(parsed: dict) -> None:
    scores = parsed.get("scores")
    if not isinstance(scores, dict):
        raise ReviewError("scores must be an object")


def process_one(
    config: LLMConfig,
    row,
    i: int,
    total: int,
    *,
    show_progress: bool,
    summary: dict,
    summary_lock: threading.Lock | None = None,
) -> None:
    digest = build_digest(row["json"])
    if config.show_prompt:
        messages = build_prompt(digest)
        print("\n" + "=" * 72)
        for msg in messages:
            print(f"--- {msg['role']} ---")
            print(msg["content"])
        print("=" * 72 + "\n")
    base = {**record_base(row, config.model), "reviewed_at": iso_now()}

    record = fetch_record(config, base, digest, build_prompt, _validate)
    record["input"] = digest
    write_record(config.out_dir, record)
    record_summary(record, summary, summary_lock)

    if show_progress:
        if record["ok"]:
            scores = record.get("scores", {})
            td = scores.get("title-description", {}).get("score", "?")
            res = scores.get("resources", {}).get("score", "?")
            print(f"[{i + 1}/{total}] scores td={td} res={res} | {row['org_slug']}/{row['title']}")
        else:
            print(
                f"[{i + 1}/{total}] FAILED: {record['error']} | {row['org_slug']}/{row['title']}",
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
@app.command()
def main(
    *,
    limit: int | None = typer.Option(
        None,
        "--limit",
        help="datasets to process (default 20; all attempted with --include-reviewed)",
    ),
    org: str | None = typer.Option(
        None,
        "--org",
        help="only process datasets from this organisation",
    ),
    dataset: list[str] = typer.Option(
        [],
        "--dataset",
        help="dataset id(s) to process (repeat for multiple)",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="model id (default: LLM_MODEL env for remote, LOCAL_MODEL for local)",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="API base URL (default: LLM_BASE_URL env for remote, LOCAL_BASE_URL for local)",
    ),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        help="API key (default: LLM env var)",
    ),
    concurrency: int | None = typer.Option(
        None,
        "--concurrency",
        help="parallel requests (default 50 for remote APIs, 1 for local llama)",
    ),
    out_dir: Annotated[Path, typer.Option("--out-dir", help="output directory")] = DEFAULT_OUT_DIR,
    include_reviewed: bool = typer.Option(
        False,  # noqa: FBT003 — typer.Option's default is the first positional
        "--include-reviewed",
        help="re-process every dataset already in the output file",
    ),
    progress: bool = typer.Option(
        False,  # noqa: FBT003 — typer.Option's default is the first positional
        "--progress",
        help="show per-dataset progress output (auto-enabled with --dataset)",
    ),
    show_prompt: bool = typer.Option(
        False,  # noqa: FBT003 — typer.Option's default is the first positional
        "--show-prompt",
        help="print the full prompt sent to the model",
    ),
    clean: bool = typer.Option(
        False,  # noqa: FBT003 — typer.Option's default is the first positional
        "--clean",
        help="delete existing reviews before starting",
    ),
) -> None:
    """Review — one LLM call per dataset (quality scores)."""

    if limit is not None and limit < 1:
        print("--limit must be >= 1", file=sys.stderr)
        raise typer.Exit(1)

    key, base, mdl, conc = cli_resolve_config(
        api_key=api_key,
        base_url=base_url,
        model=model,
        concurrency=concurrency,
    )

    if clean and out_dir.exists():
        shutil.rmtree(out_dir)
        print(f"Cleaned {out_dir}")

    try:
        run(
            limit=limit,
            org=org,
            dataset=dataset,
            model=mdl,
            base_url=base,
            api_key=key,
            concurrency=conc,
            out_dir=out_dir,
            include_reviewed=include_reviewed,
            show_progress=progress or bool(dataset),
            show_prompt=show_prompt,
            process_one=process_one,
        )
    except typer.Exit:
        raise
    except (httpx.HTTPError, RuntimeError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
