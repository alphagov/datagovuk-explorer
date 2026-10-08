#!/usr/bin/env python3
"""Build (or rebuild) the core database tables from the cached JSON on disk.

Reads organisations.json, downloads/harvest_sources.json and every
dataset file under downloads/, then writes everything into the database.
The server can then answer page requests with fast indexed queries instead
of reading and parsing 50k+ JSON files on every request.

The full dataset JSON is stored in the dataset_json table, so nothing is
lost — the files under downloads/ remain the on-disk cache.

Usage: python -m scripts.ingest_ckan
       DATABASE_URL=postgresql://localhost:5432/other python -m scripts.ingest_ckan

Phases: wipe core tables, organisations, datasets (batched, parallel file reads).
Derived tables (FTS, views, metadata, dataset_api, etc.) are populated by
separate scripts — see `just build-db` for the full sequence.
Indexes are migration-owned (0001) — the build populates, never creates.

Embeddings are a separate step: run scripts/build_embeddings.py after building.
"""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit

from scripts.db import connect, database_url

# Number of JSON files to read in parallel per batch. Reading many small
# files one-at-a-time is the dominant bottleneck, so we batch them with
# threads to overlap I/O.
READ_BATCH_SIZE = 2000

_DOWNLOADS = Path(__file__).resolve().parent.parent / "downloads"
DATASETS_DIR = _DOWNLOADS / "datasets"
ORGS_FILE = _DOWNLOADS / "organisations" / "organisations.json"
HARVEST_SOURCES_FILE = _DOWNLOADS / "organisations" / "harvest_sources.json"
DATABASE_URL = database_url()

_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Temporal coverage normalisation
# ---------------------------------------------------------------------------
def _stringify(v) -> str:
    """Stringify a scalar the way it appears in JSON: booleans lowercase
    ('true'/'false'), integral floats rendered without the trailing '.0',
    everything else str()."""

    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def temporal_val(v):
    """Normalise a temporal coverage value for storage.

    CKAN stores these as either a plain string ("2012-06-09", "point") or
    an array of dates (multiple coverage periods). Blank/empty values →
    None; arrays are joined so the column stays readable and queryable.
    """

    if v is None or v == "":
        return None
    if isinstance(v, list):
        return ", ".join(_stringify(x) for x in v) if v else None
    return _stringify(v)


_YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b", re.ASCII)


def temporal_year(v):
    """Extract the coverage year from a normalised temporal value. Values are
    messy (ISO dates "2010-04-01", UK dates "31/07/2015", junk like
    "present"/"-"/"19"/"Months") — pull the first 4-digit year in the
    1500-2099 range, else None. re.ASCII keeps \\d and \\b ASCII-only."""

    if not v:
        return None
    m = _YEAR_RE.search(_stringify(v))
    return m.group(1) if m else None


def temporal_periods(from_val, to_val):
    """Reduce normalised temporal from/to values to a list of coverage
    periods, each an [from_year, to_year] pair (either year null). Periods
    are paired up positionally and kept separate so non-contiguous coverage
    (e.g. [1960-1992] and [2000-2016]) can be matched as a union instead
    of collapsing to the first period. Reversed pairs (from > to) are
    swapped. Returns None when neither side yields any years."""

    from_years = [temporal_year(y) for y in _stringify(from_val).split(", ")] if from_val else []
    to_years = [temporal_year(y) for y in _stringify(to_val).split(", ")] if to_val else []
    n = max(len(from_years), len(to_years))
    if not n:
        return None
    periods = []
    for i in range(n):
        # A missing year parses as falsy — guard the length before indexing.
        f = int(from_years[i]) if i < len(from_years) and from_years[i] else None
        t = int(to_years[i]) if i < len(to_years) and to_years[i] else None
        if f is None and t is None:
            continue
        periods.append([t, f] if f is not None and t is not None and f > t else [f, t])
    return periods or None


# Explicit year-range separators: "1838 - 1862", "2019-20", "2009 to 2010",
# en/em-dash variants (\u2013/\u2014 — escaped so the source stays ASCII).
# re.ASCII keeps \d and \b ASCII-only like _YEAR_RE. The end boundary is
# (?!\d) rather than \b so filenames like "2021 - 2023_0300_S3.pdf"
# (reference-number suffixes glued to the year) still parse as a range — \b
# would reject the underscore after "2023".
_RANGE_SEP = r"(?:\s*[-\u2013\u2014]\s*|\s+to\s+)"
_RANGE_RE = re.compile(
    rf"\b(1[5-9]\d\d|20\d\d){_RANGE_SEP}(\d\d|\d{{4}})(?!\d)",
    re.ASCII,
)
# Standalone-year pass for the text outside ranges: the same relaxed end
# boundary, so a year with a suffix glued on ("2023_0300" with no range,
# "2023data") still yields a period. The leading \b stays: "data_2023"
# (underscore before the year) is not a year start.
_STANDALONE_YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20\d\d)(?!\d)", re.ASCII)
# 2-digit end years expand via their century (2019-20 -> 2020); the result
# must land in the same window _YEAR_RE accepts (1500-2099), and 4-digit
# ends like "0300" fail the floor check.
_CENTURY = 100
_YEAR_MIN = 1000
_YEAR_MAX = 2099


def _dedupe_periods(periods: list) -> list:
    """Order-preserving dedupe of [from, to] pairs."""
    seen: set = set()
    out = []
    for p in periods:
        key = tuple(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _text_periods(text) -> list:
    """Extract coverage periods from free text (a dataset title or a
    resource name). Explicit year ranges first — "1838 - 1862", "2019-20"
    (2-digit tail expanded via its century, so 2019-20 → 2019-2020),
    "2009 to 2010" — then standalone years as closed single-year periods
    [y, y]. Reversed ranges are swapped. Deduped, capped at 10 periods."""
    if not text:
        return []
    periods = []
    for m in _RANGE_RE.finditer(text):
        a = int(m.group(1))
        b = int(m.group(2))
        if b < _CENTURY:
            b += (a // _CENTURY) * _CENTURY  # century expansion: 2019-20 -> 2020
        if not _YEAR_MIN <= b <= _YEAR_MAX:
            continue
        periods.append([min(a, b), max(a, b)])
    # Standalone years in the text outside the matched ranges.
    periods.extend([int(m.group(1))] * 2 for m in _STANDALONE_YEAR_RE.finditer(_RANGE_RE.sub(" ", text)))
    return _dedupe_periods(periods)[:10]


def _suggested_periods(ds: dict) -> tuple[list | None, str | None]:
    """Infer coverage periods when the publisher declared none: the dataset
    title first (high confidence), resource names as fallback (noisier,
    lower value — filenames can carry reference numbers). Returns
    (periods, source) with source 'title' or 'resource', or (None, None)
    when nothing is found."""
    periods = _text_periods(ds.get("title"))
    if periods:
        return periods, "title"
    all_periods: list = []
    for r in ds.get("resources") or []:
        all_periods.extend(_text_periods(r.get("name")))
    periods = _dedupe_periods(all_periods)[:10]
    if periods:
        return periods, "resource"
    return None, None


# ---------------------------------------------------------------------------
# Host extraction
# ---------------------------------------------------------------------------
# Loose scheme://host fallback for URLs that defeat urlsplit (unencoded
# spaces, angle brackets, ...): /^[a-z][a-z0-9+.-]*:\/\/([^/?#]+)/i
_SCHEME_HOST_RE = re.compile(r"^[a-z][a-z0-9+.-]*://([^/?#]+)", re.IGNORECASE)
# A real hostname can only contain word chars (letters/digits/underscore),
# dots and hyphens — re.ASCII makes \w ASCII-only.
_BAD_HOST_CHARS = re.compile(r"[^\w.-]", re.ASCII)

# Schemes where WHATWG treats backslashes as slashes and auto-parses the
# authority (http:/host, http:host, http:///host all put host in authority).
_SPECIAL_SCHEMES = {"http", "https", "ws", "wss", "ftp", "file"}
_SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.-]*):", re.IGNORECASE)


def _whatwg_normalize(url: str) -> str:
    """Approximate WHATWG URL host parsing enough for extract_host.

    For special schemes, new URL() treats backslashes as forward slashes and
    enters the authority state after any number of slashes (zero included)
    following the scheme colon — so `http:/host`, `http:host` and
    `http:///host` all yield host `host`. urlsplit requires exactly `//`, so
    normalize those shapes first. The `file` scheme is the exception:
    WHATWG only parses a host after exactly `file://host`, so Windows
    paths like `file:///C:/...` (and `file://` + backslash forms) have an
    empty host (null) — no slash collapsing. Non-special schemes (mailto:,
    etc.) and scheme-less strings are returned unchanged (the fallback
    regex rejects them).
    """

    m = _SCHEME_RE.match(url)
    if not m or m.group(1).lower() not in _SPECIAL_SCHEMES:
        return url
    scheme = m.group(1).lower()
    rest = url[m.end() :]
    if "\\" in rest:
        rest = rest.replace("\\", "/")
    # http/https/ws/wss/ftp: the authority follows any number of slashes
    # (http:/host, http:host, http:///host all put host in authority).
    # file: only parses a host after exactly `file://host` — file:///C:/…
    # and file://\\J:\… have an EMPTY host (the drive letter is part of the
    # path), so don't collapse slashes for it.
    if scheme != "file":
        rest = re.sub(r"^/*", "//", rest)
    return f"{scheme}:{rest}"


def _idna_host(host: str) -> str:
    """WHATWG applies IDNA ToASCII to special-scheme hosts, so unicode hosts
    come out punycoded (e.g. 'Spend-over-£25k…' → 'xn--spend-over-25k…').
    Python's urlsplit leaves the unicode in place; the 'idna' codec produces
    the same form. Raises on invalid IDNA."""

    return host.encode("idna").decode("ascii")


def extract_host(url):
    """Extract a normalised hostname from a resource URL. Strips the leading
    "www." and lowercases so the links report can group by host. Returns
    None for blank/unparseable URLs.

    Uses the WHATWG URL algorithm: try urlsplit (with a pre-normalisation
    for special schemes — backslashes-as-slashes, lenient authority slashes
    — and IDNA punycode for unicode hosts), reject malformed ports, fall
    back to the loose scheme://host regex, then lowercase + strip www. and
    reject hosts containing non-[\\w.-] chars. IPv6 bracket hosts are
    rejected by the bad-char check."""

    if not url or not isinstance(url, str):
        return None
    host = None
    try:
        parts = urlsplit(_whatwg_normalize(url))
        # new URL() throws on non-numeric or out-of-range ports; urlsplit's
        # .port property raises ValueError for the same inputs. hostname
        # alone would silently accept them, so probe the port when present.
        if parts.hostname and ":" in parts.netloc:
            _ = parts.port  # raises ValueError on a malformed port
        host = parts.hostname or None
        # new URL() punycodes unicode hosts (IDNA ToASCII); urlsplit leaves
        # them in place — encode to the same xn-- form.
        if host and not host.isascii():
            host = _idna_host(host)
    except (ValueError, UnicodeError):
        host = None
    if host is None:
        m = _SCHEME_HOST_RE.match(url)
        host = m.group(1) if m else None
    if not host:
        return None
    host = host.lower().removeprefix("www.")
    if _BAD_HOST_CHARS.search(host):
        return None
    return host


# ---------------------------------------------------------------------------
# Format normalisation
# ---------------------------------------------------------------------------
# CKAN's `format` field is free text, so values get mechanical cleaning
# (uppercase, trim, IANA media-type URL → its type, dot strip), then map
# through MIME_TO_NAME / FORMAT_ALIASES. Anything not in the maps keeps its
# cleaned label — rare-but-real formats are left alone rather than hidden.
# Judgment calls behind the aliases:
#  - ArcGIS GeoServices REST API and ESRI variants collapse to ARCGIS REST
#    (ArcGIS Hub's default export label); interactive products (storymaps,
#    experiences) stay separate.
#  - Portal-page labels (websites, webpages) → WEB PAGE; API/SPARQL and
#    DASHBOARD stay separate — "the link isn't a data file" is a finding.
#  - json1.0/json2.0 are NISRA's JSON-stat endpoints, not typos.
#  - Multi-format labels like "CSV / ZIP" are left alone — assigning them
#    to either type is an inference and splitting double-counts.

# MIME types (raw or from IANA media-type URLs) → common names
MIME_TO_NAME = {
    "TEXT/CSV": "CSV",
    "APPLICATION/JSON": "JSON",
    "APPLICATION/LD+JSON": "JSON-LD",
    "APPLICATION/PARQUET": "PARQUET",
    "APPLICATION/ZIP": "ZIP",
    "TEXT/PLAIN": "TXT",
    "TXT/PLAIN": "TXT",
    "APPLICATION/RDF+XML": "RDF",
    "TEXT/N3": "N3",
    "TEXT/TURTLE": "TTL",
    "APPLICATION/GPX+XML": "GPX",
    "APPLICATION/VNDGOOGLE-EARTHKML+XML": "KML",
    "APPLICATION/VNDOPENXMLFORMATS-OFFICEDOCUMENTSPREADSHEETMLSHEET": "XLSX",
    "APPLICATION/OCTET-STREAM": "OCTET-STREAM",
    "APPLICATION/XHTML+XML": "HTML",
    "TEXT/HTML; CHARSET=UTF-8": "HTML",
    "TEXT/RTF": "RTF",
    "APPLICATION/GML+XML": "GML",
    "APPLICATION/GEOPACKAGE+SQLITE3": "GPKG",
    "APPLICATION/X-MSDOS-PROGRAM": "EXE",
    "APPLICATION/X-NETCDF": "NETCDF",
    "APPLICATION/MSACCESS": "MDB",
}

# High-confidence synonyms and deliberate buckets (keys are post-cleaning)
FORMAT_ALIASES = {
    # typos
    "CVS": "CSV",
    "CVC": "CSV",
    "CSV FILE": "CSV",
    "CSV / CSV": "CSV",
    "XLXS": "XLSX",
    "XLX": "XLSX",
    "XSLX": "XLSX",
    "HMTL": "HTML",
    "HML": "HTML",
    "TIF": "TIFF",
    "KMX": "KMZ",
    "EXEL": "XLS",
    "EXCELL": "XLS",
    "GEOPACKAGE": "GPKG",
    "GEOPACKAGES": "GPKG",
    "GEODATABASE": "GDB",
    "SHAPE": "SHP",
    # JSON-stat API endpoints (NISRA) — raw values "json1.0"/"json2.0"
    "JSON10": "JSON-STAT",
    "JSON20": "JSON-STAT",
    # same format, different labels
    "PDF / PDF": "PDF",
    "ZIP / ZIP": "ZIP",
    "WEBMAP": "WEB MAP",
    "POWERBI": "POWER BI",
    "OD / ODS": "ODS",
    "WORD": "DOC",
    "WORD DOC": "DOC",
    "MS WORD": "DOC",
    "POWERPOINT": "PPT",
    "RDFA": "RDF",
    "HTML+RDFA": "RDF",
    "SKOS RDF": "RDF",
    # ArcGIS Hub default export label + synonyms → one REST bucket
    "ARCGIS GEOSERVICES REST API": "ARCGIS REST",
    "ESRI REST": "ARCGIS REST",
    "ESRI GEOSERVICE": "ARCGIS REST",
    "ESRI REST API": "ARCGIS REST",
    "ESRI REST SERVICE": "ARCGIS REST",
    "FEATURE SERVER": "ARCGIS REST",
    "FEATURE SERVICE": "ARCGIS REST",
    "MAP SERVICE": "ARCGIS REST",
    # Crown Commercial Service's standard download label (a ZIP bundle; 100%
    # of this value is one org) → ZIP
    "APPLICATION/ZIP, APPLICATION/OCTET-STREAM, APPLICATION/X-ZIP-COMPRESSED, MULTIPART/X-ZIP": "ZIP",
    # Links to a portal page rather than a data file
    "WEBPAGE": "WEB PAGE",
    "WEBSITE": "WEB PAGE",
    "WEB": "WEB PAGE",
    "WEBLINK": "WEB PAGE",
    "URL": "WEB PAGE",
    "OPEN DATA SITE": "WEB PAGE",
    "OPEN DATA WEBSITE": "WEB PAGE",
    "OPEN DATE SITE": "WEB PAGE",
    "ESRI OPEN DATA SITE": "WEB PAGE",
    "SCHOOL LOCALITIES ON OPEN DATA SITE": "WEB PAGE",
    "WEP PAGE": "WEB PAGE",
    "WEBSITE CONTAINING DATA FILES": "WEB PAGE",
    "HTTP": "WEB PAGE",
    "HTTPS": "WEB PAGE",
    "INFORMATION AND DOWNLOAD": "WEB PAGE",
    "DATA DOWNLOAD": "WEB PAGE",
}

# IANA media-type URL, e.g. https://www.iana.org/assignments/media-types/text/csv
IANA_RE = re.compile(
    r"^https?://www\.iana\.org/assignments/media-types/(.+)$",
    re.IGNORECASE,
)


def normalise_format(raw):
    """Normalise a resource format string for the links facet.
    Returns None for blank."""

    if not raw or not isinstance(raw, str):
        return None
    f = raw.strip()
    if f == "":
        return None

    # IANA media-type URLs carry the MIME type in the URL path — pull it out
    # before the dot-strip mangles the hostname.
    m = IANA_RE.match(f)
    if m:
        f = m.group(1)

    # Mechanical cleaning: uppercase, strip dots, collapse runs of
    # whitespace (so trailing "CSV " folds into "CSV"), and drop the "OGC "
    # prefix from WFS/WMS/WMTS so they share one facet with their bare forms.
    f = f.upper().replace(".", "")
    f = _WS_RE.sub(" ", f).strip()
    if f == "":
        return None
    m = re.match(r"^OGC (WFS|WMS|WMTS)$", f)
    if m:
        f = m.group(1)

    # MIME types → common names (text/csv → CSV, application/zip → ZIP…)
    if f in MIME_TO_NAME:
        return MIME_TO_NAME[f]

    # High-confidence synonyms and deliberate buckets
    if f in FORMAT_ALIASES:
        return FORMAT_ALIASES[f]

    return f


# ---------------------------------------------------------------------------
# Wipe — schema is owned by Django migrations; the build only truncates
# the core tables it repopulates (series/derived tables excluded). The
# embedding tables are deliberately untouched: they are keyed on ckan_id and
# must survive a re-ingest (see explorer/models.py EmbeddingMap).
# ---------------------------------------------------------------------------

TRUNCATE_SQL = (
    "TRUNCATE TABLE links, temporal_periods, dataset_json, datasets, "
    "organisations, harvest_sources RESTART IDENTITY CASCADE"
)


# ---------------------------------------------------------------------------
# Dataset load
# ---------------------------------------------------------------------------

# Prepared-statement SQL for the per-batch insert — static strings, so they
# live at module level and _process_batch reads as data-flow, not SQL-plus-
# mapping. The datasets/json statements upsert (the pipeline re-runs are
# idempotent); the links statement is bulk-loaded per batch.
INSERT_DATASET_SQL = """
INSERT INTO datasets
    (ckan_id, org_slug, org_display_name, title, name, notes, metadata_created,
     metadata_modified, resource_count, theme_primary,
     harvested, harvest_source_title, harvest_source_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (ckan_id) DO UPDATE SET
    org_slug = EXCLUDED.org_slug, org_display_name = EXCLUDED.org_display_name,
    title = EXCLUDED.title, name = EXCLUDED.name, notes = EXCLUDED.notes,
    metadata_created = EXCLUDED.metadata_created,
    metadata_modified = EXCLUDED.metadata_modified,
    resource_count = EXCLUDED.resource_count,
    theme_primary = EXCLUDED.theme_primary,
    harvested = EXCLUDED.harvested,
    harvest_source_title = EXCLUDED.harvest_source_title,
    harvest_source_id = EXCLUDED.harvest_source_id
RETURNING id
"""

# One row per coverage period — bulk-loaded per batch like links.
# Upsert: a dataset can appear under multiple orgs in the download set.
INSERT_PERIOD_SQL = """
INSERT INTO temporal_periods
    (dataset_id, position, from_year, to_year, source)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (dataset_id, position) DO UPDATE SET
    from_year = EXCLUDED.from_year,
    to_year   = EXCLUDED.to_year,
    source    = EXCLUDED.source
"""

INSERT_JSON_SQL = """
INSERT INTO dataset_json (dataset_id, json) VALUES (?, ?)
ON CONFLICT (dataset_id) DO UPDATE SET json = EXCLUDED.json
"""

INSERT_LINK_SQL = """
INSERT INTO links
    (resource_id, dataset_id, org_slug, org_display_name, dataset_title,
     name, description, url, host, format, format_norm, year_created, created, position)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class _BuildState:
    """Mutable build counters + accumulators shared across batches."""

    def __init__(self) -> None:
        self.count = 0
        self.skipped = 0


def _read_parse(item: dict) -> dict:
    """Read + parse one dataset file off the main thread. Read or parse
    failure → {'skipped': True}."""

    try:
        raw = item["filepath"].read_text(encoding="utf-8")
    except OSError:
        return {"skipped": True}
    try:
        ds = json.loads(raw)
    except ValueError:
        return {"skipped": True}
    return {"ds": ds, "raw": raw, "orgSlug": item["orgSlug"], "skipped": False}


def _extras(ds: dict) -> dict:
    """The dataset's extras keyed by key (harvest bookkeeping)."""
    return {e["key"]: e["value"] for e in ds.get("extras") or []}


def _dataset_row(ds: dict, extras: dict, org_name, org_display) -> tuple:
    """The 13 VALUES for insert_ds, derived from one dataset dict."""
    return (
        ds.get("id"),
        org_name,
        org_display,
        ds.get("title"),
        ds.get("name"),
        ds.get("notes") or None,
        ds.get("metadata_created"),
        ds.get("metadata_modified"),
        len(ds.get("resources") or []),
        ds.get("theme-primary") or None,
        1 if extras.get("harvest_object_id") else 0,
        extras.get("harvest_source_title") or None,
        extras.get("harvest_source_id") or None,
    )


def _dataset_period_rows(ds: dict, int_id: int) -> list[tuple]:
    """The insert_period rows for one dataset: (dataset_id, position,
    from_year, to_year, source). Declared periods from the publisher's
    temporal_coverage-from/to (source='declared') when they yield any;
    otherwise suggested periods inferred from the title or a resource name
    (source='title'/'resource'). Inference fills gaps only — never
    alongside declared coverage. Empty when neither source yields a year."""
    periods = temporal_periods(
        temporal_val(ds.get("temporal_coverage-from")),
        temporal_val(ds.get("temporal_coverage-to")),
    )
    source: str
    if periods:
        source = "declared"
    else:
        periods, suggested_source = _suggested_periods(ds)
        if not periods:
            return []
        # _suggested_periods returns a source only together with periods
        assert suggested_source is not None
        source = suggested_source
    return [(int_id, i, p[0], p[1], source) for i, p in enumerate(periods)]


def _link_rows(ds: dict, int_id: int, org_name, org_display, year_created) -> list[tuple]:
    """The insert_link rows, one per resource."""
    rows = []
    for r in ds.get("resources") or []:
        raw_format = r.get("format") or None
        position = r.get("position")
        rows.append(
            (
                r.get("id") or None,
                int_id,
                org_name,
                org_display,
                ds.get("title"),
                r.get("name") or None,
                r.get("description") or None,
                r.get("url") or None,
                extract_host(r.get("url")),
                raw_format,
                normalise_format(raw_format),
                year_created,
                r.get("created") or None,
                position if isinstance(position, (int, float)) else None,
            ),
        )
    return rows


def _process_batch(db, batch: list[dict], st: _BuildState) -> None:
    """Process files in batches: read each batch in parallel (overlapping
    I/O via threads), parse, then insert in a single transaction."""

    # Phase 1: read & parse the whole batch concurrently. ThreadPoolExecutor
    # preserves input order, so insertion order — and therefore row ids —
    # stay deterministic.
    with ThreadPoolExecutor() as pool:
        parsed = list(pool.map(_read_parse, batch))

    # Phase 2: insert within a pg transaction (single client, BEGIN/COMMIT)
    def _tx(tx) -> None:
        insert_ds = tx.prepare(INSERT_DATASET_SQL)
        insert_json = tx.prepare(INSERT_JSON_SQL)
        insert_link = tx.prepare(INSERT_LINK_SQL)
        insert_period = tx.prepare(INSERT_PERIOD_SQL)

        for item in parsed:
            if item["skipped"]:
                st.skipped += 1
                continue
            ds, raw, org_slug = item["ds"], item["raw"], item["orgSlug"]

            # Shared per-dataset derivations — extras, org-name fallbacks
            # and the created year feed both the dataset row and the links.
            extras = _extras(ds)
            org = ds.get("_organisation") or {}
            org_name = org.get("name") or org_slug
            org_display = org.get("display_name") or org_slug
            year_created = (ds.get("metadata_created") or "")[:4] or None

            # INSERT … RETURNING id gives back the auto-assigned integer PK.
            row = insert_ds.get(*_dataset_row(ds, extras, org_name, org_display))
            int_id = row["id"]
            insert_json.run(int_id, raw)
            for link_row in _link_rows(ds, int_id, org_name, org_display, year_created):
                insert_link.run(*link_row)
            for period_row in _dataset_period_rows(ds, int_id):
                insert_period.run(*period_row)

            st.count += 1

    db.transaction(_tx)


def _load_orgs() -> list:
    """Read downloads/organisations.json — the friendly CLI errors on
    failure are the interface (get-organisations regenerates the file)."""
    print("Reading organisations.json...", file=sys.stderr)
    try:
        return json.loads(ORGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        print(f"Could not read {ORGS_FILE}: {err}", file=sys.stderr)
        print(
            "Run `just get-organisations` first (regenerates it from the CKAN API).",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


def _load_harvest_sources() -> list:
    """Read downloads/harvest_sources.json — the friendly CLI errors on
    failure are the interface (get-harvest-sources regenerates the file)."""
    print("Reading harvest_sources.json...", file=sys.stderr)
    try:
        data = json.loads(HARVEST_SOURCES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        print(f"Could not read {HARVEST_SOURCES_FILE}: {err}", file=sys.stderr)
        print(
            "Run `just get-harvest-sources` first (regenerates it from the CKAN API).",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    # The wrapper groups the records by owning org; the build wants a flat
    # list of records.
    return [source for sources in data["orgs"].values() for source in sources]


def _collect_files() -> list[dict[str, str | Path]]:
    """All .json dataset files with their org slug. Sorted on both levels so
    the build is deterministic regardless of filesystem directory order (and
    matches the insertion order a table diff expects)."""
    if not DATASETS_DIR.is_dir():
        print(
            f"No {DATASETS_DIR}/ directory found — run get_datasets.py first.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    all_files: list[dict[str, str | Path]] = []
    for org_dir in sorted(DATASETS_DIR.iterdir(), key=lambda p: p.name):
        if not org_dir.is_dir():
            continue
        all_files.extend(
            {"filepath": f, "orgSlug": org_dir.name}
            for f in sorted(org_dir.iterdir(), key=lambda p: p.name)
            if f.name.endswith(".json") and f.name != "no-datasets.json"
        )
    return all_files


def _load_organisations_tx(tx, orgs) -> None:
    """Insert/upsert the organisations rows."""
    insert_org = tx.prepare(
        """
        INSERT INTO organisations
            (slug, name, display_name, package_count, type, state, approval_status, created, title, json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (slug) DO UPDATE SET
            name = EXCLUDED.name, display_name = EXCLUDED.display_name,
            package_count = EXCLUDED.package_count, type = EXCLUDED.type,
            state = EXCLUDED.state, approval_status = EXCLUDED.approval_status,
            created = EXCLUDED.created, title = EXCLUDED.title, json = EXCLUDED.json
        """,
    )
    for o in orgs:
        insert_org.run(
            o["name"],
            o["name"],
            o.get("display_name"),
            o.get("package_count"),
            o.get("type"),
            o.get("state"),
            o.get("approval_status"),
            o.get("created"),
            o.get("title"),
            # JSON.stringify(o) — no spaces, raw unicode.
            json.dumps(o, ensure_ascii=False, separators=(",", ":")),
        )


def _load_harvest_sources_tx(tx, sources, org_slug_by_uuid) -> None:
    """Insert/upsert the harvest_sources rows. org_slug_by_uuid maps the
    CKAN organisation UUID (organization_id) to its slug (the
    organisations PK) so the join key is denormalised at build time
    instead of read out of the org record's json column on every query."""
    insert_source = tx.prepare(
        """
        INSERT INTO harvest_sources
            (id, title, url, type, active, frequency, organization_id,
             org_slug, created, json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            title = EXCLUDED.title, url = EXCLUDED.url, type = EXCLUDED.type,
            active = EXCLUDED.active, frequency = EXCLUDED.frequency,
            organization_id = EXCLUDED.organization_id,
            org_slug = EXCLUDED.org_slug, created = EXCLUDED.created,
            json = EXCLUDED.json
        """,
    )
    for s in sources:
        insert_source.run(
            s.get("id"),
            s.get("title") or None,
            s.get("url") or None,
            s.get("type") or None,
            s.get("active"),
            s.get("frequency") or None,
            s.get("organization_id") or None,
            org_slug_by_uuid.get(s.get("organization_id")),
            s.get("created") or None,
            # JSON.stringify(s) — no spaces, raw unicode.
            json.dumps(s, ensure_ascii=False, separators=(",", ":")),
        )


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------
def build() -> None:
    """Rebuild the database from downloads/ + organisations.json +
    harvest_sources.json + CSVs."""

    orgs = _load_orgs()
    # CKAN org UUID → slug (the organisations PK) — the harvest sources
    # loader uses it to denormalise org_slug so queries join on the PK.
    org_slug_by_uuid = {o.get("id"): o.get("name") for o in orgs}
    harvest_sources = _load_harvest_sources()
    all_files = _collect_files()

    print(f"Building on {DATABASE_URL}...", file=sys.stderr)
    print(f"  {len(orgs)} organisations", file=sys.stderr)
    print(f"  {len(harvest_sources)} harvest sources", file=sys.stderr)

    db = connect(DATABASE_URL)
    try:
        print(f"  Found {len(all_files)} dataset files to process", file=sys.stderr)

        st = _BuildState()

        # Phase 1: wipe — drop old rows, keep the migrated tables
        db.exec(TRUNCATE_SQL)

        # Phase 2: load organisations
        db.transaction(partial(_load_organisations_tx, orgs=orgs))
        print(f"  {len(orgs)} organisations", file=sys.stderr)

        # Phase 3: load harvest sources (downloads/harvest_sources.json)
        db.transaction(
            partial(
                _load_harvest_sources_tx,
                sources=harvest_sources,
                org_slug_by_uuid=org_slug_by_uuid,
            ),
        )
        print(f"  {len(harvest_sources)} harvest sources", file=sys.stderr)

        # Phase 4: load datasets (batched)
        for i in range(0, len(all_files), READ_BATCH_SIZE):
            _process_batch(db, all_files[i : i + READ_BATCH_SIZE], st)
            if st.count % 10000 == 0 or st.count == len(all_files):
                print(f"  {st.count} datasets...", file=sys.stderr)

        # Indexes are migration-owned (0001) — the build populates, it never
        # creates. On the baseline DB they pre-exist.
        print("  indexes: migration-owned (0001)", file=sys.stderr)

        db.exec("REFRESH MATERIALIZED VIEW mv_org_aggregates")
        # /links/status reads its pre-joined matview; links/datasets/
        # organisations just changed, so rebuild it here too. (check_links
        # refreshes it again once link_check_results change.)
        db.exec("REFRESH MATERIALIZED VIEW mv_link_status")

        link_row = db.prepare("SELECT COUNT(*) AS n FROM links").get()
        link_count = link_row["n"]
        print(
            f"Done: {st.count} datasets ({st.skipped} files skipped), {link_count} resource links.",
        )
        print(f"Index written to {DATABASE_URL}")
    finally:
        db.close()


def main() -> None:
    """Rebuild the database from downloads/ + organisations.json +
    harvest_sources.json + CSVs."""

    try:
        build()
    except SystemExit:
        raise  # exit codes raised inside build() (e.g. missing inputs)
    except (RuntimeError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
