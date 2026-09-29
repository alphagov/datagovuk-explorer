#!/usr/bin/env python3
"""One LLM call per dataset: theme, tag, title and description suggestions.

Reads datasets from the quality index, sends a curated digest to the
model, and writes one JSON file per dataset to downloads/suggestions/<org>/.
Each record has:

  theme    — suggested primary theme from the 14-theme vocabulary
  tags     — 3-8 suggested subject-matter tags
  title    — suggested title (or empty if current is good)
  desc     — suggested description (or empty if current is good)

Remote mode reads the API key from the LLM env var; local mode targets a
llama.cpp server using LOCAL_MODEL and LOCAL_BASE_URL from .env.

Usage:
  python -m scripts.llm.suggest                       # 20 random datasets
  python -m scripts.llm.suggest --limit 50
  python -m scripts.llm.suggest --org environment-agency
  python -m scripts.llm.suggest --dataset <id> --dataset <id2>
  python -m scripts.llm.suggest --dataset <id> --include-reviewed

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

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "downloads" / "suggestions"


# ---------------------------------------------------------------------------
# Suggest digest — title, description, theme, tags only
# ---------------------------------------------------------------------------
def build_digest(pkg: dict) -> dict:
    return {
        "title": pkg.get("title"),
        "organisation": (
            (pkg.get("_organisation") or {}).get("display_name") or (pkg.get("organization") or {}).get("title") or None
        ),
        "description": truncate(strip_html(pkg.get("notes")), 20000),
        "theme": pkg.get("theme-primary") or None,
        "tags": [t if isinstance(t, str) else t.get("name") for t in (pkg.get("tags") or [])][:10],
    }


THEMES: dict[str, list[str]] = json.loads(
    (Path(__file__).resolve().parent / "themes.json").read_text(),
)


# ---------------------------------------------------------------------------
# Suggestion prompt — theme/tag/title/description only
# ---------------------------------------------------------------------------
SYSTEM_CONTENT = """
context, today's date is {today}.

You are a metadata specialist for data.gov.uk,
the UK open data portal. You classify datasets by theme and suggest
improved metadata.

Be specific and evidence-based — every suggestion must reference the
metadata provided.

Never invent facts. The suggested description must only rephrase what is
present in the metadata — no added topics, audiences, purpose, numbers,
dates, geographies or sources."""

RUBRIC = """## Suggestions

**suggested_title**

A clear improved title, or empty string if the current title is good.
Reference codes and identifiers are fine in addition to
a clear title — they help specialists. A poor title
is vague, meaningless, misleading, pure jargon.
Dates in the title are good if they don't conflict with other metadata.
Do not add publisher names to title - they will be visible on the page.

Example good titles:
 - Ancient Woodland (England)
 - Speed Camera Locations in Greater Manchester
 - Derbyshire Local Nature Recovery Strategy (LNRS)

Example poor titles:
 - GM Accessibility Levels (GMAL)
 - MiniScale
 - AIMS Asset Bundle

If there is not enough metadata to go on, set suggested_title to blank string "".

**suggested_description**

The description should expand on the title with enough context to decide
whether the dataset is relevant. Acronyms are fine unless too many unexplained ones -
something like Linear Regression Rate (LRR) is fine.
Overuse of jargon is bad but proper nouns, equipment
names or place names are valid — domain-specific named things are
expected in specialist datasets. Stick strictly to facts from the title and description.
Two relevant lines or less is too short, 10 paragraphs is too long.

If there is not enough metadata to go on, set suggested_description to blank string "".

**suggested_theme**

Pick the single best primary theme from:
${themeList}
If the dataset genuinely spans multiple themes or none clearly
fit, pick the closest one and set theme_confidence low. Never
make up a theme outside the list.
If there is not enough metadata to go on, set it to blank string "".

**theme_confidence**

"high" | "low" — how confident you are in the theme assignment

**suggested_tags**

3-6 relevant tags
- Describe what the dataset is actually about.
- Example tags are listed under each theme. If any are relevant, use
  them (exact spelling). Tags from any theme are fine, not just the
  chosen one.
- Do not feel constrained by the examples — use whatever tags best
  describe this specific dataset.
- Describe what the data is ABOUT, not how it's delivered.
- NEVER include the publishing organisation's name or acronym.
- NEVER include dates or years (no "2017-18", "2019", "December 2020", etc.)
- NEVER include format or file-type terms (no "CSV", "shapefile", "WMS", etc.).
- NEVER include data-structure terms (no "table", "dataset").
- NEVER include geographic or place names (no "England", "London", "Scotland", etc.)
- Lowercase, space-separated phrases (no hyphens).
- Prefer plural forms (e.g. "rivers" not "river").
- Each tag should add something distinct — avoid near-synonyms.

If there is not enough metadata to go on, set it to empty array []."""

SCHEMA = """
Respond with ONE JSON object, no markdown, no commentary. Schema:

{
  "suggested_title": "<improved title or empty string>",
  "suggested_description": "<improved description or empty string>",
  "suggested_theme": "<exactly one of [${themeKeys}]> or empty string",
  "suggested_theme_confidence": "<high | low>",
  "suggested_tags": ["<tag1>", "<tag2>", "..."]
}"""


def build_prompt(digest: dict) -> list[dict]:
    from datetime import date

    theme_list = "\n".join(f'- "{t}" — example tags: {", ".join(tags)}' for t, tags in THEMES.items())
    theme_keys = ", ".join(f'"{t}"' for t in THEMES)
    rubric = RUBRIC.replace("${themeList}", theme_list)
    schema = SCHEMA.replace("${themeKeys}", theme_keys)

    return [
        {"role": "system", "content": SYSTEM_CONTENT.format(today=date.today().isoformat())},
        {
            "role": "user",
            "content": (
                f"{rubric}\n\n"
                "Dataset metadata (JSON):\n"
                f"{json.dumps(digest, indent=1, ensure_ascii=False)}\n"
                f"{schema}\n\n"
                "Now return the suggestion JSON."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Validation + per-dataset processing
# ---------------------------------------------------------------------------
def _validate(parsed: dict) -> None:
    if parsed.get("suggested_theme") and parsed["suggested_theme"] not in THEMES:
        raise LLMError(
            f'invalid theme "{parsed["suggested_theme"]}" — not in vocabulary',
        )
    if not isinstance(parsed.get("suggested_tags"), list):
        raise LLMError("suggested_tags must be an array")


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
    base = {**record_base(row, config.model), "classified_at": iso_now()}

    record = fetch_record(config, base, digest, build_prompt, _validate)
    record["input"] = digest
    write_record(config.out_dir, record)
    record_summary(record, summary, summary_lock)

    if show_progress:
        if record["ok"]:
            theme = record.get("suggested_theme")
            conf = record.get("suggested_theme_confidence") or "?"
            print(f"[{i + 1}/{total}] theme {theme} ({conf}) | {row['org_slug']}/{row['title']}")
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
        help="delete existing suggestions before starting",
    ),
) -> None:
    """Suggest — one LLM call per dataset (theme/tags/title/description)."""

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
