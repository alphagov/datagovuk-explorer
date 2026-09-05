#!/usr/bin/env python3
"""Experiment harness: candidate improvements to series/template detection.

Read-only. Runs the current build_series.py detector (baseline) against
candidate "v2" detectors purely in memory from dataset titles — no DB
writes, no migrations, no changes to production code. The point is to try
ideas cheaply against real data and see the effect before committing
anything to scripts/build_series.py (and its schema + tests).

Several detection ideas below were folded into build_series when they
landed (range patterns, connector trim, min-words, filename rejection,
normalised exact keys); keep that in mind when reading the v1/v2 totals.

Experiments:
  E1 roots    — date-range patterns + trailing-connector trim + min-words
                + filename rejection. Shows fixed garbage roots, new drops,
                and residue still to handle.
  E2 types    — splits the conflation of "how titles group" (exact/date)
                and "what the group means" (template / timeseries /
                duplicates / hybrid). Re-derives every series' semantics
                and cross-tabs v1 -> v2.
  E3 overlap  — datasets that land in more than one series.
  E4 template — are "template" datasets actually identical copies
                (Organogram) or just same-named (Allotments)? Uses notes.
  E5 recall   — case+punct normalisation (punct_normalize flag): how many
                more template families/memberships appear, and are the
                genuinely-new families quality (notes similarity gate)?
  E6 seed-grow— once a series is "decent" (a confident template/timeseries),
                use it as an anchor to find residual datasets whose titles
                contain/prefix/suffix its root (timeseries also need a
                year token). Precision-first: only grown from decent seeds.

Flags (all on by default; each is togglable for ablation):
  range_patterns   add "Month YYYY to Month YYYY" / "YYYY to YYYY" patterns
  trim_connectors  strip trailing "-" / "for" / "to" / "as of" ... from roots
  min_words        require >= 2 words in a date-cluster root (0 disables)
  reject_filenames skip snake_case / file-extension roots
  casefold_exact   Phase-1 exact dup groups keyed on lowercase title
  punct_normalize  Phase-1 groups keyed on case+punct-normalised title
                   (recall: finds "conservation_areas" and "CONSERVATION
                   AREAS" publishers of known templates — E5 gates the
                   genuinely-new families it creates by notes similarity)

Usage:
    uv run --env-file .env python -m scripts.experiment_series
    uv run --env-file .env python -m scripts.experiment_series --sample 20000
    uv run --env-file .env python -m scripts.experiment_series --flags trim_connectors,min_words
    uv run --env-file .env python -m scripts.experiment_series --no-notes
"""

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/datagovuk_explorer")

from scripts.build_series import (
    DATE_PATTERNS,
    MIN_ROOT_LENGTH,
    build_all_series,
    strip_date as strip_date_v1,
)
from scripts.db import connect, database_url

MIN_SERIES_SIZE = 2
TIGHT_SHARE = 0.8
MEDIUM_SHARE = 0.5
TWO_GROUPINGS = 2
_ROOT_WS = re.compile(r"\s+")
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"

# Whole-range suffixes — "January 2010 to December 2010", "1994 to
# 2010". These now live in build_series' DATE_PATTERNS itself; the
# range_patterns flag below just re-tries them at the front of the list.
RANGE_MONTH = re.compile(
    rf"\s+({_MONTHS})\s+\d{{4}}\s+to\s+({_MONTHS})\s+\d{{4}}\s*$",
    re.ASCII,
)
RANGE_YEAR = re.compile(r"\s+\d{4}\s+to\s+\d{4}\s*$", re.ASCII)

# build_series' DATE_PATTERNS, with the two range patterns first (first
# match wins).
DATE_PATTERNS_V2 = [RANGE_MONTH, RANGE_YEAR, *DATE_PATTERNS]

# Trailing connector words / punctuation left behind by date stripping
# ("Expenditure for 2020/21" -> "… Expenditure for", "Notices - April 2021"
# -> "Notices -"). Trimmed repeatedly until stable.
_CONNECTOR_WORDS = re.compile(r"\s+(?:as of|for|to|in|from|since|of|and|the|at|by)\s*$", re.IGNORECASE)
_TRAILING_PUNCT = re.compile(r"\s*[-\u2013\u2014,;:&/]+\s*$")

# Filename-ish roots: snake_case or a file extension. A bare dot ("No.",
# "£25,000 per transaction.") is NOT filename evidence — a broad rule
# dropped legitimate series like those.
_FILENAME_RE = re.compile(r"_\w|\.(?:csv|xlsx?|json|geojson|zip|txt|pdf)$", re.IGNORECASE)

_RESIDUE_RE = re.compile(
    r"(?:[-\u2013\u2014,;:&/]| as of| for| to| in| from| since| of| and| the| at| by)$",
    re.IGNORECASE,
)

# Phase-1 recall key: case-fold, collapse whitespace, drop punctuation.
# "conservation_areas" and "CONSERVATION AREAS" both become
# "conservation areas".
_PUNCT_NORM = re.compile(r"[^a-z0-9]+")


def _norm_title(t: str) -> str:
    return _PUNCT_NORM.sub(" ", t.strip().lower()).strip()


@dataclass
class Flags:
    range_patterns: bool = True
    trim_connectors: bool = True
    min_words: int = 2
    reject_filenames: bool = True
    casefold_exact: bool = True
    punct_normalize: bool = True


def strip_date_v2(title: str, flags: Flags) -> dict | None:
    """v1 strip_date with the v2 pattern list + optional root trimming.

    range_patterns toggles whether the two range patterns are tried first;
    the other flags control root post-processing only.
    """
    patterns = DATE_PATTERNS_V2 if flags.range_patterns else DATE_PATTERNS
    for pattern in patterns:
        m = pattern.search(title)
        if m:
            root = title[: m.start()].strip()
            if not root:
                return None
            if flags.trim_connectors:
                root = _trim_tail(root)
                if not root:
                    return None
            return {"root": root, "date": m.group(0).strip()}
    return None


def _trim_tail(root: str) -> str:
    prev = None
    while prev != root:
        prev = root
        root = _TRAILING_PUNCT.sub("", root).strip()
        root = _CONNECTOR_WORDS.sub("", root).strip()
    return root


def _semantics(grouping: str, group_rows: list[dict]) -> str:
    orgs = {r["org_slug"] for r in group_rows}
    if grouping == "exact":
        return "template" if len(orgs) > 1 else "duplicates"
    return "hybrid" if len(orgs) > 1 else "timeseries"


def _keep_root(root: str, flags: Flags) -> bool:
    if flags.reject_filenames and _FILENAME_RE.search(root):
        return False
    return not (flags.min_words and len(root.split()) < flags.min_words)


def _exact_groups(rows: list[dict], flags: Flags) -> list[dict]:
    """Phase 1: exact duplicate titles (casefold / punct-normalise optional)."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        t = r["title"].strip()
        if flags.punct_normalize:
            key = _norm_title(t)
        elif flags.casefold_exact:
            key = t.lower()
        else:
            key = t
        groups.setdefault(key, []).append(r)
    out = []
    for key, datasets in groups.items():
        if len(datasets) < MIN_SERIES_SIZE:
            continue
        # filename check: normalised keys are clean, so test the key in that
        # mode ("conservation_areas" -> "conservation areas" is kept).
        probe = key if flags.punct_normalize else datasets[0]["title"].strip()
        if flags.reject_filenames and _FILENAME_RE.search(probe):
            continue
        out.append(
            {
                "root_title": datasets[0]["title"].strip(),
                "grouping": "exact",
                "semantics": _semantics("exact", datasets),
                "datasets": datasets,
            },
        )
    return out


def _date_groups(rows: list[dict], flags: Flags) -> list[dict]:
    """Phase 2: date-suffix clusters."""
    groups: dict[str, dict] = {}
    for r in rows:
        result = strip_date_v2(r["title"].strip(), flags)
        if result and len(result["root"]) >= MIN_ROOT_LENGTH and _keep_root(result["root"], flags):
            key = result["root"].lower()
            if key not in groups:
                groups[key] = {"root": result["root"], "items": []}
            groups[key]["items"].append({**dict(r), "date": result["date"]})
    out = []
    for group in groups.values():
        if len(group["items"]) < MIN_SERIES_SIZE:
            continue
        out.append(
            {
                "root_title": group["root"],
                "grouping": "date",
                "semantics": _semantics("date", group["items"]),
                "datasets": group["items"],
            },
        )
    return out


def build_all_series_v2(rows: list[dict], flags: Flags) -> list[dict]:
    """Same two-phase shape as build_series.build_all_series, with v2
    patterns/trimming and a 4-way semantics split (grouping x meaning)."""
    return _exact_groups(rows, flags) + _date_groups(rows, flags)


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _key(series: dict) -> frozenset:
    """Identity key for a series: its dataset ids (order-independent)."""
    return frozenset(d["id"] for d in series["datasets"])


def _root_key(root: str) -> str:
    """Normalised root identity: case-folded, whitespace collapsed, trailing
    connectors/punct stripped, and any leftover date tail stripped again so a
    range-merged v2 root matches its v1 split twin ("…January 2011 to" vs
    "…month")."""
    r = _ROOT_WS.sub(" ", root.strip().lower())
    r = _trim_tail(r)
    stripped = strip_date_v1(r)
    if stripped:
        r = stripped["root"]
    return r


def _report(title: str) -> None:
    print(f"\n{'─' * 3} {title}")


def _print_table(headers: list[str], rows: list[list]) -> None:
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print(fmt.format(*[str(c) for c in r]))


# ---------------------------------------------------------------------------
# E1 + E2: root quality and type re-derivation
# ---------------------------------------------------------------------------


def _v1_semantics(s: dict) -> str:
    """Map a v1 series type onto the v2 semantics frame for the cross-tab."""
    if s["type"] == "template":
        return "template"
    if any("date" in d for d in s["datasets"]):
        return "hybrid" if len({d["org_slug"] for d in s["datasets"]}) > 1 else "timeseries"
    return "duplicates"


def _totals(base: list[dict], v2: list[dict], flags: Flags) -> None:
    base_sem = Counter(_v1_semantics(s) for s in base)
    v2_sem = Counter(s["semantics"] for s in v2)
    print(f"\ndatasets in series: {len({d['id'] for s in base for d in s['datasets']}):,}")
    _report("E1/E2  detector totals")
    _print_table(
        ["detector", "series", "template", "timeseries", "duplicates", "hybrid"],
        [
            [
                "baseline (v1)",
                len(base),
                base_sem["template"],
                base_sem["timeseries"],
                base_sem["duplicates"],
                base_sem["hybrid"],
            ],
            [
                f"v2 ({_flags_str(flags)})",
                len(v2),
                v2_sem["template"],
                v2_sem["timeseries"],
                v2_sem["duplicates"],
                v2_sem["hybrid"],
            ],
        ],
    )


def _transitions(base: list[dict], v2: list[dict]) -> None:
    base_by_key = {_key(s): s for s in base}
    v2_by_key = {_key(s): s for s in v2}
    transitions = Counter()
    for key, b in base_by_key.items():
        v = v2_by_key.get(key)
        if v is None:
            transitions["dropped"] += 1
        else:
            transitions[(_v1_semantics(b), v["semantics"])] += 1
    for s in v2:
        if _key(s) not in base_by_key:
            transitions["added"] += 1
    _report("E2  v1 -> v2 transitions (by dataset set)")
    kept = {k: n for k, n in transitions.items() if k not in ("dropped", "added")}
    _print_table(
        ["v1 type -> v2 semantics", "series"],
        [[f"{a} -> {b}", n] for (a, b), n in sorted(kept.items(), key=lambda kv: -kv[1])]
        + [["(dropped)", transitions["dropped"]], ["(added)", transitions["added"]]],
    )


def _roots_cleaned(base: list[dict], v2: list[dict]) -> None:
    base_by_key = {_key(s): s for s in base}
    v2_by_key = {_key(s): s for s in v2}
    changed = []
    for key, b in base_by_key.items():
        v = v2_by_key.get(key)
        if v and v["root_title"] != b["root_title"]:
            changed.append((b, v))
    changed.sort(key=lambda pair: -len(pair[0]["datasets"]))
    _report(f"E1  roots cleaned (same dataset set, root changed): {len(changed)}")
    for b, v in changed[:15]:
        print(f"  {b['root_title']!r:70} -> {v['root_title']!r}  ({len(b['datasets'])} datasets)")


def _why_dropped(s: dict, flags: Flags) -> str:
    root = s["root_title"]
    if _FILENAME_RE.search(root):
        return "filename-like"
    if s["type"] != "template" and flags.min_words and len(root.split()) < flags.min_words:
        return "single-word root"
    return "membership split?"


def _dropped_report(base_by_root: dict, v2_by_root: dict, flags: Flags) -> None:
    dropped = [s for rk, blist in base_by_root.items() if rk not in v2_by_root for s in blist]
    dropped.sort(key=lambda s: -len(s["datasets"]))
    reasons = Counter(_why_dropped(s, flags) for s in dropped)
    _report(f"E1  series dropped by v2: {len(dropped)} — {dict(reasons)}")
    for s in dropped[:12]:
        dates = sum(1 for d in s["datasets"] if "date" in d)
        print(
            f"  {s['root_title']!r:70} {len(s['datasets']):>4} datasets, {dates} dated  "
            f"[{s['type']}] ({_why_dropped(s, flags)})",
        )
    filename_drops = [s for s in dropped if _why_dropped(s, flags) == "filename-like"]
    if filename_drops:
        print("  filename-like examples:")
        for s in filename_drops[:6]:
            print(f"    {s['root_title']!r}")


def _merged_report(base_by_root: dict, v2_by_root: dict) -> None:
    merged = []
    for rk, blist in base_by_root.items():
        if rk not in v2_by_root:
            continue
        for b in blist:
            bset = _key(b)
            for v in v2_by_root[rk]:
                vset = _key(v)
                if bset == vset or not (bset & vset):
                    continue
                merged.append((b, v, len(vset - bset), len(bset - vset)))
    merged.sort(key=lambda t: -(t[2] + t[3]))
    _report(f"E1  membership changes (same root family, overlapping sets): {len(merged)}")
    for b, v, added_n, lost_n in merged[:12]:
        label = "root cleaned" if v["root_title"] != b["root_title"] else "membership changed"
        print(
            f"  {b['root_title']!r:70} {len(b['datasets']):>4} -> {len(v['datasets']):<4} "
            f"(+{added_n}/-{lost_n})  [{b['type']} -> {v['grouping']}/{v['semantics']}] {label}",
        )


def _added_residue_report(base_by_root: dict, v2_by_root: dict, v2: list[dict]) -> None:
    added = [s for rk, vlist in v2_by_root.items() if rk not in base_by_root for s in vlist]
    added.sort(key=lambda s: -len(s["datasets"]))
    _report(f"E1  series added by v2: {len(added)} (top by size — new roots?)")
    for s in added[:12]:
        print(f"  {s['root_title']!r:70} {len(s['datasets']):>4} datasets [{s['semantics']}]")

    residue = [s for s in v2 if s["grouping"] == "date" and _RESIDUE_RE.search(s["root_title"])]
    residue.sort(key=lambda s: -len(s["datasets"]))
    _report(f"E1  residue — date roots still ending in a connector (top {min(10, len(residue))})")
    for s in residue[:10]:
        print(f"  {s['root_title']!r:70} {len(s['datasets']):>4} datasets")


def _drop_merge_add(base: list[dict], v2: list[dict], flags: Flags) -> None:
    """Drop/merge/add by normalised root (casefold + trim change the dataset
    set, which a set-based key would read as drop+add)."""
    base_by_root: dict[str, list[dict]] = {}
    for s in base:
        base_by_root.setdefault(_root_key(s["root_title"]), []).append(s)
    v2_by_root: dict[str, list[dict]] = {}
    for s in v2:
        v2_by_root.setdefault(_root_key(s["root_title"]), []).append(s)
    _dropped_report(base_by_root, v2_by_root, flags)
    _merged_report(base_by_root, v2_by_root)
    _added_residue_report(base_by_root, v2_by_root, v2)


def _ablation(rows: list[dict], flags: Flags) -> None:
    v2 = build_all_series_v2([dict(r) for r in rows], flags)
    v2_keys = {_key(s) for s in v2}
    _report("E1  flag ablation (each flag off, everything else on)")
    rows_out = []
    for name, off in [
        ("range_patterns", lambda f: Flags(**{**f.__dict__, "range_patterns": False})),
        ("trim_connectors", lambda f: Flags(**{**f.__dict__, "trim_connectors": False})),
        ("min_words", lambda f: Flags(**{**f.__dict__, "min_words": 0})),
        ("reject_filenames", lambda f: Flags(**{**f.__dict__, "reject_filenames": False})),
        ("casefold_exact", lambda f: Flags(**{**f.__dict__, "casefold_exact": False})),
        ("punct_normalize", lambda f: Flags(**{**f.__dict__, "punct_normalize": False})),
    ]:
        alt = build_all_series_v2([dict(r) for r in rows], off(flags))
        alt_keys = {_key(s) for s in alt}
        rows_out.append([name, len(alt), len(alt_keys - v2_keys), len(v2_keys - alt_keys)])
    _print_table(["flag", "series (flag off)", "added vs v2", "missing vs v2"], rows_out)


def _overlap(v2: list[dict]) -> None:
    memberships = Counter(d["id"] for s in v2 for d in s["datasets"])
    multi = {k: n for k, n in memberships.items() if n > 1}
    _report(f"E3  datasets in >1 v2 series: {len(multi)} of {len(memberships)}")
    title_by_id = {d["id"]: d["title"].strip() for s in v2 for d in s["datasets"]}
    by_title = Counter()
    for id_ in multi:
        by_title[title_by_id.get(id_, id_)] += 1
    for title, n in by_title.most_common(8):
        print(f"  {title!r:70} {n} datasets, each in 2 series")
    pairs = 0
    for id_ in multi:
        series_of = [s for s in v2 if any(d["id"] == id_ for d in s["datasets"])]
        if len({s["grouping"] for s in series_of}) == TWO_GROUPINGS:
            pairs += 1
    print(f"  ({pairs} overlap datasets sit in both an exact group and a date group)")


def _recall_report(base: list[dict], v2: list[dict], db) -> None:
    """E5: with punct_normalize, how many template families grew vs are
    genuinely new, and is the quality of the new families acceptable
    (notes-similarity gate)?"""
    known = {_norm_title(s["root_title"]) for s in base if s["type"] == "template"}
    v2_templates = [s for s in v2 if s["semantics"] == "template"]
    grown = [s for s in v2_templates if _norm_title(s["root_title"]) in known]
    new = [s for s in v2_templates if _norm_title(s["root_title"]) not in known]
    _report(f"E5  recall — template families: baseline {len(known)}, v2 {len(v2_templates)}")
    print(f"  grown (case/punct variants of known families): {len(grown)}")
    print(f"  genuinely new families: {len(new)}")
    if not new:
        return
    grown_by = Counter()
    for s in grown:
        grown_by[_norm_title(s["root_title"])] = len({d["org_slug"] for d in s["datasets"]})
    if grown_by:
        print("  biggest grown families (orgs now matched):")
        for rk, n in grown_by.most_common(5):
            print(f"    {rk!r} — {n} orgs")
    id_to_note = _load_notes(db, new)
    _new_family_quality(new, id_to_note)


def _new_family_quality(new: list[dict], id_to_note: dict) -> None:
    scored = _score_templates(new, id_to_note)
    buckets = Counter()
    for _, kind, share, _ in scored:
        if kind == "no notes":
            buckets["no notes"] += 1
        elif share >= TIGHT_SHARE:
            buckets["tight (>=80% identical notes)"] += 1
        elif share >= MEDIUM_SHARE:
            buckets["medium (50-80%)"] += 1
        else:
            buckets["loose (<50%)"] += 1
    _print_table(["new-family quality", "families"], [[k, v] for k, v in buckets.items()])
    by_share = sorted(scored, key=lambda x: (-x[2], -len(x[0]["datasets"])))
    print("  highest notes-similarity new families:")
    for s, _, share, distinct in by_share[:6]:
        print(
            f"    {s['root_title']!r:70} {len(s['datasets']):>3} ds, {share:.0%} identical notes ({distinct} distinct)",
        )
    print("  lowest notes-similarity new families (eyeball for coincidences):")
    for s, _, share, distinct in by_share[-6:]:
        print(
            f"    {s['root_title']!r:70} {len(s['datasets']):>3} ds, {share:.0%} identical notes ({distinct} distinct)",
        )


def run_detection_experiment(rows: list[dict], flags: Flags, db) -> None:
    base = build_all_series([dict(r) for r in rows])[0]
    v2 = build_all_series_v2([dict(r) for r in rows], flags)
    _totals(base, v2, flags)
    _transitions(base, v2)
    _roots_cleaned(base, v2)
    _drop_merge_add(base, v2, flags)
    _ablation([dict(r) for r in rows], flags)
    _overlap(v2)
    if flags.punct_normalize:
        _recall_report(base, v2, db)


# ---------------------------------------------------------------------------
# E4: template similarity via notes
# ---------------------------------------------------------------------------


def _load_notes(db, templates: list[dict]) -> dict:
    """id -> trimmed notes for every dataset in the template groups."""
    ids = {d["id"] for s in templates for d in s["datasets"]}
    return _load_notes_from_ids(db, ids)


def _score_templates(templates: list[dict], id_to_note: dict) -> list[tuple]:
    """(series, kind, share, distinct) — share = modal notes share among the
    orgs that have notes; kind is 'notes' or 'no notes'."""
    scored = []
    for s in templates:
        notes = [id_to_note[d["id"]] for d in s["datasets"]]
        nonempty = [n for n in notes if n]
        if not nonempty:
            scored.append((s, "no notes", 0.0, 0))
        else:
            share = max(Counter(nonempty).values()) / len(nonempty)
            scored.append((s, "notes", share, len(set(nonempty))))
    return scored


def run_template_similarity(rows: list[dict], flags: Flags, db) -> None:
    """Are exact-duplicate multi-org "template" groups actually identical
    copies? Score each by the max share of datasets sharing one notes text."""
    v2 = build_all_series_v2([dict(r) for r in rows], flags)
    templates = [s for s in v2 if s["semantics"] == "template"]
    _report(f"E4  template similarity (notes) — {len(templates)} template groups")
    id_to_note = _load_notes(db, templates)
    scored = _score_templates(templates, id_to_note)

    buckets = Counter()
    for _, kind, share, _ in scored:
        if kind == "no notes":
            buckets["no notes"] += 1
        elif share >= TIGHT_SHARE:
            buckets["tight (>=80% identical notes)"] += 1
        elif share >= MEDIUM_SHARE:
            buckets["medium (50-80%)"] += 1
        else:
            buckets["loose (<50%)"] += 1
    _print_table(["template-ness", "groups"], [[k, v] for k, v in buckets.items()])

    tight = [x for x in scored if x[1] == "notes" and x[2] >= TIGHT_SHARE]
    tight.sort(key=lambda x: -len(x[0]["datasets"]))
    _report("  tightest (genuine copies, e.g. Organogram-type)")
    for s, _, share, distinct in tight[:6]:
        print(
            f"  {s['root_title']!r:70} {len(s['datasets']):>4} datasets, {share:.0%} identical "
            f"notes ({distinct} distinct)",
        )

    loose = [x for x in scored if x[1] == "notes" and x[2] < MEDIUM_SHARE]
    loose.sort(key=lambda x: -len(x[0]["datasets"]))
    _report("  loosest (title collisions, e.g. Allotments-type)")
    for s, _, share, distinct in loose[:6]:
        print(
            f"  {s['root_title']!r:70} {len(s['datasets']):>4} datasets, {share:.0%} identical "
            f"notes ({distinct} distinct)",
        )


# ---------------------------------------------------------------------------
# E6: seed-and-grow — use decent series as anchors to find residual datasets
# ---------------------------------------------------------------------------

_SEED_MIN_TEMPLATE_ORGS = 3
_SEED_MIN_TIMESERIES = 4
MIN_ROOT_WORDS = 2
_MAX_AMBIGUOUS_EXAMPLES = 5
_YEAR_TOKEN = re.compile(r"(?:19|20)\d{2}")


def _is_decent_seed(s: dict) -> bool:
    """A series worth growing from: a real template (>=3 orgs) or a
    multi-period timeseries (>=4 datasets) with a 2+ word root."""
    if len(_norm_title(s["root_title"]).split()) < MIN_ROOT_WORDS:
        return False
    if s["semantics"] == "template":
        return len({d["org_slug"] for d in s["datasets"]}) >= _SEED_MIN_TEMPLATE_ORGS
    if s["semantics"] == "timeseries":
        return len(s["datasets"]) >= _SEED_MIN_TIMESERIES
    return False


def _title_hit(mode: str, root: str, t: str) -> bool:
    """Whether normalised title t matches root by the mode's rule."""
    if mode == "prefix":
        return t.startswith(root) and t != root
    if mode == "suffix":
        return t.endswith(root) and t != root
    return re.search(rf"\b{re.escape(root)}\b", t) is not None and t != root


def _grow_pairs(residual: list[tuple], v2: list[dict], mode: str) -> list[tuple]:
    """(seed, member) pairs for unassigned datasets whose normalised title
    starts with / ends with / contains the seed root. Timeseries seeds
    additionally require a year token in the candidate title.

    residual is [(row, normalised title)]; candidates are pre-indexed by
    token so each seed only scans rows sharing its first (or last, for
    suffix) token instead of the whole pool."""
    by_token: dict[str, list[tuple]] = defaultdict(list)
    for r, t in residual:
        toks = t.split()
        if mode == "suffix":
            by_token[toks[-1]].append((r, t))
        else:
            for tok in set(toks):
                by_token[tok].append((r, t))
    pairs: list[tuple] = []
    for s in v2:
        if not _is_decent_seed(s):
            continue
        root = _norm_title(s["root_title"])
        root_toks = root.split()
        need_year = s["semantics"] == "timeseries"
        anchor = root_toks[-1] if mode == "suffix" else root_toks[0]
        for r, t in by_token.get(anchor, []):
            hit = _title_hit(mode, root, t)
            if hit and need_year and not _YEAR_TOKEN.search(t):
                hit = False
            if hit:
                pairs.append((s, r))
    return pairs


def _notes_fit(pairs: list[tuple], id_to_note: dict) -> list[tuple]:
    """For each (seed, member) pair, whether the member's notes match the
    seed's modal notes (only meaningful for seeds with a dominant note).
    Returns (seed, member, fit|None)."""
    out = []
    by_seed: dict[int, list] = {}
    for s, m in pairs:
        by_seed.setdefault(id(s), []).append((s, m))
    for spairs in by_seed.values():
        seed_notes = [id_to_note.get(d["id"], "") for d in spairs[0][0]["datasets"]]
        nonempty = [n for n in seed_notes if n]
        if not nonempty:
            for s, m in spairs:
                out.append((s, m, None))
            continue
        modal = Counter(nonempty).most_common(1)[0][0]
        for s, m in spairs:
            out.append((s, m, id_to_note.get(m["id"], "") == modal))
    return out


def run_seed_grow(rows: list[dict], flags: Flags, db) -> None:
    """E6: grow decent series from residual (unassigned) datasets."""
    v2 = build_all_series_v2([dict(r) for r in rows], flags)
    seeds = [s for s in v2 if _is_decent_seed(s)]
    in_series = {d["id"] for s in v2 for d in s["datasets"]}
    residual = [r for r in rows if r["id"] not in in_series]
    _report(
        f"E6  seed-and-grow — seeds: {len(seeds)}"
        f" (templates>=3orgs, timeseries>=4ds), residual pool: {len(residual):,}",
    )

    residual_norm = [(r, _norm_title(r["title"])) for r in residual]
    rows_out = []
    for mode in ("prefix", "suffix", "contains"):
        pairs = _grow_pairs(residual_norm, v2, mode)
        members = {m["id"] for _, m in pairs}
        orgs = {m["org_slug"] for _, m in pairs}
        rows_out.append([mode, len(pairs), len(members), len(orgs)])
    _print_table(["mode", "matches", "unique members", "new orgs"], rows_out)

    # detail on the loosest mode (contains) with notes fit for tight seeds
    pairs = _grow_pairs(residual_norm, v2, "contains")
    if pairs:
        _grow_detail(db, pairs)


def _grow_detail(db, pairs: list[tuple]) -> None:
    """Notes-fit gate, sample grown members, and ambiguity check."""
    all_ids = set()
    for s, m in pairs:
        all_ids.update(d["id"] for d in s["datasets"])
        all_ids.add(m["id"])
    id_to_note = _load_notes_from_ids(db, all_ids)
    _notes_fit_report(_notes_fit(pairs, id_to_note))
    _grow_examples(pairs)
    _grow_ambiguity(pairs)


def _notes_fit_report(fitted: list[tuple]) -> None:
    with_fit = [x for x in fitted if x[2] is not None]
    if with_fit:
        yes = sum(1 for _, _, f in with_fit if f)
        print(
            f"  notes fit (grown member matches seed modal note, tight seeds only):"
            f" {yes}/{len(with_fit)} ({yes / len(with_fit):.0%})",
        )


def _grow_examples(pairs: list[tuple]) -> None:
    seen = set()
    examples = []
    for s, m in pairs:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        examples.append((s["root_title"], s["semantics"], m["title"]))
    examples.sort(key=lambda x: -len(x[0]))
    _report(f"E6  sample grown members ({len(examples)} unique, top by seed-root length)")
    for root, sem, title in examples[:15]:
        print(f"  [{sem[:4]}] {root!r:55} <- {title!r}")


def _grow_ambiguity(pairs: list[tuple]) -> None:
    member_seeds = Counter()
    for _, m in pairs:
        member_seeds[m["id"]] += 1
    ambiguous = [m for m in member_seeds if member_seeds[m] > 1]
    if ambiguous:
        print(f"  {len(ambiguous)} members matched more than one seed (ambiguous):")
        shown = set()
        for _, m in pairs:
            if m["id"] in ambiguous and m["id"] not in shown:
                shown.add(m["id"])
                if len(shown) <= _MAX_AMBIGUOUS_EXAMPLES:
                    print(f"    {m['title'][:70]!r}")


def _load_notes_from_ids(db, ids: set) -> dict:
    """id -> trimmed notes for an arbitrary set of dataset ids."""
    id_to_note: dict = {}
    id_list = list(ids)
    for i in range(0, len(id_list), 500):
        chunk = id_list[i : i + 500]
        placeholders = ",".join(["%s"] * len(chunk))
        for row in db.prepare(f"SELECT id, notes FROM datasets WHERE id IN ({placeholders})").all(*chunk):
            id_to_note[row["id"]] = (row["notes"] or "").strip()
    return id_to_note


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _flags_str(flags: Flags) -> str:
    parts = []
    if flags.range_patterns:
        parts.append("ranges")
    if flags.trim_connectors:
        parts.append("trim")
    if flags.min_words:
        parts.append(f"min_words={flags.min_words}")
    if flags.reject_filenames:
        parts.append("no_filenames")
    if flags.casefold_exact:
        parts.append("casefold")
    if flags.punct_normalize:
        parts.append("punct_norm")
    return ",".join(parts) or "none"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=0, help="limit dataset rows (0 = all)")
    ap.add_argument(
        "--flags",
        default="",
        help="comma list of flags to turn OFF: "
        "range_patterns,trim_connectors,min_words,reject_filenames,casefold_exact",
    )
    ap.add_argument("--no-notes", action="store_true", help="skip E4 (notes query)")
    ap.add_argument("--no-grow", action="store_true", help="skip E6 (seed-and-grow)")
    args = ap.parse_args()

    flags = Flags()
    allowed = {
        "range_patterns",
        "trim_connectors",
        "min_words",
        "reject_filenames",
        "casefold_exact",
        "punct_normalize",
    }
    for raw in args.flags.split(","):
        flag = raw.strip()
        if not flag:
            continue
        if flag not in allowed:
            raise SystemExit(f"unknown flag: {flag} (allowed: {', '.join(sorted(allowed))})")
        setattr(flags, flag, False)  # listed flags are OFF

    print(f"Experiment: series detection v2 (flags: {_flags_str(flags)})")
    db = connect(database_url())
    try:
        limit = f" LIMIT {args.sample}" if args.sample else ""
        rows = db.prepare(
            "SELECT id, title, org_slug, org_display_name FROM datasets"
            " WHERE title IS NOT NULL AND title != ''" + limit,
        ).all()
        rows = [dict(r) for r in rows]
        run_detection_experiment(rows, flags, db)
        if not args.no_notes:
            run_template_similarity(rows, flags, db)
        if not args.no_grow:
            run_seed_grow(rows, flags, db)
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
