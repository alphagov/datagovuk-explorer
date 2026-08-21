"""GET /metadata — field-adoption overview across the catalogue (top-level
fields and extras keys, sorted by how many datasets use them).
GET /metadata/{section}/{name} — value distribution for one field, paginated.
"""

from django.http import Http404
from django.shortcuts import render

from explorer.queries.datasets import DATASET_TOTAL
from explorer.queries.metadata import METADATA_KEYS, METADATA_VALUE_COUNT, METADATA_VALUES

from .core import paginate


def metadata_overview(request):
    """GET /metadata — list of field keys with dataset counts, one table
    ranked by usage; extras fields carry a badge."""
    # small list — 185 field keys, below the 500-row pagination threshold;
    # renders fully, no pager (see docs/pagination-plan.md).
    keys = METADATA_KEYS.all()
    total_datasets = DATASET_TOTAL.get()["n"]

    # Merge top-level and extras fields into one usage-ranked list. The SQL
    # already orders within section by non_empty, count; sorting again on
    # the same keys just interleaves the two sections.
    rows = sorted(keys, key=lambda k: (k["non_empty"], k["count"]), reverse=True)
    fields: list[dict] = []
    for k in rows:
        extras = k["section"] == "extras"
        fields.append(
            {
                "key": k["key"],
                "section": k["section"],
                "label": k["key"][7:] if extras else k["key"][4:],  # strip prefix
                "extras": extras,
                "count": k["non_empty"],
                "distinct": k["distinct_values"],
                "pct": (k["non_empty"] / total_datasets) * 100,
            },
        )

    return render(
        request,
        "metadata.html",
        {
            "title": "Metadata — data.gov.uk Explorer",
            "section": "metadata",
            "fields": fields,
        },
    )


def metadata_detail(request, section, name):
    """GET /metadata/{section}/{name} — value distribution for one field."""
    # Only top and extras sections exist
    if section not in {"top", "extras"}:
        raise Http404

    full_key = f"{section}:{name}"

    total_values = METADATA_VALUE_COUNT.get(full_key)
    if not total_values or total_values["n"] == 0:
        raise Http404

    # Total datasets that have this field — look up from metadata_keys
    keys = METADATA_KEYS.all()
    key_row = next((k for k in keys if k["key"] == full_key), None)
    dataset_count = key_row["count"] if key_row else 0
    non_empty_count = key_row["non_empty"] if key_row else 0

    total = total_values["n"]
    pagination = paginate(request, total)

    rows = METADATA_VALUES.all(full_key, pagination["page_size"], pagination["offset"])

    display_label = name

    return render(
        request,
        "metadata_values.html",
        {
            "title": f"{display_label} — Metadata — data.gov.uk Explorer",
            "section": "metadata",
            "field_key": full_key,
            "field_label": display_label,
            "dataset_count": dataset_count,
            "non_empty_count": non_empty_count,
            "rows": rows,
            "total": total,
            **pagination,
        },
    )
