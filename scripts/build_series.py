#!/usr/bin/env python3
"""Build series data from dataset titles.

Scans the datasets table for title patterns that suggest series membership:
  1. Exact duplicate titles (same title, different datasets) — keyed on a
     case/punctuation-normalised title, so "conservation_areas",
     "CONSERVATION AREAS" and "Conservation Areas" group together
  2. Date-suffix clusters (common root with varying dates at the end) —
     date ranges ("1990 to 2018", "January 2009 to December 2009"), fiscal
     years, quarters, months, plain years; roots are trimmed of trailing
     connectors ("… Expenditure for 2020/21" -> "… Expenditure")
  3. Seed-and-grow: decent timeseries then pull in residual datasets that
     carry a year token but no recognised date suffix (all-caps months,
     year-prefixed titles, parenthetical years)

Stores results in two tables:
  series          — one row per detected series
  series_datasets — junction linking series to their datasets

Run after build_db.py (needs the datasets table to exist).

Usage: python scripts/build_series.py
       DATABASE_URL=postgresql://localhost:5432/other python scripts/build_series.py
"""

import re
import sys
from collections import Counter, defaultdict

from scripts.db import connect, database_url

DATABASE_URL = database_url()

# ---- Date stripping patterns ----
# Applied in order; first match wins. Each matches a date-like suffix at
# the end of a title, which strip_date cuts off. re.ASCII keeps \d and \b
# ASCII-only.
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"

DATE_PATTERNS = [
    # January 2010 to December 2010 — month ranges. Without these first, the
    # month-name tail pattern below strips only the last "Month YYYY" and
    # leaves "… to" in the root.
    re.compile(
        rf"\s+({_MONTHS})\s+\d{{4}}\s+to\s+({_MONTHS})\s+\d{{4}}\s*$",
        re.ASCII,
    ),
    # 1994 to 2010 — year ranges (same dangling-"to" problem as above).
    re.compile(r"\s+\d{4}\s+to\s+\d{4}\s*$", re.ASCII),
    # 2020/21, 2020-21, 2020-2021
    re.compile(r"\s+\d{4}\s*[/-]\s*\d{2,4}\s*$", re.ASCII),
    # Q1 2020, Q4 2020/21 etc. (quarter prefix)
    re.compile(r"\s+Q[1-4]\s+\d{4}(\s*[/-]\s*\d{2,4})?\s*$", re.ASCII),
    # January 2020, December 2024
    re.compile(
        rf"\s+({_MONTHS})\s+\d{{4}}\s*$",
        re.ASCII,
    ),
    # 2020 (plain year; must be at end and reasonable-looking)
    re.compile(r"\s+\(?\b(19|20)\d{2}\b\)?\s*$", re.ASCII),
    # (2020) — year in parens at end
    re.compile(r"\s*\(\d{4}\)\s*$", re.ASCII),
]

# Trailing connector words / punctuation left behind by date stripping
# ("NHS Kent and Medway CCG Expenditure for 2020/21" -> "… for",
# "UK Public Procurement Notices - April 2021" -> "… -"). Trimmed repeatedly
# until stable, so "… January 2009 to" loses both "to" and the leftover date
# fragment in one pass.
_CONNECTOR_WORDS = re.compile(r"\s+(?:as of|for|to|in|from|since|of|and|the|at|by)\s*$", re.IGNORECASE)
_TRAILING_PUNCT = re.compile(r"\s*[-\u2013\u2014,;:&/]+\s*$")

# Filename-ish roots: snake_case or a file extension. A bare dot ("No.",
# "£25,000 per transaction.") is NOT filename evidence — a broad rule dropped
# legitimate series like those.
_FILENAME_RE = re.compile(r"_\w|\.(?:csv|xlsx?|json|geojson|zip|txt|pdf)$", re.IGNORECASE)

# Date-suffix roots shorter than this are too vague to be series titles.
MIN_ROOT_LENGTH = 5

# Date-cluster roots need at least this many words. Single-word roots
# are Phase-1 exact duplicates, not date clusters — this only gates Phase 2.
MIN_WORDS = 2


# A series needs at least this many datasets.
MIN_SERIES_SIZE = 2

# A date-cluster timeseries needs at least this many datasets to anchor
# Phase-3 growth (see _grow_timeseries).
MIN_TS_SEED_SIZE = 4

# Year tokens (19xx/20xx) — the anchor that separates a real period
# ("2017", "JANUARY 2017", "(2011-2013)") from a title collision when
# growing a timeseries from a seed.
_YEAR_TOKEN = re.compile(r"(?:19|20)\d{2}")

# Month name directly before a year token, for _year_tail ("…JANUARY 2017").
_MONTH_TAIL = re.compile(rf"(?:{_MONTHS})\s*$", re.IGNORECASE)


def _trim_tail(root: str) -> str:
    """Strip trailing connectors/punctuation from a root, repeatedly."""
    prev = None
    while prev != root:
        prev = root
        root = _TRAILING_PUNCT.sub("", root).strip()
        root = _CONNECTOR_WORDS.sub("", root).strip()
    return root


_PUNCT_NORM = re.compile(r"[^a-z0-9]+")


def _norm_title(title: str) -> str:
    """Case-fold, collapse whitespace, drop punctuation — the Phase-1 recall
    key, so "conservation_areas" / "CONSERVATION AREAS" / "Conservation
    Areas" group together."""
    return _PUNCT_NORM.sub(" ", title.strip().lower()).strip()


def strip_date(title: str) -> dict | None:
    """Strip a date-like suffix from the end of title.

    First pattern to match wins; the root is the title with the match cut
    off, trimmed of trailing connectors, and stripped. Returns
    {"root": ..., "date": ...} when the root is non-empty, None when no
    pattern matches or the root is empty.
    """

    for pattern in DATE_PATTERNS:
        m = pattern.search(title)
        if m:
            root = _trim_tail(title[: m.start()])
            if root:
                return {"root": root, "date": m.group(0).strip()}
    return None


def _keep_date_root(root: str) -> bool:
    """Phase-2 gates: long enough, >= MIN_WORDS, not filename-ish."""
    if len(root) < MIN_ROOT_LENGTH or len(root.split()) < MIN_WORDS:
        return False
    return not _FILENAME_RE.search(root)


def _display_title(datasets: list[dict]) -> str:
    """Best title to show for an exact group: the most common spelling; on
    a tie, the most natural (not all-caps, not all-lowercase, no
    underscores, starts upper); then first-seen. Keeps "Air Quality
    Management Areas" over "air_quality_management_areas" when both
    spellings are in the group."""
    counts = Counter(d["title"].strip() for d in datasets)

    def quality(t: str) -> tuple:
        return (not t.isupper(), not t.islower(), "_" not in t, t[:1].isupper())

    best_title, best_score = None, None
    for t, n in counts.items():
        score = (n, *quality(t))
        if best_score is None or score > best_score:
            best_title, best_score = t, score
    return best_title


def _exact_series_groups(exact_groups: dict[str, list[dict]]) -> tuple[list[dict], int]:
    """Phase-1 assembly: 2+ datasets per normalised title; >1 org -> template."""
    out: list[dict] = []
    count = 0
    for key, datasets in exact_groups.items():
        if len(datasets) < MIN_SERIES_SIZE:
            continue
        if _FILENAME_RE.search(key):
            continue
        orgs = {d["org_slug"] for d in datasets}
        out.append(
            {
                "root_title": _display_title(datasets),
                "type": "template" if len(orgs) > 1 else "timeseries",
                "datasets": datasets,
            },
        )
        count += 1
    return out, count


def _date_series_groups(root_groups: dict[str, dict]) -> tuple[list[dict], int]:
    """Phase-2 assembly: 2+ items per date-stripped root -> timeseries."""
    out: list[dict] = []
    count = 0
    for group in root_groups.values():
        if len(group["items"]) < MIN_SERIES_SIZE:
            continue
        out.append(
            {
                "root_title": group["root"],
                "type": "timeseries",
                "datasets": group["items"],
            },
        )
        count += 1
    return out, count


def _year_tail(title: str) -> str | None:
    """Date-ish tail of a title: from the first year token to the end,
    including a preceding month name so "…SPEND OVER £25K JANUARY 2017"
    yields "JANUARY 2017" (preserves original case). None when no year."""
    m = _YEAR_TOKEN.search(title)
    if not m:
        return None
    start = m.start()
    month = _MONTH_TAIL.search(title[:start])
    if month:
        start = month.start()
    elif start and title[start - 1] == "(":
        start -= 1  # keep the opening paren: "(2011-2013)", not "2011-2013)"
    return title[start:].strip()


def _grown_date(title: str, root: str) -> str | None:
    """Date-ish tail for a grown member, with the seed root stripped out
    when the tail carries it (year-prefixed titles: "2019 Hazardous Waste
    Interrogator" -> "2019")."""
    tail = _year_tail(title)
    if not tail:
        return None
    norm = _norm_title(tail)
    if root and norm.endswith(root):
        return norm[: -len(root)].strip()
    return tail


def _is_grow_seed(group: dict) -> bool:
    """A date cluster worth growing from: >= MIN_TS_SEED_SIZE datasets and a
    2+ word root."""
    return len(group["items"]) >= MIN_TS_SEED_SIZE and len(_norm_title(group["root"]).split()) >= MIN_WORDS


def _in_series_ids(exact_groups: dict[str, list[dict]], root_groups: dict[str, dict]) -> set[str]:
    """Dataset ids that end up in a series (exact or date groups of 2+)."""
    exact = {d["id"] for datasets in exact_groups.values() if len(datasets) >= MIN_SERIES_SIZE for d in datasets}
    date = {d["id"] for g in root_groups.values() if len(g["items"]) >= MIN_SERIES_SIZE for d in g["items"]}
    return exact | date


def _index_residual(rows: list[dict], in_series: set[str]) -> dict[str, list[tuple[dict, str]]]:
    """Residual (unassigned) datasets with a year token, pre-indexed by
    token so each seed only scans rows sharing its first token."""
    by_token: dict[str, list[tuple[dict, str]]] = defaultdict(list)
    for r in rows:
        if r["id"] in in_series:
            continue
        t = _norm_title(r["title"])
        if not _YEAR_TOKEN.search(t):
            continue
        for tok in set(t.split()):
            by_token[tok].append((r, t))
    return by_token


def _grow_timeseries(
    exact_groups: dict[str, list[dict]],
    root_groups: dict[str, dict],
    rows: list[dict],
) -> None:
    """Phase 3: seed-and-grow for timeseries (mutates root_groups items).

    Decent date-cluster timeseries anchor a looser search over residual
    datasets — ones in no series at all — whose normalised title contains
    the root AND carries a year token. The year token is the anchor that
    separates a real period ("2017", "JANUARY 2017", "(2011-2013)") from
    a title collision, and it catches formats the Phase-2 patterns miss:
    all-caps months ("…OVER £25K JANUARY 2017"), year-prefixed titles
    ("2024 Hazardous Waste Interrogator"), parenthetical years.

    Each residual dataset joins at most one series — the seed with the
    longest root (most specific), then the biggest.

    Known false-positive pattern: roots that are substrings of a longer,
    different concept ("Somerset NHS Foundation Trust Expenditure" matching
    "Taunton and Somerset NHS Foundation Trust Expenditure Over £25k").
    """
    in_series = _in_series_ids(exact_groups, root_groups)
    seeds = [g for g in root_groups.values() if _is_grow_seed(g)]
    if not seeds:
        return

    by_token = _index_residual(rows, in_series)

    # Assign each residual dataset to its best seed (longest root, biggest
    # group — both read before any appends, so the choice is deterministic).
    best: dict[str, tuple] = {}
    for g in seeds:
        root = _norm_title(g["root"])
        root_toks = root.split()
        root_re = re.compile(rf"\b{re.escape(root)}\b")
        score = (len(root_toks), len(g["items"]))
        for r, t in by_token.get(root_toks[0], ()):
            if not root_re.search(t):
                continue
            key = r["id"]
            prev = best.get(key)
            if prev is None or score > prev[0]:
                best[key] = (score, g, r)

    for _, g, r in best.values():
        g["items"].append({**dict(r), "date": _grown_date(r["title"], _norm_title(g["root"]))})


def build_all_series(rows: list[dict]) -> tuple[list[dict], int, int]:
    """Detect series from dataset rows.

    rows: [{id, title, org_slug, org_display_name}, ...] — the datasets
    table rows with a non-empty title (the caller's WHERE clause).

    Returns (all_series, exact_series, date_series):
      all_series   — [{root_title, type, datasets}, ...]; Phase 1 exact
                     duplicate groups first, then Phase 2 date-suffix
                     clusters, both in insertion order (SERIAL ids are
                     assigned in this order at insert time).
      exact_series — count of Phase 1 groups (2+ datasets)
      date_series  — count of Phase 2 clusters (2+ items)

    dataset_count / org_count are computed at insert time (see _write_series).
    """

    # ---- Phase 1: Exact duplicate titles ----
    # Keyed on the case/punct-normalised title so spelling variants of a
    # known template ("conservation_areas" vs "Conservation Areas") land in
    # the same group; the shown root_title is picked in _exact_series_groups.
    exact_groups: dict[str, list[dict]] = {}
    for r in rows:
        exact_groups.setdefault(_norm_title(r["title"]), []).append(r)

    # ---- Phase 2: Date-suffix clusters ----
    root_groups: dict[str, dict] = {}
    for r in rows:
        result = strip_date(r["title"].strip())
        if not result:
            continue
        root = result["root"]
        if not _keep_date_root(root):
            continue
        key = root.lower()
        if key not in root_groups:
            root_groups[key] = {"root": root, "items": []}
        root_groups[key]["items"].append({**dict(r), "date": result["date"]})

    # ---- Phase 3: seed-and-grow timeseries ----
    # Decent date clusters pull in residual datasets that carry a year
    # token but no recognised date suffix. Mutates root_groups in place.
    _grow_timeseries(exact_groups, root_groups, rows)

    # ---- Assemble ----
    exact_series_list, exact_series = _exact_series_groups(exact_groups)
    date_series_list, date_series = _date_series_groups(root_groups)

    # Phase 2 date clusters become timeseries. The same root can also exist
    # as a Phase 1 exact group (e.g. "Planning Applications" is both a
    # multi-council template and Wigan's year-by-year series) — they stay
    # separate rows with different types.
    return exact_series_list + date_series_list, exact_series, date_series


TRUNCATE_SQL = "TRUNCATE TABLE series_datasets, series RESTART IDENTITY CASCADE"


def _write_series(tx, all_series: list[dict]) -> None:
    """Insert all series + junction rows inside the transaction."""

    insert_series = tx.prepare(
        "INSERT INTO series (root_title, type, dataset_count, org_count) VALUES (?, ?, ?, ?) RETURNING id",
    )
    insert_sd = tx.prepare(
        "INSERT INTO series_datasets (series_id, dataset_id, dataset_title, date_suffix,"
        " org_slug, org_display_name) VALUES (?, ?, ?, ?, ?, ?)",
    )
    for s in all_series:
        orgs = {d["org_slug"] for d in s["datasets"]}
        result = insert_series.get(
            s["root_title"],
            s["type"],
            len(s["datasets"]),
            len(orgs),
        )
        series_id = result["id"]
        for d in s["datasets"]:
            insert_sd.run(
                series_id,
                d["id"],
                d["title"],
                d.get("date"),  # Phase 1 rows have no date -> NULL
                d["org_slug"],
                d["org_display_name"],
            )


def main() -> None:
    db = connect(DATABASE_URL)
    try:
        print("Reading datasets...")
        rows = db.prepare(
            "SELECT id, title, org_slug, org_display_name FROM datasets WHERE title IS NOT NULL AND title != ''",
        ).all()
        print(f"  {len(rows)} datasets with titles")

        all_series, exact_series, date_series = build_all_series(
            [dict(r) for r in rows],
        )

        print("\nPhase 1: exact duplicate titles...")
        print(f"  {exact_series} exact-duplicate series found")

        print("\nPhase 2: date-suffix clusters...")
        print(f"  {date_series} date-suffix series found (after dedup)")

        # ---- Write to database ----
        print("\nWriting series tables...")
        db.exec(TRUNCATE_SQL)
        db.transaction(lambda tx: _write_series(tx, all_series))

        # Stats
        stats = db.prepare(
            "SELECT type, COUNT(*) AS n, SUM(dataset_count) AS d FROM series GROUP BY type",
        ).all()
        print(f"\nDone. Series table: {len(all_series)} series")
        for s in stats:
            print(f"  {s['type']}: {s['n']} series, {s['d']} datasets")
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
