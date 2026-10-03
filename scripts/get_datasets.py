#!/usr/bin/env python3
"""Get all datasets from data.gov.uk and save each to
downloads/datasets/<org-name>/<slug>-<id8>.json.

Walks organisations.json and fetches every dataset for each org not yet
saved. Orgs returning zero datasets are recorded in no-datasets.json and
skipped on subsequent runs. Interrupting is safe — run again to resume.

Usage: python scripts/get_datasets.py [options]

Options:
  --org <slug>  Process a single specific organisation only
  --force       Refetch and overwrite orgs/datasets already saved
  --help, -h    Show this help
"""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

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


def has_saved_datasets(org_name: str) -> bool:
    d = Path(OUTPUT_DIR) / org_name
    return d.is_dir() and any(p.suffix == ".json" for p in d.iterdir())


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


def select_orgs(
    orgs: list[dict],
    org_slug: str | None,
    *,
    force: bool,
) -> list[dict]:
    """Choose which orgs to process."""
    if org_slug:
        org = next((o for o in orgs if o["name"] == org_slug), None)
        if org is None:
            raise OrgNotFoundError(org_slug)
        return [org]
    if force:
        return list(orgs)
    return [o for o in orgs if not has_saved_datasets(o["name"])]


def process_org(
    org: dict,
    index: int,
    total: int,
    rate_limit,
    client: httpx.Client,
    *,
    force: bool,
) -> int:
    """Fetch and save one org's datasets. Returns count saved."""
    org_name = org["name"]
    display = org.get("display_name") or org_name
    dir_path = Path(OUTPUT_DIR) / org_name

    print(f"[{index + 1}/{total}] {display} ({org_name})")

    try:
        if force and dir_path.is_dir():
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


def load_orgs(path: Path = ORGS_FILE) -> list[dict] | None:
    try:
        with Path(path).open(encoding="utf-8") as f:
            orgs = json.load(f)
    except (OSError, ValueError):
        return None
    return orgs if isinstance(orgs, list) else None


@app.command()
def main(
    *,
    org_slug: str | None = typer.Option(None, "--org", help="Process a single specific organisation only"),
    force: bool = typer.Option(
        False,  # noqa: FBT003
        "--force",
        help="Refetch and overwrite orgs/datasets already saved",
    ),
) -> None:
    """Fetch all datasets from data.gov.uk into downloads/datasets/<org>/<slug>-<id8>.json."""
    orgs = load_orgs()
    if orgs is None:
        print("No organisations.json found. Run get-organisations first.", file=sys.stderr)
        raise typer.Exit(1)

    try:
        target = select_orgs(orgs, org_slug, force=force)
    except OrgNotFoundError as e:
        print(str(e), file=sys.stderr)
        print(e.hint, file=sys.stderr)
        raise typer.Exit(1) from None

    if not target:
        print("No organisations left to fetch.")
        return

    print(f"Fetching {len(target)} organisation(s)...\n")

    rate_limit = create_rate_limiter(MAX_RPS)
    total_saved = 0

    with httpx.Client(follow_redirects=True, timeout=30) as client:
        for i, org in enumerate(target):
            total_saved += process_org(org, i, len(target), rate_limit, client, force=force)

    print(f"\nDone. {total_saved} datasets saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    app()
