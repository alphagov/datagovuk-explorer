"""Populate the metadata_keys and metadata_values tables.

Reads the raw JSON from dataset_json and counts field adoption across the
catalogue: how many datasets have each top-level field and each extras key,
plus a value-distribution sample for the /metadata report.

Idempotent: TRUNCATE + INSERT, so re-running is always safe.

Usage: python -m scripts.build_metadata
"""

import json
from functools import partial

from scripts.db import connect, database_url

DATABASE_URL = database_url()

MAX_FIELD_VALUE_LENGTH = 500

_FETCH_SQL = "SELECT dataset_id, json FROM dataset_json ORDER BY dataset_id"


def _stringify(v) -> str:
    """Stringify a scalar the way it appears in JSON: booleans lowercase
    ('true'/'false'), integral floats rendered without the trailing '.0',
    everything else str()."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def field_value_str(v) -> str:  # noqa: PLR0911
    """Convert a field value to a string for the value-distribution table.
    Long strings/JSON are truncated at 500 chars to keep the index
    reasonable; None, empty string, empty array and empty object all
    collapse to a single "(empty)" bucket so they don't clutter the value
    table as separate rows."""
    if v is None:
        return "(empty)"
    if isinstance(v, str):
        if v == "":
            return "(empty)"
        return v[:MAX_FIELD_VALUE_LENGTH] + "..." if len(v) > MAX_FIELD_VALUE_LENGTH else v
    if isinstance(v, (bool, int, float)):
        return _stringify(v)
    if isinstance(v, list):
        if not v:
            return "(empty)"
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))[:MAX_FIELD_VALUE_LENGTH]
    if isinstance(v, dict):
        s = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        if s == "{}":
            return "(empty)"
        return s[:MAX_FIELD_VALUE_LENGTH]
    return _stringify(v)


def _count_fields(raw: dict, field_counts: dict, value_counts: dict) -> None:
    """Accumulate field usage counts from one dataset's raw JSON."""
    for key, value in raw.items():
        if key.startswith("_") or key in {"resources", "extras"}:
            continue
        fk = f"top:{key}"
        fc = field_counts.setdefault(fk, {"total": 0, "nonEmpty": 0})
        fc["total"] += 1
        vm = value_counts.setdefault(fk, {})
        vs = field_value_str(value)
        vm[vs] = vm.get(vs, 0) + 1
        if vs != "(empty)":
            fc["nonEmpty"] += 1
    seen_extras: set = set()
    for e in raw.get("extras") or []:
        if e["key"] in seen_extras:
            continue
        seen_extras.add(e["key"])
        fk = f"extras:{e['key']}"
        fc = field_counts.setdefault(fk, {"total": 0, "nonEmpty": 0})
        fc["total"] += 1
        vm = value_counts.setdefault(fk, {})
        vs = field_value_str(e.get("value"))
        vm[vs] = vm.get(vs, 0) + 1
        if vs != "(empty)":
            fc["nonEmpty"] += 1


def _write_meta_tx(tx, field_counts: dict, value_counts: dict) -> int:
    """Write the field/value counters into metadata_keys / metadata_values.
    Returns the distinct-value row count."""
    insert_meta_key = tx.prepare(
        "INSERT INTO metadata_keys (key, section, count, non_empty, distinct_values) VALUES (?, ?, ?, ?, ?)",
    )
    insert_meta_val = tx.prepare(
        "INSERT INTO metadata_values (key, value, count) VALUES (?, ?, ?)",
    )
    val_rows = 0
    for fk, fc in field_counts.items():
        section = "extras" if fk.startswith("extras:") else "top"
        vm = value_counts.get(fk)
        distinct = len(vm) if vm else 0
        insert_meta_key.run(fk, section, fc["total"], fc["nonEmpty"], distinct)
        if vm:
            for val, vc in vm.items():
                insert_meta_val.run(fk, val, vc)
                val_rows += 1
    return val_rows


def _populate_metadata(db) -> tuple[int, int]:
    """Rebuild metadata_keys + metadata_values. Returns (field_count, val_rows)."""
    db.exec("TRUNCATE TABLE metadata_values, metadata_keys CASCADE")
    rows = db.prepare(_FETCH_SQL).all()
    field_counts: dict = {}
    value_counts: dict = {}
    for r in rows:
        raw = r["json"] if isinstance(r["json"], dict) else json.loads(r["json"])
        _count_fields(raw, field_counts, value_counts)
    val_rows = db.transaction(
        partial(_write_meta_tx, field_counts=field_counts, value_counts=value_counts),
    )
    return len(field_counts), val_rows


def main() -> None:
    """Rebuild metadata_keys + metadata_values (TRUNCATE + INSERT).

    Reads raw JSON from dataset_json, counts field adoption and value
    distribution, then writes to the metadata tables for the /metadata
    report. Run after ingest_ckan populates dataset_json."""

    db = connect(DATABASE_URL)
    try:
        field_count, val_rows = _populate_metadata(db)
        print(f"build_metadata: {field_count} fields, {val_rows} distinct values")
    finally:
        db.close()


if __name__ == "__main__":
    main()
