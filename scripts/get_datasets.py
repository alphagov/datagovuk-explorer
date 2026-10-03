#!/usr/bin/env python3
"""Get all datasets from data.gov.uk and save each to
downloads/datasets/<org-name>/<slug>-<id8>.json.

Walks organisations.json and fetches every dataset for each org.

Usage: python scripts/get_datasets.py [--org <slug>]
"""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer

from scripts.ckan import BASE_URL, MAX_RPS, create_rate_limiter

app = typer.Typer(add_completion=False)
MAX_ROWS_PER_CALL = 1000
OUTPUT_DIR = "downloads/datasets"
ORGS_FILE = Path("downloads/organisations/organisations.json")
SORT = "metadata_created desc"


class OrgNotFoundError(RuntimeError):
    def __init__(self, slug: str):
        super().__init__(f'Publisher not found: "{slug}"')
        self.hint = "Check organisations.json or run get-organisations.py."


def iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def slugify(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"^-+|-+$", "", s)
    return s[:80]


def fetch_datasets(rate_limit, client: httpx.Client, org_name: str) -> list[dict]:
    """Fetch all datasets for one org, page by page until exhausted."""
    results: list[dict] = []
    offset = 0
    while True:
        rate_limit()
        params = {
            "q": "",
            "fq": f"organization:{org_name}",
            "rows": str(MAX_ROWS_PER_CALL),
            "start": str(offset),
            "sort": SORT,
        }
        res = client.get(f"{BASE_URL}/package_search", params=params)
        if not res.is_success:
            raise RuntimeError(f"HTTP {res.status_code}: {res.reason_phrase}")
        body = res.json()
        if not body.get("success"):
            raise RuntimeError("CKAN API returned success: false")
        page = body["result"]["results"]
        results.extend(page)
        offset += len(page)
        if len(page) < MAX_ROWS_PER_CALL:
            break
    return results


def process_org(
    org: dict,
    index: int,
    total: int,
    rate_limit,
    client: httpx.Client,
) -> int:
    """Fetch and save one org's datasets. Returns count saved."""
    org_name = org["name"]
    display = org.get("display_name") or org_name
    dir_path = Path(OUTPUT_DIR) / org_name

    print(f"[{index + 1}/{total}] {display} ({org_name})")

    try:
        if dir_path.is_dir():
            for stale in dir_path.glob("*.json"):
                stale.unlink()

        datasets = fetch_datasets(rate_limit, client, org_name)

        if not datasets:
            print("  → no datasets found")
            dir_path.mkdir(parents=True, exist_ok=True)
            (dir_path / "no-datasets.json").write_text("[]", encoding="utf-8")
            return 0

        dir_path.mkdir(parents=True, exist_ok=True)
        saved = 0
        for ds in datasets:
            filename = f"{slugify(ds['title'])}-{ds['id'][:8]}.json"
            org_ctx: dict = {"name": org_name}
            if "display_name" in org:
                org_ctx["display_name"] = org["display_name"]
            record = {"_fetched_at": iso_now(), "_organisation": org_ctx, **ds}
            (dir_path / filename).write_text(
                json.dumps(record, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            saved += 1

        print(f"  → saved {saved} datasets")

    except (httpx.HTTPError, RuntimeError, ValueError, OSError) as e:
        print(f"  ✗ error: {e}", file=sys.stderr)
        return 0
    else:
        return saved


@app.command()
def main(
    *,
    org: Annotated[str | None, typer.Option(help="Process a single organisation only")] = None,
) -> None:
    """Fetch all datasets from data.gov.uk into downloads/datasets/<org>/<slug>-<id8>.json."""
    try:
        with Path(ORGS_FILE).open(encoding="utf-8") as f:
            orgs = {o["name"]: o for o in json.load(f)}
    except FileNotFoundError:
        print("No organisations.json found. Run get-organisations first.", file=sys.stderr)
        raise typer.Exit(1) from None

    if org:
        try:
            orgs = {org: orgs[org]}
        except KeyError:
            print(f'Publisher not found: "{org}"', file=sys.stderr)
            print("Check organisations.json or run get-organisations.py.", file=sys.stderr)
            raise typer.Exit(1) from None

    if not orgs:
        print("No organisations found.")
        return

    print(f"Fetching {len(orgs)} organisation(s)...\n")

    rate_limit = create_rate_limiter(MAX_RPS)
    total_saved = 0

    with httpx.Client(follow_redirects=True, timeout=30) as client:
        for i, organisation in enumerate(orgs.values()):
            total_saved += process_org(organisation, i, len(orgs), rate_limit, client)

    print(f"\nDone. {total_saved} datasets saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    app()
