"""GET /datasets — all datasets across all orgs.

Server-side sortable via ?sort= & ?dir= and filterable via the sidebar
facets — primary theme (?theme=), publisher (?publisher=<org slug>),
source (?source=harvested|manual), creation year (?year=), link count
(?links=, the count-bucket facet), temporal coverage year (?temporal=)
and metadata key/value (?metadata_key=&metadata_value=, linked from the
/metadata value pages) — paginated (100/page).

Sidebar facet counts are SQL aggregates from explorer/queries/datasets.py
(datasets_facet_counts) over the same WHERE builder the page list/count use
(datasets_stmts) — one clause builder, both consumers.
"""

import functools
import re
from dataclasses import asdict, dataclass
from urllib.parse import urlencode

from django.shortcuts import render

from explorer import facets
from explorer.helpers import theme_label
from explorer.queries.datasets import (
    DATASET_TOTAL,
    DATASETS_SORT,
    DATASETS_SORT_DEFAULT,
    LINK_BUCKET_NAMES,
    LINK_BUCKETS,
    TEMPORAL_MAX_YEAR,
    TEMPORAL_MIN_YEAR,
    TEMPORAL_YEARS,
    THEME_COUNTS,
    VALID_LINK_BUCKETS,
    dataset_created_years,
    datasets_facet_counts,
    datasets_stmts,
    fetched_slugs,
    harvested_count,
)
from explorer.sort import parse_sort

from .core import _pill, paginate

# In-window temporal years (latest first) — filter-independent, memoised at
# module level (the DB is a build-time snapshot, so the result is stable).


@functools.cache
def _in_window_temporal_years() -> list[int]:
    return [r["year"] for r in TEMPORAL_YEARS.all()]


@functools.cache
def _theme_master() -> list[dict]:
    """Full theme list + counts — the filter-independent master list the
    validation whitelist and the theme facet items both come from. The
    no-theme bucket is a regular master member under the value-space slug
    "none", so the master sort places it (first, with current data)."""
    theme_counts = {r["theme"]: r["count"] for r in THEME_COUNTS.all()}
    themes = [
        {"slug": slug, "label": theme_label(slug), "count": count}
        for slug, count in theme_counts.items()
        if slug != "__none__"
    ]
    themes.append({"slug": "none", "label": "No theme", "count": theme_counts.get("__none__", 0)})
    themes.sort(key=lambda t: (-t["count"], t["label"].lower()))
    return themes


@functools.cache
def _created_year_master() -> list[str]:
    """Created-year facet master list — latest first (filter-independent)."""
    return dataset_created_years()


@dataclass(frozen=True)
class DatasetsFilters:
    """The eight validated /datasets facet selections (None = not active)."""

    theme: str | None
    publisher: str | None
    source: str | None
    links: str | None
    created_year: str | None
    temporal_year: str | None
    metadata_key: str | None
    metadata_value: str | None
    api: str | None


def _parse_filters(
    request,
    valid_slugs,
    valid_publishers,
    valid_created_years,
    valid_temporal_years,
) -> DatasetsFilters:
    """Validate the /datasets facet selections from request.GET.

    Each facet has the same shape: take request.GET, validate against a
    whitelist, return None or the value. The theme/temporal special values
    ("none", "pre1900", "post") are selections in their own right, not
    slugs/years. The publisher value is an org slug (validated against the
    orgs that actually own datasets). The metadata filter is a key/value
    pair — both must be present and the key must match the top:/extras:
    metadata sections.
    """
    theme = request.GET.get("theme")
    current_theme = None
    if theme == "none":
        current_theme = "none"
    elif theme in valid_slugs:
        current_theme = theme

    publisher = request.GET.get("publisher")
    current_publisher = publisher if publisher in valid_publishers else None

    source = request.GET.get("source")
    current_source = source if source in ("harvested", "manual") else None

    links = request.GET.get("links")
    current_links = links if links in VALID_LINK_BUCKETS else None

    created_year = request.GET.get("created_year")
    current_created_year = created_year if created_year in valid_created_years else None

    temporal_year = request.GET.get("temporal_year")
    current_temporal_year = None
    if temporal_year == "none":
        current_temporal_year = "none"
    elif temporal_year == "pre1900":
        current_temporal_year = "pre1900"
    elif temporal_year == "post":
        current_temporal_year = "post"
    elif temporal_year in valid_temporal_years:
        current_temporal_year = temporal_year

    metadata_key = request.GET.get("metadata_key")
    metadata_value = request.GET.get("metadata_value")
    current_metadata_key = None
    current_metadata_value = None
    if metadata_key is not None and re.match(r"^(top|extras):.+", metadata_key) and metadata_value is not None:
        current_metadata_key = metadata_key
        current_metadata_value = metadata_value

    api = request.GET.get("api")
    current_api = api if api in ("data-apis", "map-layers") else None

    return DatasetsFilters(
        theme=current_theme,
        publisher=current_publisher,
        source=current_source,
        links=current_links,
        created_year=current_created_year,
        temporal_year=current_temporal_year,
        metadata_key=current_metadata_key,
        metadata_value=current_metadata_value,
        api=current_api,
    )


def _active_labels(filters: DatasetsFilters) -> dict[str, str | None]:
    """Human-readable labels for the active theme/temporal/metadata filters
    (used by the active-filter pills and the sidebar)."""
    theme_label_active = (
        "No theme" if filters.theme == "none" else theme_label(filters.theme) if filters.theme else None
    )

    temporal_label = (
        "No temporal year"
        if filters.temporal_year == "none"
        else f"Before {TEMPORAL_MIN_YEAR}"
        if filters.temporal_year == "pre1900"
        else f"After {TEMPORAL_MAX_YEAR}"
        if filters.temporal_year == "post"
        else filters.temporal_year
    )

    metadata_label = (
        f"{filters.metadata_key.split(':')[1]} = {filters.metadata_value}"
        if filters.metadata_key and filters.metadata_value
        else None
    )

    return {
        "theme_label": theme_label_active,
        "temporal_label": temporal_label,
        "metadata_label": metadata_label,
    }


_API_NAMES = {"data-apis": "Data API", "map-layers": "Map layers"}


def datasets(request):  # noqa: PLR0915
    """GET /datasets — the all-datasets report with sidebar facets."""
    fetched_slug_rows = fetched_slugs()
    harvested_count_value = harvested_count()

    # Filter-independent master lists — the validation whitelists and the
    # facet builders consume these (computed once, not per consumer).
    themes = _theme_master()
    created_years = _created_year_master()
    temporal_years = _in_window_temporal_years()
    filters = _parse_filters(
        request,
        {t["slug"] for t in themes},
        {r["org_slug"] for r in fetched_slug_rows},
        set(created_years),
        {str(y) for y in temporal_years},
    )

    # Sidebar facet counts — each group counts over the pool filtered by
    # every other group (the metadata filter is deliberately excluded).
    facet_counts = datasets_facet_counts(
        {
            "theme": filters.theme,
            "publisher": filters.publisher,
            "source": filters.source,
            "links": filters.links,
            "created_year": filters.created_year,
            "temporal_year": filters.temporal_year,
            "api": filters.api,
        },
    )

    sort, dir_ = parse_sort(request, DATASETS_SORT, *DATASETS_SORT_DEFAULT)

    # Query-string base shared by sort links / facet links / pills and the
    # temporal-year / publisher More toggles. preserve_params gives the
    # ordered base (sort, dir, then each active facet in a fixed order, then
    # the expanded-lists extras — ?temporal_years=all / ?publishers=all);
    # facet_qs drops sort/dir for the sort_link/pagination macros.
    temporal_year_expanded = request.GET.get("temporal_years") == "all"
    publisher_expanded = request.GET.get("publishers") == "all"
    # Theme and created-year lists also collapse past the default cutoff
    # behind their own More toggles (?themes=all / ?created_years=all).
    theme_expanded = request.GET.get("themes") == "all"
    created_year_expanded = request.GET.get("created_years") == "all"
    expanded_extras = {}
    if temporal_year_expanded:
        expanded_extras["temporal_years"] = "all"
    if publisher_expanded:
        expanded_extras["publishers"] = "all"
    if theme_expanded:
        expanded_extras["themes"] = "all"
    if created_year_expanded:
        expanded_extras["created_years"] = "all"
    base_params = facets.preserve_params(
        sort,
        dir_,
        [
            ("theme", filters.theme),
            ("publisher", filters.publisher),
            ("source", filters.source),
            ("links", filters.links),
            ("created_year", filters.created_year),
            ("temporal_year", filters.temporal_year),
            ("api", filters.api),
            ("metadata_key", filters.metadata_key),
            ("metadata_value", filters.metadata_value),
        ],
        expanded_extras or None,
        defaults=DATASETS_SORT_DEFAULT,
    )

    # --- Sidebar facet groups (pool counts + current selection -> group) ---
    # The temporal-year facet's trailing buckets — After/Before/No-year —
    # trail the year list and only render when their pools are non-empty.
    temporal_buckets = facet_counts["temporal_buckets"]
    trailing_items = []
    if temporal_buckets["post"]:
        trailing_items.append(
            {
                "value": "post",
                "name": f"After {TEMPORAL_MAX_YEAR}",
                "count": temporal_buckets["post"],
                "active": filters.temporal_year == "post",
            },
        )
    if temporal_buckets["pre1900"]:
        trailing_items.append(
            {
                "value": "pre1900",
                "name": f"Before {TEMPORAL_MIN_YEAR}",
                "count": temporal_buckets["pre1900"],
                "active": filters.temporal_year == "pre1900",
            },
        )
    if temporal_buckets["none"]:
        trailing_items.append(
            {
                "value": "none",
                "name": "No temporal year",
                "count": temporal_buckets["none"],
                "active": filters.temporal_year == "none",
            },
        )

    # Theme pool counts use the value-space "none" slug (the SQL returns
    # __none__); the theme master already carries "none" as a member.
    theme_pool_counts = {
        ("none" if r["theme"] == "__none__" else r["theme"]): r["count"] for r in facet_counts["themes"]
    }
    # Publisher pool returns every publisher in it (count desc) with its
    # display name, so the same rows feed the master list, the item counts
    # and the pill-name lookup. The value-space is the org slug — same key
    # the row links to /organisation/<slug> with.
    publisher_pool = facet_counts["publishers"]
    publisher_names = {p["value"]: p["name"] for p in publisher_pool}
    facet_groups = {
        g["key"]: g
        for g in (
            facets.facet_counts_group(
                "theme",
                "Theme",
                "Filter by primary theme",
                [(t["slug"], t["label"]) for t in themes],
                theme_pool_counts,
                filters.theme,
                proportions=True,
                plural="themes",
                toggle_base=base_params,
                expanded=theme_expanded,
            ),
            # Every publisher with datasets is a facet — the long list
            # collapses past the default cutoff behind the standard "More
            # publishers" toggle (?publishers=all), like the temporal
            # years list.
            facets.facet_counts_group(
                "publisher",
                "Publisher",
                "Filter by publisher",
                [(p["value"], p["name"]) for p in publisher_pool],
                {p["value"]: p["count"] for p in publisher_pool},
                filters.publisher,
                proportions=True,
                plural="publishers",
                toggle_base=base_params,
                expanded=publisher_expanded,
            ),
            facets.facet_counts_group(
                "api",
                "API",
                "Filter by API type",
                [("data-apis", "Data API"), ("map-layers", "Map layers")],
                {r["api"]: r["count"] for r in facet_counts["api"]},
                filters.api,
                proportions=True,
            ),
            facets.facet_counts_group(
                "source",
                "Source",
                "Filter by source",
                [("harvested", "Harvested"), ("manual", "Manual")],
                facet_counts["source"],
                filters.source,
                proportions=True,
            ),
            facets.facet_counts_group(
                "links",
                "Links",
                "Filter by number of links",
                [(value, name) for value, name in LINK_BUCKETS],
                {r["bucket"]: r["count"] for r in facet_counts["links"]},
                filters.links,
                proportions=True,
            ),
            facets.facet_counts_group(
                "created_year",
                "Year created",
                "Filter by year created",
                [(y, y) for y in created_years],
                {r["created_year"]: r["count"] for r in facet_counts["created_years"]},
                filters.created_year,
                proportions=True,
                plural="created years",
                toggle_base=base_params,
                expanded=created_year_expanded,
            ),
            facets.facet_counts_group(
                "temporal_year",
                "Temporal year",
                "Filter by temporal year",
                [(str(y), str(y)) for y in temporal_years],
                {str(r["year"]): r["count"] for r in facet_counts["temporal_years"]},
                filters.temporal_year,
                plural="temporal years",
                toggle_base=base_params,
                expanded=temporal_year_expanded,
                trailing=trailing_items,
                always_render=True,
            ),
        )
        if g is not None
    }

    # Datasets matching all active filters — count + page in SQL
    stmts_out = datasets_stmts(asdict(filters), sort, dir_)
    shown_count = stmts_out["count"].get(*stmts_out["params"])["n"]

    pagination = paginate(request, shown_count)
    page_datasets = stmts_out["list"].all(*stmts_out["params"], pagination["page_size"], pagination["offset"])

    labels = _active_labels(filters)

    # The publisher pill shows the display name (the value-space is the
    # slug). The pool always holds the selected publisher — its own filter
    # is excluded from the pool — except when the other filters rule it
    # out entirely, where the slug is the best we can do.
    publisher_label = publisher_names.get(filters.publisher, filters.publisher) if filters.publisher else None

    base_facet_url = facets.facet_url_for(base_params)
    facet_qs = facets.facet_qs(base_params, include_sort=False)
    pager_base = facets.pager_base(base_params)

    def facet_url(key: str, value: str) -> str:
        # The metadata filter is a key+value pair: clearing the key drops
        # the value too (a lone metadata_value is invalid anyway).
        if key == "metadata_key" and not value:
            params = dict(base_params)
            params.pop("metadata_key", None)
            params.pop("metadata_value", None)
            return f"?{urlencode(params)}" if params else "?"
        return base_facet_url(key, value)

    source_name = "Harvested" if filters.source == "harvested" else "Manual"
    pills = [
        _pill("Theme", labels["theme_label"], facet_url("theme", "")) if filters.theme else None,
        _pill("Publisher", publisher_label, facet_url("publisher", "")) if filters.publisher else None,
        _pill("API", _API_NAMES[filters.api], facet_url("api", "")) if filters.api else None,
        _pill("Source", source_name, facet_url("source", "")) if filters.source else None,
        _pill("Links", LINK_BUCKET_NAMES[filters.links], facet_url("links", "")) if filters.links else None,
        _pill("Created year", filters.created_year, facet_url("created_year", "")) if filters.created_year else None,
        _pill("Temporal year", labels["temporal_label"], facet_url("temporal_year", ""))
        if filters.temporal_year
        else None,
        _pill("Metadata", labels["metadata_label"], facet_url("metadata_key", "")) if filters.metadata_key else None,
    ]

    return render(
        request,
        "datasets.html",
        {
            "title": "All datasets — data.gov.uk Explorer",
            "nav_key": "datasets",
            "datasets": page_datasets,
            **pagination,
            "total_datasets": DATASET_TOTAL.get()["n"],
            "shown_datasets": shown_count,
            "total_orgs": len(fetched_slug_rows),
            "harvested_count": harvested_count_value,
            "pills": pills,
            "sort": sort,
            "dir": dir_,
            "facet_groups": facet_groups,
            "facet_qs": facet_qs,
            "facet_url": facet_url,
            "pager_base": pager_base,
        },
    )
