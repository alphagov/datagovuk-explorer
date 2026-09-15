"""Seeded fixture database for the app integration tests.

pytest-django builds the test DB from migrations; ``django_db_setup`` then
seeds it once via ``make_fixtures()``. ``make_fixtures()`` is a no-op when the
tables already hold rows, and every ``@pytest.mark.django_db`` test rolls
back, so the seed stays read-only and ``--reuse-db`` is safe.

Row factories spell out only the fields a case needs; derived columns (link
org/title/position/resource_id, link_error publisher) are filled at insert.
The ``# fmt: off`` block is data — the formatter would destroy its shape.
"""

import json
import os

import pytest
from dotenv import load_dotenv

# Load .env before Django settings import; this also covers `pytest
# explorer/tests`, which never imports tests/conftest.py. Real env vars win.
load_dotenv()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Seed ids; tests reference these instead of hardcoding strings.
FIXTURE = {
    "org": "alpha",
    "org_display_name": "Alpha Department",
    "org_no_display": "beta",
    "org_empty": "gamma",
    "dataset": "d01",
    "dataset_reviewed": "d01",
    "dataset_no_links": "d02",
    "dataset_with_api": "d09",
    "dataset_temporal": "d06",
    "harvest_source": "hs1",
    "series": 1,
    "metadata_key": "top:type",
    "metadata_section": "top",
    "metadata_name": "type",
    "metadata_value": "dataset",
    "link_error_missing_package": "missing-pkg-1",
    "link_error_org_missing": "ghost",
    "review_dataset_latest_overall": 5,
}

_LONG = "A detailed description of this dataset covering its contents, coverage, provenance and caveats. " * 2

# Row factories. Defaults are the common case; each fixture row overrides the
# handful of fields its case depends on.


def _dataset(ds_id, org, title, created, **overrides):
    """One datasets row (JSON-only keys are split out by make_fixtures)."""
    row = {
        "id": ds_id,
        "org_slug": org,
        "title": title,
        "notes": _LONG,
        "metadata_created": created,
        "metadata_modified": created,
        "theme_primary": None,
        "harvested": 0,
        "resource_count": 0,
        "views": 0,
        "tags": [],
    }
    row.update(overrides)
    return row


def _link(dataset_id, url, host, **overrides):
    """One links row; org/title/position/resource_id are derived on insert."""
    row = {
        "dataset_id": dataset_id,
        "url": url,
        "host": host,
        "name": "Test resource",
        "description": "A test resource.",
        "format": "CSV",
        "format_norm": "CSV",
        "year_created": "2024",
        "created": "2024-01-01",
    }
    row.update(overrides)
    if "format" in overrides and "format_norm" not in overrides:
        row["format_norm"] = overrides["format"].upper() if overrides["format"] else None
    return row


def _link_error(package_id, resource_url, http_status, category, *, to_delete, org="alpha", **overrides):
    """One link_errors row; publisher id/name are derived on insert."""
    row = {
        "package_id": package_id,
        "resource_url": resource_url,
        "http_status": http_status,
        "category": category,
        "to_delete": to_delete,
        "org_name": org,
    }
    row.update(overrides)
    return row


def _dataset_json(row, org_display_name):
    """A minimal CKAN-shaped JSON record, read by the detail view and metadata filter."""
    extras = list(row.get("extras", []))
    if row.get("harvested"):
        extras += [
            {"key": "harvest_source_id", "value": row["harvest_source_id"]},
            {"key": "harvest_source_title", "value": row["harvest_source_title"]},
            {"key": "harvest_object_id", "value": f"ho-{row['id']}"},
        ]

    return {
        "id": row["id"],
        "name": row["id"],
        "title": row["title"],
        "notes": row["notes"],
        "type": "dataset",
        "metadata_created": row["metadata_created"],
        "metadata_modified": row["metadata_modified"],
        "license_id": row.get("license_id", "ogl"),
        "license_title": "Open Government Licence v3.0",
        "isopen": True,
        "private": False,
        "state": "active",
        "owner_org": f"uuid-{row['org_slug']}",
        "organization": {
            "name": row["org_slug"],
            "title": org_display_name or row["org_slug"],
            "display_name": org_display_name,
        },
        "_organisation": {"display_name": org_display_name},
        "theme-primary": row.get("theme_primary"),
        "theme-secondary": row.get("theme_secondary", []),
        "tags": [{"name": t} for t in row.get("tags", [])],
        "groups": [],
        "extras": extras,
        "resources": row.get("resources", []),
        "temporal_coverage-from": row.get("temporal_from"),
        "temporal_coverage-to": row.get("temporal_to"),
        "temporal_granularity": row.get("temporal_granularity"),
        "relationships_as_subject": [],
        "relationships_as_object": [],
    }


def _review(dataset_id, org_slug, org_display_name, overall, *, ok=True, theme="environment"):
    """One JSONL-shaped review record (mirrors data/dataset-reviews-suggestions.jsonl)."""
    return {
        "dataset_id": dataset_id,
        "title": f"Review of {dataset_id}",
        "org_slug": org_slug,
        "org_display_name": org_display_name,
        "model": "test",
        "reviewed_at": "2026-01-01T00:00:00.000Z",
        "classified_at": "2026-01-01T00:00:00.000Z",
        "ok": ok,
        "overall": overall,
        "scores": {
            "findability": {"score": overall, "explanation": "Clear title and description."},
            "metadata": {
                "score": None if overall is None else max(0, overall - 1),
                "explanation": "Most fields present.",
            },
            "resources": {"score": overall, "explanation": "Resources are usable."},
        },
        "theme": theme,
        "theme_confidence": "medium",
        "tags": ["tag-one", "tag-two"],
        "suggested_title": "A clearer title",
        "suggested_description": "A clearer description.",
    }


# Seed data (see the module docstring on `# fmt: off`)
# fmt: off

# alpha has a display name, beta none (COALESCE fallbacks), gamma no datasets.
_ORGS = {
    "alpha": dict(name="alpha-department", display_name="Alpha Department", package_count=8,
                  type="central", state="active", approval_status="approved",
                  created="2010-05-05T00:00:00", title="Alpha Department"),
    "beta": dict(name="beta-council", display_name=None, package_count=8,
                 type="local", state="active", approval_status="approved",
                 created="2015-06-06T00:00:00", title="Beta Council"),
    "gamma": dict(name="gamma-agency", display_name="Gamma Agency", package_count=0,
                  type="central", state="active", approval_status="approved",
                  created="2020-07-07T00:00:00", title="Gamma Agency"),
}

# date-only; format_date and substr(...,1,4) accept it.
_DATASETS = [
    # alpha
    _dataset("d01", "alpha", "Air quality data", "2024-03-01", theme_primary="Environment",
        resource_count=5, views=100, tags=["air", "quality"]),
    _dataset("d02", "alpha", "Air quality data", "2020-06-01", notes=None,
        theme_primary="Environment", views=5, tags=["air"]),
    _dataset("d03", "alpha", "Coastal survey records 2015", "2015-01-15", notes="Tiny.", theme_primary="",
        harvested=1, resource_count=3, views=10, harvest_source_id="hs1", harvest_source_title="Alpha Harvester"),
    _dataset("d04", "alpha", "Withdrawn flood dataset", "2023-08-01", notes="This dataset has been withdrawn.",
        theme_primary="Transport", harvested=1, resource_count=12, views=20,
        harvest_source_id="hs1", harvest_source_title="Alpha Harvester", tags=["flood"]),
    _dataset("d05", "alpha", "Coastal erosion observations", "2010-05-05",
        resource_count=150, views=50, tags=["coast"]),
    _dataset("d06", "alpha", "Historic maps 1880", "2019-11-11", theme_primary="Environment", resource_count=1200,
        views=70, temporal_from="1880", temporal_to="1890", temporal_granularity="year", tags=["maps"]),
    _dataset("d12", "alpha", "Bus data", "2018-02-02", notes="Short notes.", theme_primary="",
        resource_count=4, views=30, tags=["bus"]),
    _dataset("d16", "alpha", "Road traffic counts", "2022-07-07", theme_primary="Transport", resource_count=8,
        views=40, tags=["traffic"], extras=[{"key": "contact_email", "value": "data@alpha.test"}]),
    # beta (no display name)
    _dataset("d07", "beta", "School census", "2024-01-01", theme_primary="Education", harvested=1,
        resource_count=7, views=80, harvest_source_id="hs2", harvest_source_title="Beta Harvester",
        tags=["schools"]),
    _dataset("d08", "beta", "School census", "2021-02-02", notes=None, theme_primary="Education", harvested=1,
        resource_count=2, views=15, harvest_source_id="hs2", harvest_source_title="Beta Harvester",
        tags=["schools"]),
    _dataset("d09", "beta", "Bus timetables", "2020-09-09", theme_primary="Transport",
        resource_count=1, views=25, tags=["bus"]),
    _dataset("d10", "beta", "Flood warnings", "2025-01-20", theme_primary="Environment", harvested=1,
        resource_count=20, views=90, harvest_source_id="hs2", harvest_source_title="Beta Harvester",
        temporal_from="2020", temporal_to=None, tags=["flood"]),
    _dataset("d11", "beta", "Planning applications", "2016-04-04", notes=None, theme_primary="Housing",
        views=12, tags=["planning"]),
    _dataset("d13", "beta", "Open geography API", "2023-03-03", theme_primary="Environment",
        resource_count=9, views=60, tags=["geography"]),
    _dataset("d14", "beta", "Victorian census extracts", "2017-08-08", resource_count=30, views=33,
        tags=["census"]),
    _dataset("d15", "beta", "Flood risk mapping", "2024-10-10", theme_primary="Environment",
        resource_count=6, views=44, tags=["flood"]),
]

# Dataset, position, from, to, source
_TEMPORAL = [
    ("d06", 0, 1880, 1890, "declared"),
    ("d10", 0, 2020, None, "declared"),
    ("d14", 0, 1901, 1911, "title"),
    ("d03", 0, 2013, 2015, "title"),
]

_LINKS = [
    # d01: shared URL, second shared URL, no URL
    _link("d01", "https://example.com/shared.csv", "example.com", name="Air quality 2024",
        year_created="2024", created="2024-03-01"),
    _link("d01", "https://shared.example.org/data.csv", "shared.example.org", name="Air quality 2023",
        year_created="2023"),
    _link("d01", None, None, name=None, description=None),
    # d02: shared URL, scheme-less/unparseable URL
    _link("d02", "https://shared.example.org/data.csv", "shared.example.org", name="Air quality archive",
        year_created="2020"),
    _link("d02", "not a url", None, name="Broken reference", description="Link is dead", format="HTML",
        year_created="2020"),
    # d03: shared URL, internal link
    _link("d03", "https://shared.example.org/data.csv", "shared.example.org", name="Survey",
        year_created="2015"),
    _link("d03", "https://data.gov.uk/dataset/coastal", "data.gov.uk", name="Survey notes", description="",
        format="PDF", year_created="2015"),
    # d04: missing format, subdomain, empty URL
    _link("d04", "http://other.org/flood", "other.org", name="Flood map", description="Withdrawn resource",
        format=None, year_created="2023"),
    _link("d04", "http://sub.data.gov.uk/report.pdf", "sub.data.gov.uk", name="Flood report", description=None,
        format="pdf", year_created="2023"),
    _link("d04", "", None, name=None, description="", year_created=None, created=None),
    # d05 / d06, incl. a no-URL row
    _link("d05", "https://example.com/erosion.csv", "example.com", name="Erosion data",
        description="Point data", year_created="2011"),
    _link("d06", "https://maps.example.net/1880", "maps.example.net", name="Historic map scan",
        description="TIFF scan", format="TIFF", year_created="2019"),
    _link("d06", None, None, name="Map index", description=None),
    # d12
    _link("d12", "https://example.com/bus.csv", "example.com", name="Bus stops", description="Stop locations",
        year_created="2018"),
    # d07: shared URL
    _link("d07", "https://example.com/shared.csv", "example.com", name="Census 2024",
        description="Schools census", year_created="2024"),
    _link("d07", "https://beta.example.net/method.pdf", "beta.example.net", name="Census methodology",
        description="", format="PDF", year_created="2024"),
    # d08: missing name and description
    _link("d08", "https://example.com/old-school.csv", "example.com", name=None, description=None,
        year_created="2021"),
    # d09 / d10, incl. a missing format
    _link("d09", "https://api.example.com/gtfs.zip", "api.example.com", name="Timetable API",
        description="GTFS feed", format="GTFS", year_created="2020"),
    _link("d10", "https://data.gov.uk/flood-warnings", "data.gov.uk", name="Warnings feed",
        description="Live warnings", format="JSON", year_created="2025"),
    _link("d10", "ftp://files.example.org/warnings.csv", "files.example.org", name="", description="",
        format=None, year_created="2025"),
    # d13 / d14 / d15 / d16
    _link("d13", "https://api.example.com/geo", "api.example.com", name="Geography API",
        description="GeoJSON endpoint", format="JSON", year_created="2023"),
    _link("d14", "https://example.com/census.xlsx", "example.com", name="Census extract",
        description="XLSX extract", format="XLSX", year_created="2017"),
    _link("d15", "https://example.com/risk.geojson", "example.com", name="Risk map",
        description="Risk zones", format="GeoJSON", year_created="2024"),
    _link("d16", "https://data.gov.uk/traffic", "data.gov.uk", name="Traffic counts",
        description="AADF data", year_created="2022"),
    _link("d16", "https://example.com/method", "example.com", name="Traffic methodology", description="",
        format=None, year_created="2022"),
]

# Manual datasets first, then harvested, then unknown states.
_LINK_ERRORS = [
    _link_error("d01", "https://example.com/shared.csv", 200, "OK", to_delete=False),
    _link_error("d01", "https://example.com/shared.csv", 404, "NOT_FOUND", to_delete=True),
    _link_error("d03", "https://data.gov.uk/dataset/coastal", 410, "GONE", to_delete=True),
    _link_error("d03", "https://data.gov.uk/dataset/coastal", 403, "OTHER_CLIENT_ERROR", to_delete=True),
    _link_error("d04", "https://other.org/flood", 500, "SERVER_ERROR", to_delete=True),
    _link_error("d04", "https://other.org/flood", None, "DNS_ERROR", to_delete=True),
    _link_error("d07", "https://example.com/shared.csv", None, "TIMEOUT", to_delete=True, org="beta"),
    _link_error("d07", "https://example.com/shared.csv", None, "CONNECTION_ERROR", to_delete=True, org="beta"),
    _link_error("d08", "https://beta.example.net/method.pdf", None, "CONNECTION_REFUSED", to_delete=True, org="beta"),
    _link_error("d08", "https://beta.example.net/method.pdf", 418, "OTHER_ERROR", to_delete=True, org="beta"),
    _link_error("missing-pkg-1", "not-a-url", 404, "NOT_FOUND", to_delete=True, org="ghost"),
    _link_error("missing-pkg-2", "", None, "TIMEOUT", to_delete=True, org="ghost"),
    _link_error("d09", "https://api.example.com/gtfs.zip", 404, "NOT_FOUND", to_delete=True, org="beta"),
    _link_error("d09", "https://api.example.com/gtfs.zip", 200, "OK", to_delete=False, org="beta"),
    _link_error("d10", "https://data.gov.uk/flood-warnings", 404, "NOT_FOUND", to_delete=True, org="beta"),
    _link_error("d11", "https://example.com/planning", 500, "SERVER_ERROR", to_delete=True),
    _link_error("d12", "https://example.com/bus.csv", 200, "OK", to_delete=False),
    _link_error("d15", "https://example.com/risk.geojson", None, "DNS_ERROR", to_delete=True, org="beta"),
]

_METADATA_KEYS = [
    ("top:type", "top", 16, 16, 2),
    ("top:license_id", "top", 16, 14, 2),
    ("extras:contact_email", "extras", 1, 1, 1),
]

_METADATA_VALUES = [
    ("top:type", "dataset", 15),
    ("top:type", "series", 1),
    ("top:license_id", "ogl", 13),
    ("top:license_id", "other", 1),
    ("extras:contact_email", "data@alpha.test", 1),
]

# Harvest sources: id, title, org, active, frequency, last harvest request
_HARVEST_SOURCES = [
    ("hs1", "Alpha Harvester", "alpha", True, "weekly", "2025-01-01T00:00:00"),
    ("hs2", "Beta Harvester", "beta", True, "daily", "2025-02-01T00:00:00"),
    ("hs3", "Gamma Harvester", "gamma", False, "manual", None),
]

# Two ok reviews for d01 (latest wins), one ok:false, plus d07 and d05.
_REVIEWS = [
    _review("d01", "alpha", "Alpha Department", 3),
    _review("d01", "alpha", "Alpha Department", FIXTURE["review_dataset_latest_overall"]),
    _review("d01", "alpha", "Alpha Department", 1, ok=False),
    _review("d07", "beta", None, 4),
    _review("d05", "alpha", "Alpha Department", None),
]

# fmt: on

# Keys that live only in dataset_json, not on the datasets summary row.
_JSON_ONLY = ("extras", "resources", "temporal_from", "temporal_to", "temporal_granularity", "theme_secondary")


def _model_fields(row):
    """A dataset row's model columns (tags serialised, JSON-only keys dropped)."""
    return {**{k: v for k, v in row.items() if k not in _JSON_ONLY}, "tags": json.dumps(row.get("tags", []))}


def make_fixtures():
    """Insert the fixture world once (idempotent)."""
    from django.db import connection

    from explorer.models import (
        Dataset,
        DatasetApi,
        DatasetContentHash,
        DatasetJson,
        HarvestSource,
        Link,
        LinkError,
        MetadataKey,
        MetadataValue,
        Organisation,
        Review,
        Series,
        SeriesDataset,
        TemporalPeriod,
    )

    if Dataset.objects.exists():
        return FIXTURE

    Organisation.objects.bulk_create(
        [Organisation(slug=slug, **fields) for slug, fields in _ORGS.items()],
    )
    display = {slug: fields["display_name"] for slug, fields in _ORGS.items()}
    by_id = {row["id"]: row for row in _DATASETS}

    Dataset.objects.bulk_create(
        [Dataset(org_display_name=display[row["org_slug"]], **_model_fields(row)) for row in _DATASETS],
    )
    # Pass a dict, not a JSON string: raw-SQL readers expect an object.
    DatasetJson.objects.bulk_create(
        [DatasetJson(dataset_id=row["id"], json=_dataset_json(row, display[row["org_slug"]])) for row in _DATASETS],
    )
    HarvestSource.objects.bulk_create(
        [
            HarvestSource(
                id=hs_id,
                title=title,
                url=f"https://{org}.test/harvest",
                type="harvest",
                active=active,
                frequency=frequency,
                organization_id=f"uuid-{org}",
                org_slug=org,
                created="2012-01-01T00:00:00",
                json=json.dumps({"status": {"last_harvest_request": last_run}} if last_run else {}),
            )
            for hs_id, title, org, active, frequency, last_run in _HARVEST_SOURCES
        ],
    )
    TemporalPeriod.objects.bulk_create(
        [
            TemporalPeriod(dataset_id=ds_id, position=pos, from_year=frm, to_year=to, source=source)
            for ds_id, pos, frm, to, source in _TEMPORAL
        ],
    )
    DatasetApi.objects.bulk_create(
        [
            DatasetApi(dataset_id="d09", api_category="map-layers"),
            DatasetApi(dataset_id="d13", api_category="data-apis"),
        ],
    )

    # One row per dataset, as the real build populates it — every dataset
    # gets its own hash except the three that share one: d01 + d05 (alpha)
    # and d09 (beta). Three members, not two, so a group has a distinct
    # group count (1), member count (3) and redundant-record count (2) —
    # the datasets-duplicate-content report's own count, its dashboard card
    # and the detail page each assert a different one. Cross-org, so the
    # detail page's org_count is exercised too.
    _shared_hash = "hash-shared-d01-d05-d09"
    DatasetContentHash.objects.bulk_create(
        [
            DatasetContentHash(
                dataset_id=row["id"],
                content_hash=_shared_hash if row["id"] in ("d01", "d05", "d09") else f"hash-{row['id']}",
            )
            for row in _DATASETS
        ],
    )

    # Derive link org/title/position/resource_id from the dataset rows.
    positions = {}
    links = []
    for i, row in enumerate(_LINKS):
        ds_id = row["dataset_id"]
        positions[ds_id] = pos = positions.get(ds_id, 0)
        positions[ds_id] += 1
        links.append(
            Link(
                resource_id=f"res-{i:03d}",
                org_slug=by_id[ds_id]["org_slug"],
                org_display_name=display[by_id[ds_id]["org_slug"]],
                dataset_title=by_id[ds_id]["title"],
                position=pos,
                **row,
            ),
        )
    Link.objects.bulk_create(links)

    LinkError.objects.bulk_create(
        [
            LinkError(
                datagovuk_url=f"https://data.gov.uk/{row['package_id']}",
                package_name=by_id.get(row["package_id"], {}).get("title", row["package_id"]),
                org_id=f"uuid-{row['org_name']}",
                package_metadata_created="2020-01-01T00:00:00",
                package_metadata_modified="2024-01-01T00:00:00",
                guid=f"err-{i:03d}",
                resource_id=f"err-{i:03d}",
                resource_created="2020-01-01T00:00:00",
                resource_last_modified="2024-01-01T00:00:00",
                resource_metadata_modified="2024-01-01T00:00:00",
                error_detail=None,
                checked_at="2026-01-01T00:00:00",
                **row,
            )
            for i, row in enumerate(_LINK_ERRORS)
        ],
    )

    MetadataKey.objects.bulk_create(
        [
            MetadataKey(key=key, section=section, count=count, non_empty=non_empty, distinct_values=distinct)
            for key, section, count, non_empty, distinct in _METADATA_KEYS
        ],
    )
    MetadataValue.objects.bulk_create(
        [MetadataValue(metadata_key_id=key, value=value, count=count) for key, value, count in _METADATA_VALUES],
    )
    Series.objects.bulk_create(
        [Series(id=1, root_title="Coastal monitoring", type="timeseries", dataset_count=2, org_count=1)],
    )
    SeriesDataset.objects.bulk_create(
        [
            SeriesDataset(
                series_id=1,
                dataset_id=ds_id,
                dataset_title=by_id[ds_id]["title"],
                date_suffix=suffix,
                org_slug="alpha",
                org_display_name="Alpha Department",
            )
            for ds_id, suffix in (("d01", "2024"), ("d05", "2011"))
        ],
    )

    # Typed columns mirror the JSON written by scripts/ingest_reviews.py.
    Review.objects.bulk_create(
        [
            Review(
                dataset_id=record["dataset_id"],
                ok=record["ok"],
                overall=record["overall"],
                findability=record["scores"]["findability"]["score"],
                metadata=record["scores"]["metadata"]["score"],
                resources=record["scores"]["resources"]["score"],
                theme=record["theme"],
                tags=json.dumps(record["tags"]),
                title=record["suggested_title"],
                desc=record["suggested_description"],
                theme_confidence=record["theme_confidence"],
                created_at=record["reviewed_at"],
                json=json.dumps(record),
            )
            for record in _REVIEWS
        ],
    )

    # datasets.fts is a build-time tsvector; populate it as the build does.
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE datasets SET fts = to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(notes, ''))",
        )

    return FIXTURE


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Seed once, after pytest-django creates the test DB."""
    with django_db_blocker.unblock():
        make_fixtures()


@pytest.fixture(scope="session")
def fixtures():
    """The known fixture ids (see FIXTURE)."""
    return FIXTURE


def pytest_addoption(parser):
    parser.addoption(
        "--fail-on-skip",
        action="store_true",
        default=False,
        help="Fail the run if any test is skipped (CI guard against skip-to-green).",
    )


def _skip_reports(config):
    """The reports pytest marked as skipped, from the terminal reporter."""
    reporter = config.pluginmanager.getplugin("terminalreporter")
    return reporter.stats.get("skipped", []) if reporter else []


def pytest_sessionfinish(session, exitstatus):
    """Turn ``--fail-on-skip`` into a failing exit code (CI's no-skip guard)."""
    if session.config.getoption("--fail-on-skip") and _skip_reports(session.config):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Spell out the skips that ``--fail-on-skip`` is failing the run on."""
    if not config.getoption("--fail-on-skip"):
        return
    skipped = _skip_reports(config)
    if not skipped:
        return
    terminalreporter.write_sep(
        "=",
        f"fail-on-skip: {len(skipped)} unexpected skip(s)",
        red=True,
    )
    for report in skipped:
        terminalreporter.write_line(f"  {report.nodeid}\n    {report.longrepr}")
