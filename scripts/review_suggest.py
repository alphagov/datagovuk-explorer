#!/usr/bin/env python3
"""One LLM call per dataset: quality scores + theme/tag suggestions.

Reads datasets from the quality index, sends a curated digest to the
model, and writes one JSON file per dataset to downloads/reviews/<org>/.
Each record has:

  scores   — findability, resources (0-5 + explanation)
  theme    — suggested primary theme from the 14-theme vocabulary
  tags     — 3-8 suggested subject-matter tags
  title    — suggested title (or empty if current is good)
  desc     — suggested description (or empty if current is good)

Remote mode reads the API key from the LLM env var; local mode targets a
llama.cpp server using LOCAL_MODEL and LOCAL_BASE_URL from .env.

Usage:
  python scripts/review_suggest.py                       # 20 random datasets
  python scripts/review_suggest.py --limit 50
  python scripts/review_suggest.py --org environment-agency
  python scripts/review_suggest.py --dataset <id> --dataset <id2>
  python scripts/review_suggest.py --dataset <id> --include-reviewed

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
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Annotated

import httpx
import typer

from scripts.db import connect, database_url
from scripts.rate_limit import sleep

app = typer.Typer(add_completion=False)

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "downloads" / "reviews"
DATABASE_URL = database_url()
REQUEST_TIMEOUT = 120  # seconds
RETRIES = 2  # attempts are 0..RETRIES (up to 3 tries)
REMOTE_CONCURRENCY = 50
MAX_TOKENS = 2048
TEMPERATURE = 0.2

# Resource digest — first N resources per dataset (+ a count note).
MAX_DIGEST_RESOURCES = 8


class ReviewError(RuntimeError):
    """LLM/HTTP error carrying an optional HTTP status (for the 429 retry).

    status is set only for HTTP errors; the retry loop checks status ==
    HTTPStatus.TOO_MANY_REQUESTS to decide the backoff.
    """

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


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
# Curated digest (shared between review and classify — identical logic)
# ---------------------------------------------------------------------------
EXTRAS_WHITELIST = {
    "frequency-of-update": "update_frequency",
    "update_frequency": "update_frequency",
    "dataset-reference-date": "temporal_reference",
    "temporal_coverage": "temporal_coverage",
    "geographic_coverage": "geographic_coverage",
    "publisher": "publisher",
    "access_constraints": "access_constraints",
    "licence": "licence_statement",
    "resource-type": "resource_type",
    "spatial-reference-system": "spatial_reference_system",
    "schema-vocabulary": "schema_vocabulary",
    "codelist": "codelist",
}


# ---------------------------------------------------------------------------
# Timestamp + string helpers
# ---------------------------------------------------------------------------
def iso_now() -> str:
    """Current UTC time, ISO 8601 with milliseconds — e.g. 2026-08-03T15:04:29.901Z."""

    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def truncate(s, n: int):
    """null -> null; string-coerce then slice to n chars + '…' when longer.

    A bool coerces to 'true'/'false' (not 'True'/'False') so the digest
    output stays consistent.
    """

    if s is None:
        return None
    s = ("true" if s else "false") if isinstance(s, bool) else str(s)
    return s[:n] + "…" if len(s) > n else s


def strip_html(s) -> str:
    """Coerce to str, strip tags, decode &amp;/&nbsp;, collapse whitespace."""

    s = str(s if s is not None else "")
    s = re.sub(r"<[^>]*>", " ", s)
    s = s.replace("&amp;", "&")
    s = s.replace("&nbsp;", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def digest_resource(r: dict) -> dict:
    """One resource -> the slim digest object (key order matters: format,
    then name/description/url/size/created as present)."""

    out = {"format": r.get("format") or None}
    if r.get("name"):
        out["name"] = truncate(r["name"], 200)
    if r.get("description"):
        out["description"] = truncate(r["description"], 1000)
    if r.get("url"):
        out["url"] = r["url"]
    if r.get("created"):
        out["created"] = str(r["created"])[:10]
    return out


def build_digest(pkg: dict) -> dict:
    """Curated digest sent to the model."""

    extras = {}
    for e in pkg.get("extras") or []:
        if not isinstance(e, dict):
            continue
        key = EXTRAS_WHITELIST.get(e.get("key"))
        if key:
            extras[key] = truncate(e.get("value"), 2000)

    resources = [digest_resource(r) for r in (pkg.get("resources") or [])[:MAX_DIGEST_RESOURCES]]
    total = pkg.get("num_resources")
    if total is None:
        total = len(pkg.get("resources") or [])
    if total > MAX_DIGEST_RESOURCES:
        resources.append({"_note": f"…and {total - MAX_DIGEST_RESOURCES} more resources"})

    return {
        "title": pkg.get("title"),
        "organisation": (
            (pkg.get("_organisation") or {}).get("display_name") or (pkg.get("organization") or {}).get("title") or None
        ),
        "theme": pkg.get("theme-primary") or None,
        "licence": pkg.get("license_title") or None,
        "open_licence": pkg.get("isopen"),
        "created": str(pkg.get("metadata_created") or "")[:10],
        "last_modified": str(pkg.get("metadata_modified") or "")[:10],
        "description": truncate(strip_html(pkg.get("notes")), 20000),
        "tags": [t if isinstance(t, str) else t.get("name") for t in (pkg.get("tags") or [])][:10],
        "resources": resources,
        "extras": extras,
    }


# ---------------------------------------------------------------------------
# Combined prompt — review scores + theme/tag suggestions
#
# The three strings below are the model prompt — the prompt is the model
# contract, so copy exactly rather than paraphrase.
# ---------------------------------------------------------------------------
SYSTEM_CONTENT = """You are a data-quality reviewer and metadata specialist for data.gov.uk,
        the UK open data portal. You evaluate dataset metadata against open-data
        best practice and suggest improvements.

        Be specific and evidence-based — every score must be justified by the
        explanation, referencing the metadata provided. Be critical but fair: a
        small public-sector dataset published as a monthly CSV can be high quality.
        Flag unexplained jargon or technical language that a non-specialist could
        not understand.

        Descriptions and resource URLs are sent in full. If a dataset has more than
        8 resources, only the first 8 are shown; very long extra values may be
        trimmed. Never criticise these digest limits — judge only what is present.

        Never invent facts. The suggested description must only rephrase what is
        present in the metadata — no added topics, audiences, purpose, numbers,
        dates, geographies or sources. If the metadata is too thin to improve on
        without inventing details, set suggested_title / suggested_description to
        empty strings rather than elaborating."""

RUBRIC = """## Part 1 — Quality review

Every dimension starts at score 5. Deduct points only for specific, named
problems — every deduction must cite the concrete issue that caused it.

**findability**

A clear, plain title that says what the data is; a useful description;
relevant tags; a theme. The TITLE is the single most important signal —
a vague, jargon-heavy or misleading title caps findability at 2/5.

**resources**

Downloadable data files in sensible formats (CSV/GeoJSON/XLSX etc.).
HTML alone can be ok in context (eg it represents API documentation).
They should have clear names.
Do not penalise National Archives links.

## Part 2 — Suggestions

**theme**

Pick the single best primary theme from:
${themeList}
If the dataset genuinely spans multiple themes or none clearly
fit, pick the closest one and set theme_confidence low. Never
make up a theme outside the list.

**theme_confidence**

"high" | "medium" | "low" — how confident you are in the theme
assignment.

**tags**

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
  "scores": {
    "findability": { "score": <int 0-5>, "explanation": "<1-2 sentence reason>" },
    "resources":   { "score": <int 0-5>, "explanation": "<1-2 sentence reason>" }
  },
  "theme": "<exactly one of [${themeKeys}]>",
  "theme_confidence": "<high | medium | low>",
  "tags": ["<tag1>", "<tag2>", "..."],
  "suggested_title": "<improved title or empty string>",
  "suggested_description": "<improved description or empty string>"
}"""


def build_prompt(digest: dict) -> list[dict]:
    """The chat messages. themeList interpolates into both the rubric and
    the schema — the `${themeList}` placeholder is kept verbatim in the
    constants above."""

    theme_list = "\n".join(f'- "{t}" — example tags: {", ".join(tags)}' for t, tags in THEMES.items())
    theme_keys = ", ".join(f'"{t}"' for t in THEMES)
    rubric = RUBRIC.replace("${themeList}", theme_list)
    schema = SCHEMA.replace("${themeKeys}", theme_keys)

    return [
        {"role": "system", "content": SYSTEM_CONTENT},
        {
            "role": "user",
            "content": (
                "Evaluate and classify the following dataset metadata.\n"
                f"{rubric}\n\n"
                "Dataset metadata (JSON):\n"
                f"{json.dumps(digest, indent=1, ensure_ascii=False)}\n"
                f"{schema}\n\n"
                "Now return the review JSON."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# API client (shared between remote and local llama.cpp)
# ---------------------------------------------------------------------------
def check_server(client: httpx.Client, base_url: str) -> None:
    """Local-mode health check: {base}/health must return {"status": "ok"}."""

    res = client.get(f"{base_url}/health", timeout=10)
    if not res.is_success:
        raise ReviewError(f"health check failed with HTTP {res.status_code}")
    body = res.json()
    if body.get("status") != "ok":
        raise ReviewError(f'server reports status "{body.get("status")}"')


def _is_anthropic(base_url: str, model: str = "") -> bool:
    # Direct Anthropic API, or a proxy serving Bedrock models (eu./us./ap. prefix).
    return "api.anthropic.com" in base_url or bool(
        re.match(r"(eu|us|ap)\.anthropic\.", model),
    )


def send_request(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    model: str,
    digest: dict,
) -> str:
    """One chat completion call. Returns the trimmed reply content.

    Routes to the Anthropic Messages API when base_url contains
    api.anthropic.com; otherwise uses the OpenAI-compatible
    /v1/chat/completions endpoint (remote or local llama).
    """

    if _is_anthropic(base_url, model):
        return _send_anthropic(client, base_url, api_key, model, digest)
    return _send_openai_compat(client, base_url, api_key, model, digest)


def _send_openai_compat(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    model: str,
    digest: dict,
) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body: dict = {"model": model, "messages": build_prompt(digest)}
    if api_key:
        body["thinking"] = {"type": "disabled"}
    body["max_tokens"] = MAX_TOKENS
    body["temperature"] = TEMPERATURE

    res = client.post(
        f"{base_url}/v1/chat/completions",
        headers=headers,
        content=json.dumps(body, ensure_ascii=False, separators=(",", ":")),
    )
    if not res.is_success:
        raise ReviewError(
            f"HTTP {res.status_code}: {truncate(res.text, 200)}",
            status=res.status_code,
        )
    data = res.json()
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        message = None
    content = (message or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise ReviewError("empty reply content (max_tokens may be too low)")
    return content.strip()


def _send_anthropic(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    model: str,
    digest: dict,
) -> str:
    # Split system message from user messages — Anthropic takes system as a
    # top-level field, not a messages entry.
    messages = build_prompt(digest)
    system_text = next((m["content"] for m in messages if m["role"] == "system"), None)
    user_messages = [m for m in messages if m["role"] != "system"]

    # API keys start with "sk-ant-api"; anything else is treated as an
    # OAuth bearer token (e.g. ANTHROPIC_AUTH_TOKEN from Claude Code).
    is_oauth = not api_key.startswith("sk-ant-api")
    headers: dict = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    if is_oauth:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["anthropic-beta"] = "oauth-2025-04-20"
    else:
        headers["x-api-key"] = api_key

    body: dict = {"model": model, "max_tokens": MAX_TOKENS, "messages": user_messages}
    if system_text:
        body["system"] = system_text

    res = client.post(
        f"{base_url}/v1/messages",
        headers=headers,
        content=json.dumps(body, ensure_ascii=False, separators=(",", ":")),
    )
    if not res.is_success:
        raise ReviewError(
            f"HTTP {res.status_code}: {truncate(res.text, 200)}",
            status=res.status_code,
        )
    data = res.json()
    try:
        content = next(b["text"] for b in data["content"] if b.get("type") == "text")
    except (KeyError, IndexError, StopIteration, TypeError):
        content = None
    if not isinstance(content, str) or not content.strip():
        raise ReviewError("empty reply content (max_tokens may be too low)")
    return content.strip()


def extract_json(text: str) -> dict:
    """Strip ```json fences, slice first { to last }, parse as JSON."""

    stripped = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in reply")
    return json.loads(stripped[start : end + 1])


# ---------------------------------------------------------------------------
# Store: one JSON file per dataset in downloads/reviews/<org>/
# ---------------------------------------------------------------------------
def slugify(title: str) -> str:
    """Lowercase, [^a-z0-9]+ -> '-', trim dashes, [:80]."""
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"^-+|-+$", "", s)
    return s[:80]


def load_processed_ids(out_dir: Path) -> tuple[set, set]:
    """(ok, attempted) dataset-id sets from per-dataset JSON files under
    out_dir. Corrupt files are skipped."""

    ok: set[str] = set()
    attempted: set[str] = set()
    if not out_dir.exists():
        return ok, attempted
    for f in out_dir.rglob("*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        attempted.add(rec.get("dataset_id"))
        if rec.get("ok"):
            ok.add(rec.get("dataset_id"))
    return ok, attempted


def write_record(out_dir: Path, record: dict) -> None:
    """Write one JSON file per dataset: out_dir/<org_slug>/<slug>-<id[:8]>.json."""
    org = record.get("org_slug") or "_unknown"
    title = record.get("title") or record["dataset_id"]
    filename = f"{slugify(title)}-{record['dataset_id'][:8]}.json"
    directory = out_dir / org
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReviewConfig:
    """The five call-wide values every worker needs — client, endpoint,
    auth, model and output directory. Built once in run() and passed down,
    so the per-row functions stay small."""

    client: httpx.Client
    base_url: str
    api_key: str
    model: str
    out_dir: Path
    show_prompt: bool = False


def _summary_guard(summary_lock: threading.Lock | None):
    """The summary lock when process_one runs in a thread pool; a no-op
    context for direct (single-threaded) calls."""

    return summary_lock if summary_lock is not None else nullcontext()


def _record_base(row, model: str) -> dict:
    """The fixed record fields shared by ok and error records."""
    return {
        "dataset_id": row["id"],
        "title": row["title"],
        "org_slug": row["org_slug"],
        "org_display_name": row["org_display_name"],
        "model": model,
        "reviewed_at": iso_now(),
        "classified_at": iso_now(),
    }


def _fetch_record(config: ReviewConfig, base: dict, digest: dict) -> dict:
    """One dataset's record: send -> parse -> validate theme/tags -> ok:true.

    The retry loop allows up to RETRIES+1 attempts; any error retries, but
    only HTTP 429 backs off (sleep 2000*(attempt+1)ms). The returned record
    is ok:true with the parsed model output, or ok:false with the last
    error message.
    """
    record: dict = {**base, "ok": False, "error": "unknown"}
    for attempt in range(RETRIES + 1):
        try:
            content = send_request(config.client, config.base_url, config.api_key, config.model, digest)
            parsed = extract_json(content)

            # Validate theme / tags before accepting the record.
            if parsed.get("theme") and parsed["theme"] not in THEMES:
                raise ReviewError(  # noqa: TRY301 — validation errors are caught by the same try to record failed records
                    f'invalid theme "{parsed["theme"]}" — not in vocabulary',
                )
            if not isinstance(parsed.get("tags"), list):
                raise ReviewError("tags must be an array")  # noqa: TRY301 — validation, caught by the same try

            record = {**base, "ok": True, **parsed}
            break
        except (httpx.HTTPError, ReviewError, ValueError) as err:
            record["error"] = str(err)
            if getattr(err, "status", None) == HTTPStatus.TOO_MANY_REQUESTS and attempt < RETRIES:
                sleep(2000 * (attempt + 1))
    return record


def _record_summary(record: dict, summary: dict, summary_lock: threading.Lock | None) -> None:
    """Accumulate ok/failed counts + overall scores into the shared summary
    dict (lock-guarded when running in a thread pool)."""
    with _summary_guard(summary_lock):
        if record["ok"]:
            summary["ok"] += 1
        else:
            summary["failed"] += 1


def _worst_dimension(record: dict) -> str:
    """The lowest-scoring dimension's explanation as a ' | …' suffix ('' when
    the lowest dimension has no explanation)."""
    lowest = None
    for s in (record.get("scores") or {}).values():
        if not isinstance(s, dict):
            continue
        sc = s.get("score")
        key = 5 if sc is None else sc
        if lowest is None or key < lowest[0]:
            lowest = (key, s)
    return f" | {lowest[1]['explanation']}" if lowest and lowest[1].get("explanation") else ""


def _print_progress(record: dict, row, i: int, total: int) -> None:
    """Per-dataset progress line (show_progress only)."""
    if record["ok"]:
        print(
            f"[{i + 1}/{total}] theme {record.get('theme')} ({record.get('theme_confidence') or '?'})"
            f" | {row['org_slug']}/{row['title']}{_worst_dimension(record)}",
        )
    else:
        print(
            f"[{i + 1}/{total}] FAILED: {record['error']} | {row['org_slug']}/{row['title']}",
        )


def process_one(
    config: ReviewConfig,
    row,
    i: int,
    total: int,
    *,
    show_progress: bool,
    summary: dict,
    summary_lock: threading.Lock | None = None,
) -> None:
    """Review + classify one dataset row and append its record.

    The retry loop lives in _fetch_record (the only place that raises
    ReviewError — the noqa: TRY301 comments live there too); the summary
    and progress printing are separate concerns here.
    """
    digest = build_digest(row["json"])
    if config.show_prompt:
        messages = build_prompt(digest)
        print("\n" + "=" * 72)
        for msg in messages:
            print(f"--- {msg['role']} ---")
            print(msg["content"])
        print("=" * 72 + "\n")
    base = _record_base(row, config.model)

    record = _fetch_record(config, base, digest)
    record["input"] = digest
    write_record(config.out_dir, record)
    _record_summary(record, summary, summary_lock)

    if show_progress:
        _print_progress(record, row, i, total)


def run_workers(
    config: ReviewConfig,
    rows: list,
    concurrency: int,
    *,
    show_progress: bool,
    summary: dict,
) -> None:
    """Run workers: min(concurrency, rows) threads share an index + summary.

    The next-row index and the summary dict are lock-guarded; each thread
    owns its LLM request (httpx.Client is thread-safe), so the 50-way
    remote concurrency is a plain thread pool — no event loop.
    """

    next_i = 0
    index_lock = threading.Lock()
    summary_lock = threading.Lock()
    workers = min(concurrency, len(rows))

    def worker() -> None:
        nonlocal next_i
        while True:
            with index_lock:
                if next_i >= len(rows):
                    return
                i = next_i
                next_i += 1
            process_one(
                config,
                rows[i],
                i,
                len(rows),
                show_progress=show_progress,
                summary=summary,
                summary_lock=summary_lock,
            )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker) for _ in range(workers)]
        for f in futures:
            f.result()  # propagate exceptions from worker threads


def run(
    *,
    limit: int | None,
    org: str | None,
    dataset: list[str] | None,
    model: str,
    base_url: str,
    api_key: str,
    concurrency: int,
    out_dir: Path,
    include_reviewed: bool,
    show_progress: bool,
    show_prompt: bool = False,
) -> None:
    """Fetch + review + write per-dataset records for the selected rows."""

    is_remote = bool(api_key)
    org_filter = org or None
    id_filter = dataset or []

    with httpx.Client(follow_redirects=True, timeout=REQUEST_TIMEOUT) as client:
        if not is_remote:
            try:
                check_server(client, base_url)
            except (httpx.HTTPError, ReviewError, ValueError) as err:
                print(
                    f"Cannot reach the model server at {base_url}: {err}",
                    file=sys.stderr,
                )
                print(
                    "Start the server configured by LOCAL_BASE_URL (e.g. llama-server) "
                    "or pass an API key for remote mode.",
                    file=sys.stderr,
                )
                raise typer.Exit(1) from None

        processed, attempted = load_processed_ids(out_dir)
        if len(processed) > 0 and not include_reviewed:
            print(
                f"Skipping {len(processed)} already-processed dataset(s) (--include-reviewed to force)",
            )

        db = connect(DATABASE_URL)
        try:
            select_sql = """SELECT d.id, d.title, d.org_slug, d.org_display_name, j.json
             FROM datasets d
             JOIN dataset_json j ON j.id = d.id
             WHERE (?::text IS NULL OR d.org_slug = ?)
               AND d.resource_count > 0"""

            if id_filter:
                placeholders = ",".join("?" for _ in id_filter)
                rows = db.prepare(
                    select_sql + f"\n AND d.id IN ({placeholders})",
                ).all(org_filter, org_filter, *id_filter)
            elif include_reviewed:
                ids = list(attempted)
                pick = limit if limit is not None else len(ids)
                rows = []
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    rows = db.prepare(
                        select_sql + f"\n AND d.id IN ({placeholders})\n LIMIT ?",
                    ).all(org_filter, org_filter, *ids, pick)
            elif limit is not None:
                pick = limit
                candidates = db.prepare(
                    select_sql + "\n ORDER BY RANDOM()\n LIMIT ?",
                ).all(org_filter, org_filter, pick * 4)
                rows = [r for r in candidates if r["id"] not in processed][:pick]
            else:
                candidates = db.prepare(
                    select_sql + "\n ORDER BY d.org_slug, d.title",
                ).all(org_filter, org_filter)
                rows = [r for r in candidates if r["id"] not in processed]
        finally:
            db.close()

        if not rows:
            print("No datasets to process.")
            return
        print(
            f"Processing {len(rows)} dataset(s) with {model} via {base_url} (concurrency {concurrency})",
        )

        summary = {"ok": 0, "failed": 0}
        t0 = time.monotonic()
        run_workers(
            ReviewConfig(
                client=client,
                base_url=base_url,
                api_key=api_key,
                model=model,
                out_dir=out_dir,
                show_prompt=show_prompt,
            ),
            rows,
            concurrency,
            show_progress=show_progress,
            summary=summary,
        )

        elapsed = time.monotonic() - t0
        print(
            f"Done in {elapsed:.1f}s — {summary['ok']} reviewed, {summary['failed']} failed. "
            f"Results written to {out_dir}",
        )


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
    # Annotated form avoids ruff B008 (a typer.Option() call as a default).
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
    """Review + suggest — one LLM call per dataset (scores + theme/tags)."""

    if limit is not None and limit < 1:
        print("--limit must be >= 1", file=sys.stderr)
        raise typer.Exit(1)

    key = (
        api_key
        or os.environ.get("LLM")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    ).strip()
    is_remote = bool(key)
    base = base_url or (os.environ.get("LLM_BASE_URL") if is_remote else os.environ.get("LOCAL_BASE_URL"))
    mdl = model or (os.environ.get("LLM_MODEL") if is_remote else os.environ.get("LOCAL_MODEL"))
    if not base or not mdl:
        vars_msg = "LLM_MODEL and LLM_BASE_URL" if is_remote else "LOCAL_MODEL and LOCAL_BASE_URL"
        print(
            f"Need a model and API base URL — set {vars_msg} in .env (or pass --model / --base-url).",
            file=sys.stderr,
        )
        raise typer.Exit(1)

    # Local mode is always single-threaded (local llama — hard-coded 1).
    # Only remote concurrency is validated.
    if is_remote:
        concurrency = concurrency if concurrency is not None else REMOTE_CONCURRENCY
        if concurrency < 1:
            print("--concurrency must be >= 1", file=sys.stderr)
            raise typer.Exit(1)
    else:
        concurrency = 1

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
            concurrency=concurrency,
            out_dir=out_dir,
            include_reviewed=include_reviewed,
            show_progress=progress or bool(dataset),
            show_prompt=show_prompt,
        )
    except typer.Exit:
        raise  # exit codes raised inside run() (e.g. the health check)
    except (httpx.HTTPError, RuntimeError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
