"""Home-dashboard card data for GET / — the summary cards grouped by kind.

The dashboard is a pure aggregation page: totals from the domain tables
(datasets / links / organisations) plus one count per data-quality report
(REPORTS from queries/reports). All of that assembly lives here, so the
view (views/dashboard.py) is a thin render of dashboard.html.

cards() is memoised (functools.cache): the first request per process runs
all ~17 independent single-SELECT fetches concurrently via
core.fetch_parallel (each on a pool thread with its own connection, closed
after the call); later requests serve the result from memory. The DB is a
build-time snapshot, so restart the process to refresh after a rebuild.
"""

import functools
import re

from explorer.queries.core import fetch_parallel
from explorer.queries.datasets import DATASET_TOTAL, DATASETS_NO_LINKS_COUNT, THEME_COUNTS
from explorer.queries.link_errors import link_errors_stats
from explorer.queries.links import LINKS_STATS
from explorer.queries.organisations import LAST_PUBLISHED_BY_ORG, ORGS
from explorer.queries.reports import REPORTS, report_dashboard_count

# Active-org card — how many most-recent publication years count as "active".
ACTIVE_YEAR_COUNT = 2


def _active_card(org_rows: list, last_pub_rows: list) -> dict:
    """'Publishers have active since …' card — pure, no DB.

    org_rows: ORGS.all() rows; last_pub_rows: LAST_PUBLISHED_BY_ORG.all()
    rows. Callers fetch both once (see cards()).
    """
    last_pub = {r["org_slug"]: r["last_published"] for r in last_pub_rows}
    years = sorted(
        {d[:4] for d in last_pub.values() if re.fullmatch(r"\d{4}", d[:4])},
        reverse=True,
    )
    active_years = years[:ACTIVE_YEAR_COUNT]
    active_set = set(active_years)
    since = str(int(active_years[1]) - 1) if len(active_years) >= ACTIVE_YEAR_COUNT else None
    count = sum(1 for o in org_rows if (last_pub.get(o["slug"]) or "")[:4] in active_set)

    return {
        "key": "orgs-active",
        "label": (f"Publishers active since {since}" if since else "Publishers have published recently"),
        "count": count,
        "link": (f"/organisations?last_published_year={','.join(active_years)}" if active_years else "/organisations"),
    }


@functools.cache
def cards() -> dict:
    """Everything dashboard.html needs: totals, cards (keyed by report key /
    card key), per-kind has-items flags, and the grand total.

    Cards come in two shapes:
    - one per report, counting via queries/reports' report_dashboard_count
      (normally the report's own unfiltered count; see that function's
      docstring for the one exception);
    - hand-built cards (orgs-active, orgs-no-datasets, datasets-no-theme)
      from the totals queries.

    All ~17 fetches — the three totals, the org rows for the hand-built
    cards, and one count per report — are independent single-SELECT
    aggregates, so they run concurrently via core.fetch_parallel and the
    results come back in the same order as the task list.

    Memoised: computed once per process on first request; later requests
    serve the cached result (rebuild/restart contract in the module docstring).
    """
    # report_dashboard_count is normally the same as the report's own
    # unfiltered count; datasets-duplicate-content groups its own list by
    # content hash (for pagination), so its card needs a different query —
    # see dashboard_count_sql in queries/reports.py. Capture key per
    # iteration — otherwise every lambda closes over the last report's key.
    report_count_fns: list = [(lambda key=report["key"]: report_dashboard_count(key)) for report in REPORTS]

    org_rows, last_pub_rows, total_datasets_row, links_stats, theme_count_rows, no_links_count_row, broken_links_row, *report_counts = fetch_parallel(
        [
            ORGS.all,
            LAST_PUBLISHED_BY_ORG.all,
            DATASET_TOTAL.get,
            LINKS_STATS.get,
            THEME_COUNTS.all,
            DATASETS_NO_LINKS_COUNT.get,
            link_errors_stats,
            *report_count_fns,
        ],
    )

    total_datasets = total_datasets_row["n"]
    total_orgs = len(org_rows)
    total_links = links_stats["total"]
    totals = {"orgs": total_orgs, "datasets": total_datasets, "links": total_links}

    cards = {}
    for report, count in zip(REPORTS, report_counts, strict=True):
        # A report's kind normally doubles as its totals bucket (orgs /
        # datasets / links). Reports whose kind is a display-only value name
        # their bucket explicitly with percent_of (datasets-duplicate-content).
        # duplicate-urls names neither → percent is None.
        bucket = report.get("percent_of", report["kind"])
        cards[report["key"]] = {
            # dashboard_label when the card's metric isn't the page's unit
            # (see dashboard_count_sql in queries/reports.py).
            "label": report.get("dashboard_label", report["label"]),
            "count": count,
            "percent": ((count / totals[bucket] * 100) if totals.get(bucket) else None),
            "href": f"/report/{report['key']}",
        }

    # orgs-active card
    active = _active_card(org_rows, last_pub_rows)
    cards[active["key"]] = {
        "label": active["label"],
        "count": active["count"],
        "percent": (active["count"] / totals["orgs"] * 100) if totals["orgs"] else None,
        "href": active["link"],
    }

    # orgs-no-datasets card
    no_datasets_count = sum(1 for o in org_rows if (o["package_count"] or 0) == 0)
    cards["orgs-no-datasets"] = {
        "label": "Publishers with no datasets",
        "count": no_datasets_count,
        "percent": ((no_datasets_count / totals["orgs"] * 100) if totals["orgs"] else None),
        "href": "/organisations?datasets=0",
    }

    # datasets-no-links card
    no_links_count = no_links_count_row["n"]
    cards["datasets-no-links"] = {
        "label": "Datasets with no links",
        "count": no_links_count,
        "percent": (no_links_count / totals["datasets"] * 100) if totals["datasets"] else None,
        "href": "/datasets?links=0",
    }

    # links-no-url card
    no_url_count = links_stats.get("no_url") or 0
    cards["links-no-url"] = {
        "label": "Links with no URL",
        "count": no_url_count,
        "percent": (no_url_count / totals["links"] * 100) if totals["links"] else None,
        "href": "/links/status?domain=__none__",
    }

    # links-no-format card
    no_format_count = links_stats.get("no_format") or 0
    cards["links-no-format"] = {
        "label": "Links with no format",
        "count": no_format_count,
        "percent": (no_format_count / totals["links"] * 100) if totals["links"] else None,
        "href": "/links?format=__none__",
    }

    # links-broken card
    broken_count = broken_links_row.get("errors") or 0
    cards["links-broken"] = {
        "label": "Broken links",
        "count": broken_count,
        "percent": (broken_count / totals["links"] * 100) if totals["links"] else None,
        "href": "/links/status?status=error",
    }

    # datasets-no-theme card
    no_theme_count = next(
        (r["count"] for r in theme_count_rows if r["theme"] == "__none__"),
        0,
    )
    cards["datasets-no-theme"] = {
        "label": "Datasets with no theme",
        "count": no_theme_count,
        "percent": ((no_theme_count / totals["datasets"] * 100) if totals["datasets"] else None),
        "href": "/datasets?theme=none",
    }

    # Per-kind card ordering for the has-items flags (dashboard.html renders
    # its own hard-coded card order per group).
    group_keys: dict[str, list[str]] = {}
    for report in REPORTS:
        group_keys.setdefault(report["kind"], []).append(report["key"])
    group_keys.setdefault("orgs", []).extend([active["key"], "orgs-no-datasets"])
    group_keys.setdefault("datasets", []).extend(["datasets-no-links", "datasets-no-theme"])
    group_keys.setdefault("links", []).extend(["links-no-url", "links-no-format", "links-broken"])
    group_has_items = {kind: any(cards[key]["count"] > 0 for key in keys) for kind, keys in group_keys.items()}

    return {
        "totals": totals,
        "cards": cards,
        "group_has_items": group_has_items,
        "dashboard_total": sum(c["count"] for c in cards.values()),
    }
