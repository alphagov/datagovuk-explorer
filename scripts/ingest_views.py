"""Reload dataset view counts from the GA/Search Console CSVs.

Combines GA page views, GA Google landing sessions, and Search Console
clicks into a single per-dataset view count, then writes it to the
datasets.views column.

Idempotent: resets all views to 0 before loading. Re-running is always safe.

Usage: python -m scripts.ingest_views
"""

import csv
import itertools
import re
from functools import partial
from pathlib import Path

from scripts.db import connect, database_url

DATABASE_URL = database_url()

_DATA = Path(__file__).resolve().parent.parent / "data"
VIEWS_FILE = _DATA / "console-clicks-apr-aug.csv"
GA_PAGE_VIEWS_FILE = _DATA / "ga-views-apr-aug.csv"
GA_GOOGLE_LANDING_FILE = _DATA / "ga-google-landing-apr-aug.csv"

# Floor for the per-page consent rate (ga_landing / sc_clicks), used when
# scaling up the non-Google view component. Ratios below this are treated as
# sampling noise (a handful of opted-in landings against many Search Console
# clicks) and would otherwise inflate views without bound (up to ~230x on the
# Apr-Aug data). ~0.10 is the corpus-wide pooled rate; see
# docs/ga-opt-in-analysis.md. Kept in sync with scripts/ingest_collections.py.
CONSENT_RATE_FLOOR = 0.10

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_VIEWS_URL_RE = re.compile(rf"https://www\.data\.gov\.uk/dataset/({_UUID})")
_GA_PATH_RE = re.compile(rf"/dataset/({_UUID})")


def _read_ga_csv(path: Path, url_col: str, value_col: str) -> dict[str, int]:
    """Read a GA-exported CSV, skip comment lines and the grand-total row,
    extract dataset UUIDs from relative paths, and sum values per UUID."""
    if not path.exists():
        return {}
    result: dict[str, int] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                break
        reader = csv.DictReader(itertools.chain([line], f))
        for row in reader:
            raw_path = row[url_col]
            if not raw_path:
                continue
            m = _GA_PATH_RE.search(raw_path)
            if not m:
                continue
            val = int(row[value_col])
            if val <= 0:
                continue
            uid = m.group(1)
            result[uid] = result.get(uid, 0) + val
    return result


def _read_search_console_csv() -> dict[str, int]:
    """Read Search Console clicks (full URLs) and return {uuid: clicks}."""
    if not VIEWS_FILE.exists():
        return {}
    result: dict[str, int] = {}
    with VIEWS_FILE.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            m = _VIEWS_URL_RE.match(row["Landing Page"])
            if not m:
                continue
            clicks = int(row["Url Clicks"])
            if clicks <= 0:
                continue
            uid = m.group(1)
            result[uid] = result.get(uid, 0) + clicks
    return result


def load_views_csv() -> dict[str, int]:
    """Combine GA page views, GA Google landing sessions, and Search Console
    clicks into a single {dataset_uuid: view_count} dict.

    For pages in the GA-landing / SC-clicks overlap, the per-page consent
    rate (ga_landing / sc_clicks), floored at CONSENT_RATE_FLOOR, scales up
    the non-Google GA component. Pages outside the overlap use the simple
    formula.
    """
    ga_views = _read_ga_csv(GA_PAGE_VIEWS_FILE, "Page path and screen class", "Views")
    ga_landing = _read_ga_csv(GA_GOOGLE_LANDING_FILE, "Landing page", "Sessions")
    sc_clicks = _read_search_console_csv()

    all_uuids = ga_views.keys() | ga_landing.keys() | sc_clicks.keys()
    result: dict[str, int] = {}
    for uid in all_uuids:
        gv = ga_views.get(uid, 0)
        gl = ga_landing.get(uid, 0)
        sc = sc_clicks.get(uid, 0)

        if gl > 0 and sc > 0:
            consent_rate = max(min(gl / sc, 1.0), CONSENT_RATE_FLOOR)
            non_google = gv - gl
            total = round(non_google / consent_rate) + sc if non_google > 0 else sc
        else:
            total = gv - gl + sc

        if total > 0:
            result[uid] = total
    return result


def _write_views_tx(tx, views_by_id) -> None:
    """Write the per-dataset view counts."""
    update_views = tx.prepare("UPDATE datasets SET views = ? WHERE ckan_id = ?")
    for ckan_id, v in views_by_id.items():
        update_views.run(v, ckan_id)


def main() -> None:
    """Reload dataset view counts from the views CSVs.

    Resets all views to 0, then loads GA page views, GA Google landing
    sessions, and Search Console clicks — runs in seconds against the
    existing datasets table, no full rebuild needed."""

    db = connect(DATABASE_URL)
    try:
        db.exec("UPDATE datasets SET views = 0")
        views_by_id = load_views_csv()
        if views_by_id:
            db.transaction(partial(_write_views_tx, views_by_id=views_by_id))
        print(f"ingest_views: {len(views_by_id)} datasets updated")
    finally:
        db.close()


if __name__ == "__main__":
    main()
