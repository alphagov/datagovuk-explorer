#!/usr/bin/env python3
"""Get harvest sources from data.gov.uk (CKAN API) — incrementally.

The unfiltered harvest_source_list endpoint caps at 100 sources, but it
accepts an organization_id filter, so this script walks organisations and
fetches their harvest sources per-org. It writes a deduped, cached union to
downloads/organisations/harvest_sources.json:

    {
      "orgs": {
        "<org-uuid>": [ ...harvest source records... ]
      }
    }

"orgs" maps every org we have checked to its harvest sources (an empty list
when it has none), so a later run can tell a brand new org (not listed) from
one we already looked at. Records are carried forward between runs; only the
checked orgs' entries are replaced, so a deletion at a checked org is picked
up.

Harvest sources change rarely, so a normal run only checks:

- new orgs (no entry in "orgs") — including orgs created since the last run;
- orgs active in the last --active-days: a dataset modified recently (their
  latest dataset `metadata_modified` in the current DB), so a publisher that
  is still working may have added a source.

Everything else carries its cached records forward. `--full` re-walks every
org and rewrites the whole cache; if the DB isn't reachable the script falls
back to a full walk automatically. Together this drops a routine run from
~1,040 calls to a handful; after a full run the cache is complete.

Each record is tagged with the organization_id it was fetched under,
because the API's own publisher_id/publisher_title fields are often empty.

Rate limit: 4 requests per second (scripts/ckan.py).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
import psycopg

from scripts.ckan import BASE_URL, MAX_RPS, create_rate_limiter, write_json
from scripts.db import connect

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

DOWNLOADS_DIR = Path(__file__).resolve().parent.parent / "downloads/organisations"

# Orgs with a dataset modified within this many days are re-checked.
DEFAULT_ACTIVE_DAYS = 30

# Org slugs with any dataset modified in the window (relative to now()).
ACTIVE_ORG_SLUGS_SQL = """
SELECT DISTINCT org_slug
  FROM datasets
 WHERE metadata_modified >= now() - make_interval(days => ?)
"""


def load_organisations() -> list[dict]:
    """Read the already-downloaded organisations.json."""
    path = DOWNLOADS_DIR / "organisations.json"
    if not path.exists():
        raise RuntimeError(
            f"{path} not found — run `just get-organisations` first",
        )
    return json.loads(path.read_text(encoding="utf-8"))


def load_organisation_ids() -> list[str]:
    """Org IDs from organisations.json (callers that only need the ids)."""
    return [org["id"] for org in load_organisations()]


def load_cached() -> dict[str, list[dict]]:
    """Read the cached harvest_sources.json: org id -> its sources."""
    path = DOWNLOADS_DIR / "harvest_sources.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["orgs"]


def active_org_slugs(active_days: int, url: str | None = None) -> set[str] | None:
    """Org slugs with a dataset modified in the last `active_days` (from the
    current DB). None when the DB isn't available or holds no datasets — the
    caller then walks every org rather than risk skipping a live one."""
    url = url or os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set — fetching every organisation", file=sys.stderr)
        return None
    try:
        db = connect(url)
    except psycopg.OperationalError as e:
        print(f"Could not connect to the DB ({e}) — fetching every organisation", file=sys.stderr)
        return None
    try:
        # An empty datasets table means a migrated-but-never-built DB: treat
        # it as unavailable so we walk everything. An empty *activity* result
        # on a populated DB is a genuine "nothing changed" and stays empty.
        total = db.prepare("SELECT COUNT(*) AS n FROM datasets").get()["n"]
        if not total:
            print("Datasets table is empty — fetching every organisation", file=sys.stderr)
            return None
        rows = db.prepare(ACTIVE_ORG_SLUGS_SQL).all(active_days)
    except psycopg.Error as e:
        print(f"Could not read org activity ({e}) — fetching every organisation", file=sys.stderr)
        return None
    finally:
        db.close()
    return {row["org_slug"] for row in rows}


def select_org_ids(
    orgs: list[dict],
    checked: set[str],
    *,
    active_days: int,
    full: bool = False,
) -> list[str]:
    """The org IDs to fetch, in organisations.json order.

    New orgs (not in `checked`) and orgs active in the last `active_days`.
    `full` (or an unavailable DB) returns every org."""
    if full:
        return [org["id"] for org in orgs]

    active_slugs = active_org_slugs(active_days)
    if active_slugs is None:
        return [org["id"] for org in orgs]

    return [org["id"] for org in orgs if org["id"] not in checked or org.get("name") in active_slugs]


def merge_sources(
    cached: dict[str, list[dict]],
    fetched: list[dict],
    checked_ids: set[str],
    current_ids: set[str],
) -> dict[str, list[dict]]:
    """Per-org cache after a run.

    Checked orgs take their fresh records (possibly empty, so deletions
    stick); unchecked orgs carry their cached records forward. Orgs no longer
    in organisations.json are dropped."""
    fetched_by_org: dict[str, list[dict]] = {org_id: [] for org_id in checked_ids}
    for source in fetched:
        fetched_by_org.setdefault(source["organization_id"], []).append(source)

    keep = (set(cached) | checked_ids) & current_ids
    merged: dict[str, list[dict]] = {}
    for org_id in sorted(keep):
        if org_id in checked_ids:
            merged[org_id] = sorted(fetched_by_org.get(org_id, []), key=lambda s: s["id"])
        else:
            merged[org_id] = cached[org_id]
    return merged


def get_harvest_sources(
    client: httpx.Client,
    rate_limit,
    org_ids: list[str],
) -> list[dict]:
    """Fetch harvest sources per organisation and return the combined list."""

    sources: dict[str, dict] = {}
    for i, org_id in enumerate(org_ids, 1):
        # The API intermittently spikes to ~30s or returns 5xx on an
        # individual org (tiny response, server-side flakiness), so a single
        # bad call must not abort the whole walk. Retry a few times.
        res = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            rate_limit()
            reason = None
            try:
                candidate = client.get(
                    f"{BASE_URL}/harvest_source_list",
                    params={"organization_id": org_id},
                )
                if candidate.status_code not in RETRY_STATUS_CODES:
                    res = candidate
                    break
                reason = f"HTTP {candidate.status_code}"
            except httpx.TransportError as e:
                reason = f"{type(e).__name__}: {e}"

            if attempt == MAX_ATTEMPTS:
                raise httpx.HTTPError(f"{reason} fetching org {org_id}")
            print(
                f"  retry {attempt}/{MAX_ATTEMPTS - 1} for org {org_id}: {reason}",
                file=sys.stderr,
            )
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

        if not res.is_success:
            raise RuntimeError(
                f"HTTP {res.status_code} fetching org {org_id}: {res.reason_phrase}",
            )
        body = res.json()
        if not body.get("success"):
            raise RuntimeError(f"CKAN API returned success: false for org {org_id}")

        for item in body.get("result", []):
            source = dict(item)
            source["organization_id"] = org_id
            sources[source["id"]] = source

        if i % 100 == 0 or i == len(org_ids):
            print(
                f"  harvest sources {len(sources)} (orgs {i}/{len(org_ids)})",
                file=sys.stderr,
            )

    return list(sources.values())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch harvest sources from data.gov.uk.")
    parser.add_argument(
        "--active-days",
        type=int,
        default=DEFAULT_ACTIVE_DAYS,
        help=f"re-check orgs with a dataset modified in this many days (default: {DEFAULT_ACTIVE_DAYS})",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="fetch every organisation and rewrite the cache",
    )
    return parser.parse_args(argv)


def main(
    active_days: int = DEFAULT_ACTIVE_DAYS,
    *,
    full: bool = False,
) -> None:
    print("Fetching harvest sources from data.gov.uk...\n")
    try:
        orgs = load_organisations()
        cached = load_cached()
        cache_orgs = set(cached)
        current_ids = {org["id"] for org in orgs}

        new_ids = current_ids - cache_orgs
        org_ids = select_org_ids(orgs, cache_orgs, active_days=active_days, full=full)
        selected = set(org_ids)
        carried = (cache_orgs - selected) & current_ids
        dropped = cache_orgs - current_ids
        print(
            f"Loaded {len(orgs)} organisations; checking {len(org_ids)} "
            f"({len(new_ids)} new, {len(selected - new_ids)} active within {active_days}d), "
            f"carrying {len(carried)} forward, dropping {len(dropped)} gone",
            file=sys.stderr,
        )

        with httpx.Client(follow_redirects=True, timeout=60) as client:
            rate_limit = create_rate_limiter(MAX_RPS)
            fetched = get_harvest_sources(client, rate_limit, org_ids)

        merged = merge_sources(cached, fetched, selected, current_ids)

        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = DOWNLOADS_DIR / "harvest_sources.json"
        write_json({"orgs": merged}, out_path)
        total = sum(len(sources) for sources in merged.values())
        with_sources = sum(1 for sources in merged.values() if sources)
        print(
            f"Wrote {total} harvest sources across {len(merged)} orgs "
            f"({with_sources} with sources, fetched {len(fetched)} this run) to {out_path}",
            file=sys.stderr,
        )
    except (httpx.HTTPError, RuntimeError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    args = _parse_args()
    main(active_days=args.active_days, full=args.full)
