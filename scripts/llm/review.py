#!/usr/bin/env python3
"""One LLM call per dataset: quality scores (findability + resources).

Reads datasets from the quality index, sends a curated digest to the
model, and writes one JSON file per dataset to downloads/reviews/<org>/.
Each record has:

  title-description, resources — score (0-5) + issues

Remote mode reads the API key from the LLM env var; local mode targets a
llama.cpp server using LOCAL_MODEL and LOCAL_BASE_URL from .env.

Usage:
  python -m scripts.llm.review                       # 20 random datasets
  python -m scripts.llm.review --limit 50
  python -m scripts.llm.review --org environment-agency
  python -m scripts.llm.review --dataset <id> --dataset <id2>
  python -m scripts.llm.review --dataset <id> --include-reviewed

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer

from scripts.llm.common import (
    LLMConfig,
    LLMError,
    cli_resolve_config,
    fetch_record,
    iso_now,
    record_base,
    record_summary,
    run,
    strip_html,
    truncate,
    write_record,
)

app = typer.Typer(add_completion=False)

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "downloads" / "reviews"
MAX_RESOURCES = 8


# ---------------------------------------------------------------------------
# Review digest — title, description, resources only
# ---------------------------------------------------------------------------
def _digest_resource(r: dict) -> dict:
    out = {"format": r.get("format") or None}
    name = (r.get("name") or "").strip()
    desc = (r.get("description") or "").strip()
    label = name or desc
    if label:
        out["name"] = truncate(label, 1000)
    if r.get("url"):
        out["url"] = r["url"]
    if r.get("created"):
        out["created"] = str(r["created"])[:10]
    return out


def build_digest(pkg: dict) -> dict:
    resources = [_digest_resource(r) for r in (pkg.get("resources") or [])[:MAX_RESOURCES]]
    total = pkg.get("num_resources") or len(pkg.get("resources") or [])
    if total > MAX_RESOURCES:
        resources.append({"_note": f"…and {total - MAX_RESOURCES} more resources"})

    return {
        "title": pkg.get("title"),
        "organisation": (
            (pkg.get("_organisation") or {}).get("display_name") or (pkg.get("organization") or {}).get("title") or None
        ),
        "description": truncate(strip_html(pkg.get("notes")), 20000),
        "resources": resources,
    }


# ---------------------------------------------------------------------------
# Review prompt — quality scores only
# ---------------------------------------------------------------------------
SYSTEM_CONTENT = """
For context, today's date is {today}.

You are a data-quality reviewer for data.gov.uk,
the UK open data portal. You evaluate dataset metadata against open-data
best practice.

Be specific and evidence-based — every score must reference the
metadata provided. Be critical but fair: a small public-sector dataset
published as a monthly CSV can be high quality.

Do not make suggestions for fixes, your role is only to review.

Descriptions and resource URLs are sent in full. If a dataset has more than
8 resources, only the first 8 are shown; very long extra values may be
trimmed. Never criticise these digest limits — judge only what is present.

"""

RUBRIC = """
## Scores and issues

Start scores at 5. Deduct points only for specific, named
issues — every deduction must cite the concrete issue that caused it.
A serious issue can deduct more than one point depending on severity.
Issues should be very short and clear, easy to scan - no need for full sentences
Add no issues if there aren't any, 1 - 4 issues if there are, prefer fewer.
Issues should be clearly distinct and ordered by priority.

**title-description**

Review the title and description only.

The title is the most important signal. It should tell a reader what the
dataset contains. Reference codes and identifiers are fine in addition to
a clear title — they help specialists. A poor title
is vague, meaningless, misleading, pure jargon and can pull down the score a lot
regardless of description. Dates in the title are
good if they don't conflict with other metadata.

Example good titles:
 - Ancient Woodland (England)
 - Speed Camera Locations in Greater Manchester
 - Derbyshire Local Nature Recovery Strategy (LNRS)

Example poor titles:
 - GM Accessibility Levels (GMAL)
 - MiniScale
 - AIMS Asset Bundle

The description should expand on the title with enough context to decide
whether the dataset is relevant. Acronyms are fine unless too many unexplained ones -
something like Linear Regression Rate (LRR) is fine.
Overuse of jargon is bad but do not flag proper nouns, equipment
names or place names as jargon — domain-specific named things are
expected in specialist datasets. Two relevant lines or less is too short, 10
paragraphs is too long.

**resources**

Data in sensible formats - downloads (CSV/GeoJSON/XLSX etc.)
or APIs (WMS, WFS, REST, etc.) it doesn't have to be both -
download only or API only is fine.
Accompanying documentation links are fine.
HTML alone can be ok only with good reason (eg it represents API documentation).
Resources should have clear names in the context of the dataset title and description,
and a declared format that makes sense.
Do not penalise National Archives links.
You cannot access URLs so never comment on whether they work or download."""

SCHEMA = """
Respond with ONE JSON object, no markdown fences, no commentary. Schema:

{
  "title-description": {
    "score": <int 0-5>,
    "issues": ["<concise issue>", ...]
  },
  "resources": {
    "score": <int 0-5>,
    "issues": ["<concise issue>", ...]
  }
}"""


def build_prompt(digest: dict) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_CONTENT.format(today=datetime.now(tz=UTC).date().isoformat())},
        {
            "role": "user",
            "content": (
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
    for key in ("title-description", "resources"):
        if not isinstance(parsed.get(key), dict):
            raise LLMError(f"{key} must be an object")


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
            td = record.get("title-description", {}).get("score", "?")
            res = record.get("resources", {}).get("score", "?")
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
