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

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "downloads" / "suggestions"


# ---------------------------------------------------------------------------
# Canonical theme vocabulary — each theme maps to example tags that double as
# the preferred tag vocabulary.  The LLM picks tags from these lists (and may
# add a small number of freeform tags when nothing fits).
# ---------------------------------------------------------------------------
THEMES = {
    "business-and-economy": [
        "business rates",
        "consumer protection",
        "contracts",
        "employment",
        "exports",
        "financial regulation",
        "fish landings",
        "imports",
        "international trade",
        "labour market",
        "mortgage lending",
        "oil and gas",
        "premises licences",
        "small businesses",
        "subsidies",
        "tourism",
        "unemployment",
    ],
    "crime-and-justice": [
        "anti social behaviour",
        "community safety",
        "courts",
        "crime statistics",
        "criminal justice",
        "domestic violence",
        "enforcement",
        "policing",
        "prisons",
        "probation",
        "reoffending",
        "sentencing",
        "youth justice",
        "appeals",
    ],
    "defence": [
        "armed forces",
        "defence spending",
        "military operations",
        "military personnel",
        "military training",
        "veterans",
        "war pensions",
    ],
    "education": [
        "adult education",
        "apprenticeships",
        "catchment areas",
        "early years",
        "free school meals",
        "further education",
        "higher education",
        "key stages",
        "libraries",
        "national curriculum",
        "primary schools",
        "pupil attainment",
        "qualifications",
        "school admissions",
        "school performance",
        "secondary schools",
        "special educational needs",
        "vocational training",
    ],
    "environment": [
        "agriculture",
        "air quality",
        "biodiversity",
        "climate change",
        "coastal flooding",
        "conservation",
        "crop mapping",
        "dairy farming",
        "deforestation",
        "emissions",
        "fisheries",
        "flood risk",
        "habitats",
        "hazardous waste",
        "insects",
        "livestock",
        "marine biology",
        "marine conservation",
        "marine habitats",
        "nature reserves",
        "pollution",
        "recycling",
        "river flooding",
        "species records",
        "surface water flooding",
        "waste management",
        "water quality",
        "wildlife",
        "trees",
        "rivers",
        "rainfall",
        "soil",
    ],
    "government-and-parliament": [
        "administrative boundaries",
        "civil service",
        "contracts",
        "electoral boundaries",
        "electoral wards",
        "elections",
        "freedom of information",
        "government spending",
        "grants",
        "legislation",
        "local government",
        "organograms",
        "parliament",
        "polling stations",
        "procurement",
        "transparency",
    ],
    "health": [
        "adult social care",
        "clinical audit",
        "dentistry",
        "disease",
        "food safety",
        "health inequalities",
        "hospital admissions",
        "laboratory testing",
        "life expectancy",
        "mental health",
        "mortality",
        "patient outcomes",
        "prescribing",
        "primary care",
        "public health",
        "social care",
        "waiting times",
    ],
    "land-and-property": [
        "addresses",
        "allotments",
        "article 4 directions",
        "brownfield land",
        "compulsory purchase orders",
        "conservation areas",
        "contaminated land",
        "green belt",
        "house prices",
        "housing",
        "land registration",
        "land use",
        "listed buildings",
        "local plans",
        "planning applications",
        "planning policy",
        "postcodes",
        "public rights of way",
        "site allocations",
        "soil surveys",
        "spatial planning",
        "tree preservation orders",
    ],
    "people": [
        "census",
        "community assets",
        "culture",
        "demographics",
        "deprivation",
        "disability",
        "ethnicity",
        "language",
        "migration",
        "neet",
        "population estimates",
        "population projections",
        "religion",
        "art",
        "music",
    ],
    "transport": [
        "active travel",
        "air travel",
        "buses",
        "car parking",
        "cycling",
        "electric vehicles",
        "footpaths",
        "freight",
        "public transport",
        "railways",
        "road maintenance",
        "roads",
        "road safety",
        "road traffic",
        "shipping",
        "walking routes",
    ],
}


# ---------------------------------------------------------------------------
# Suggestion prompt — theme/tag/title/description only
# ---------------------------------------------------------------------------
SYSTEM_CONTENT = """You are a metadata specialist for data.gov.uk,
        the UK open data portal. You classify datasets by theme and suggest
        improved metadata.

        Be specific and evidence-based — every suggestion must reference the
        metadata provided.

        Descriptions and resource URLs are sent in full. If a dataset has more than
        8 resources, only the first 8 are shown; very long extra values may be
        trimmed. Never criticise these digest limits — judge only what is present.

        Never invent facts. The suggested description must only rephrase what is
        present in the metadata — no added topics, audiences, purpose, numbers,
        dates, geographies or sources. If the metadata is too thin to improve on
        without inventing details, set suggested_title / suggested_description to
        empty strings rather than elaborating."""

RUBRIC = """## Suggestions

**suggested_theme**

Pick the single best primary theme from:
${themeList}
If the dataset genuinely spans multiple themes or none clearly
fit, pick the closest one and set theme_confidence low. Never
make up a theme outside the list.

**theme_confidence**

"high" | "medium" | "low" — how confident you are in the theme
assignment.

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

**suggested_title**

A clear improved title, or empty string if the current title is good.

**suggested_description**

A clear improved description, or empty string if the current one is
already good. Length should match the richness of the metadata — a
sentence or two is fine when there is little to say, but 3-4 paragraphs
is appropriate when the metadata supports it.
STRICT RULE — never invent facts. Only rephrase what the metadata
actually says. Do not add topics, audiences, purpose, numbers, dates,
geographies, sources or guidance that are not present in the metadata.
If the metadata is too thin to write a description that adds value
without inventing details, return an empty string."""

SCHEMA = """
Respond with ONE JSON object, no markdown fences, no commentary. Schema:

{
  "suggested_theme": "<exactly one of [${themeKeys}]>",
  "suggested_theme_confidence": "<high | medium | low>",
  "suggested_tags": ["<tag1>", "<tag2>", "..."],
  "suggested_title": "<improved title or empty string>",
  "suggested_description": "<improved description or empty string>"
}"""


def build_prompt(digest: dict) -> list[dict]:
    theme_list = "\n".join(f'- "{t}" — example tags: {", ".join(tags)}' for t, tags in THEMES.items())
    theme_keys = ", ".join(f'"{t}"' for t in THEMES)
    rubric = RUBRIC.replace("${themeList}", theme_list)
    schema = SCHEMA.replace("${themeKeys}", theme_keys)

    return [
        {"role": "system", "content": SYSTEM_CONTENT},
        {
            "role": "user",
            "content": (
                "Classify the following dataset metadata and suggest improvements.\n"
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
