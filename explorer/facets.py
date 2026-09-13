"""Shared sidebar-facet machinery for the facet pages
(/organisations, /links, /datasets and the /report/{key} reports).

Two layers live here:

1. Query-string bookkeeping — the ordered ?query base every link on a
   page keeps, and the URL builders derived from it:

   - preserve_params(): the base — sort and dir first (omitted when they
     match the page defaults), then each active facet (key, value) pair in
     a fixed order, then extras (the expanded-lists toggles, ?formats=all /
     ?years=all)
   - facet_url_for(): the facet_url(key, value) closure built from that
     base — keep the base, set one facet value or clear it
   - facet_qs(): the "&…" fragment appended to ?sort=..&dir=.. by the
     sort_link / pagination macros (optionally without the sort/dir keys
     the macros supply themselves)
   - facet_toggle_url(): the show-more toggle href for a facet list
     (?param=all when expanding, minus it when collapsing)

2. Counts → facet-group assembly — the shared builders every page's view
   calls:

   - facet_counts_group(): single-select — an ordered master list of
     possible values, a {value: count} pool, the selected value, and the
     page's base params; returns the facet_group() dict with items
     (active/count, optional proportion), optional show-more toggle
     wiring (cutoff/toggle_base/toggle_param/expanded/list_id) and
     optional trailing buckets
   - facet_counts_multiselect_group(): multi-select variant (the
     organisations pubyear facet) — each item carries a toggle href that
     adds/removes one value from the selection; optional trailing
     buckets (the "Never published" bucket) render after the items

   The builders are agnostic to how `counts` was computed — every facet
   page computes its pools through the shared core.facet_where helper
   (queries/core.py), each group excluding its own facet, and these
   builders only consume the resulting {value: count} dict. Self-exclusion
   stays the caller's responsibility; the rendering layer never needs to
   know how a count was computed.

- facet_group(): the group dict shape the templates iterate (key, label,
  aria_label, items, plus optional list_id / expanded / more / trailing
  keys for the toggle-able lists)
"""

from urllib.parse import urlencode

# Items a toggled facet list shows before collapsing — override per group
# with cutoff=<n>, or None to keep the list fully shown.
DEFAULT_CUTOFF = 10


def _toggle_param(plural: str) -> str:
    """The ?…=all expand param for a facet list — the plural slugged
    (spaces → underscores: "temporal years" → temporal_years). Views read it
    for the initial expanded state; the builder derives the same slug from
    the same plural, so the toggle hrefs and the reads can't drift."""
    return plural.replace(" ", "_")


def preserve_params(sort, dir_, facets, extras=None, defaults=None):
    """Ordered query-string base: ?sort= & ?dir= first, then each active
    (key, value) facet pair in order, then extras (e.g. {'formats': 'all'}).

    `defaults` is the page's (default_sort, default_dir) pair. When the
    current sort matches it the sort/dir keys are omitted, so links from a
    table the user hasn't sorted don't carry a redundant ?sort=..&dir=..
    (the view falls back to the same defaults on the next request)."""
    params = {}
    if defaults is None or (sort, dir_) != (defaults[0], defaults[1]):
        params["sort"] = sort
        params["dir"] = dir_
    params.update({key: value for key, value in facets if value})
    if extras:
        params.update(extras)
    return params


def sort_params(sort, dir_, defaults=None):
    """The sort-only query base for pages without facets (their pager links) —
    {'sort': .., 'dir': ..}, or {} when they match the page default. Same
    default-skipping rule as preserve_params, so a default sort never leaks
    into pagination URLs either."""
    return preserve_params(sort, dir_, [], defaults=defaults)


def facet_url_for(base_params):
    """facet_url(key, value) — keep the base (sort + dir + active facets),
    set one facet value, or clear it (value == '')."""

    def facet_url(key, value):
        params = dict(base_params)
        if value:
            params[key] = value
        else:
            params.pop(key, None)
        return f"?{urlencode(params)}" if params else "?"

    return facet_url


def facet_qs(base_params, *, include_sort=True):
    """The "&…" fragment appended to ?sort=..&dir=.. by the sort_link and
    pagination macros. include_sort=False drops the sort/dir keys (the
    macros supply those themselves). Empty base → "" (no leading &)."""
    params = dict(base_params)
    if not include_sort:
        params.pop("sort", None)
        params.pop("dir", None)
    qs = urlencode(params)
    return f"&{qs}" if qs else ""


def pager_base(base_params, *, include_sort=True):
    """The "?…" base fragment for the pagination macro — the
    ordered base params (sort, dir, then each active facet) as a
    ?-prefixed query string, exactly the fragment the macros append
    "&page=N" to. include_sort=False drops sort/dir (pages with no sort
    UI — reports: the SQL order is fixed, the URL stops pretending).
    Empty params → "" (clean "?page=N")."""
    params = dict(base_params)
    if not include_sort:
        params.pop("sort", None)
        params.pop("dir", None)
    qs = urlencode(params)
    return f"?{qs}" if qs else ""


def facet_toggle_url(base_params, param, *, expanded):
    """?url for a facet list's show-more toggle — base params plus
    param=all when expanding, minus it when collapsing."""
    params = dict(base_params)
    if expanded:
        params[param] = "all"
    else:
        params.pop(param, None)
    return f"?{urlencode(params)}" if params else "?"


def facet_group(key, label, aria_label, items, **extra):
    """Facet group dict — the shape the report templates iterate. Extra
    kwargs land on the group (list_id / expanded / more / trailing, used
    by the toggle-able lists on /links and /datasets)."""
    return {
        "key": key,
        "label": label,
        "aria_label": aria_label,
        "items": items,
        **extra,
    }


def _master_pairs(master):
    """(value, name) pairs from a master list — either (value, name)
    tuples or dicts with value/name keys."""
    for m in master:
        if isinstance(m, dict):
            yield m["value"], m["name"]
        else:
            yield m[0], m[1]


def _toggle_wiring(key, plural, toggle_param, toggle_label, list_id):
    """Toggle defaults from the facet's explicit plural (expand param =
    slug, label = plural) and key (list id); explicit toggle_param/
    toggle_label/list_id take precedence. Returns (toggleable, param, label,
    list_id) — toggleable when a param resolved."""
    if plural:
        toggle_param = toggle_param if toggle_param is not None else _toggle_param(plural)
        toggle_label = toggle_label if toggle_label is not None else plural
    return toggle_param is not None, toggle_param, toggle_label, list_id or f"{key}-facet-list"


def facet_counts_group(
    key,
    label,
    aria_label,
    master,
    counts,
    current,
    *,
    proportions=False,
    cutoff=DEFAULT_CUTOFF,
    plural=None,
    toggle_base=None,
    toggle_param=None,
    toggle_label=None,
    expanded=False,
    list_id=None,
    trailing=None,
    always_render=False,
    search=None,
):
    """Single-select facet group: ordered master + pool counts → group dict.

    master is the ordered list of possible values — a list of (value,
    name) tuples or of dicts with value/name keys — and the render order
    is exactly that master order. counts maps value → count for the
    current pool; current is the selected value (or None). The caller
    owns the counting semantics (self-excluding SQL aggregates,
    fixed aggregates or Python-side buckets) — the builder only renders
    the counts it's given. Items whose value is absent from the pool
    (count 0 / missing) are omitted, so the group is None when the pool
    is empty unless always_render is set.

    Options:
    - proportions: each item gains proportion = count / max pool count
      (the --facet-prop CSS bar; opt-in — /links doesn't use it)
    - plural + cutoff: opts the list into the toggle machinery. plural is
      the facet's explicit plural noun ("domains", "temporal years") — the
      "More …" text and, slugged (spaces → underscores), the ?<plural>=all
      expand param. A list longer than cutoff (default DEFAULT_CUTOFF;
      None = always fully shown) marks items from cutoff on as `extra`
      (hidden until expanded) and gains list_id/expanded plus the `more`
      toggle dict. Lists without a plural never collapse, so values can't
      be stranded behind nothing.
    - toggle_base/toggle_param/toggle_label/expanded/list_id: overrides.
      toggle_base is the page's ordered base params the toggle href keeps
      (facet_toggle_url); toggle_param/toggle_label and list_id default
      from plural/key; expanded is the initial state (views read
      ?<param>=all).
    - trailing: item dicts rendered after the items (and after the more
      toggle) — the "No URL" bucket on /links, the temporal After/
      Before/No-year buckets on /datasets
    - always_render: return the group even when the pool is empty (the
      /datasets temporal facet always renders)
    - search: a placeholder string (e.g. "Search publishers") that opts
      the group into a live client-side search box above the list (driven
      by explorer/static/facet-search.js). While a search term is active
      the list shows every matching value regardless of the More-toggle
      collapse, so searching covers all values in the pool, not just the
      visible cut-off; the group gains the `search` key verbatim.
    """
    pool_max = max(counts.values(), default=1)
    toggleable, toggle_param, toggle_label, list_id = _toggle_wiring(
        key,
        plural,
        toggle_param,
        toggle_label,
        list_id,
    )

    items = []
    for i, (value, name) in enumerate(_master_pairs(master)):
        count = counts.get(value, 0)
        if count <= 0:
            continue
        item = {
            "value": value,
            "name": name,
            "count": count,
            "active": current == value,
        }
        if proportions:
            item["proportion"] = count / pool_max
        if toggleable and cutoff is not None:
            item["extra"] = not expanded and i >= cutoff
        items.append(item)

    if not items and not always_render:
        return None

    group = facet_group(key, label, aria_label, items)
    if search:
        group["search"] = search
    if toggleable and cutoff is not None and len(items) > cutoff:
        group["list_id"] = list_id
        group["expanded"] = expanded
        group["more"] = {
            "href": facet_toggle_url(toggle_base or {}, toggle_param, expanded=not expanded),
            "expanded": expanded,
            "count": len(items) - cutoff,
            "label": toggle_label,
            "param": toggle_param,
        }
    if trailing:
        group["trailing"] = trailing
    return group


def facet_counts_multiselect_group(
    key,
    label,
    aria_label,
    master,
    counts,
    current,
    *,
    facet_url,
    proportions=False,
    cutoff=DEFAULT_CUTOFF,
    plural=None,
    toggle_base=None,
    toggle_param=None,
    toggle_label=None,
    expanded=False,
    list_id=None,
    trailing=None,
):
    """Multi-select facet group — the organisations year-last-published case.

    Same inputs as facet_counts_group, but current is a collection and
    every item carries a per-item toggle href built from the passed-in
    facet_url(key, value) closure: clicking a selected value removes it
    from the selection (clearing the facet when it was the last one),
    clicking an unselected value adds it. When nothing is selected no
    hrefs are set (the template falls back to the plain facet_url).
    plural + cutoff behave exactly as in facet_counts_group: lists longer
    than the cutoff collapse behind the shared More toggle (derived
    param/label/list_id), expanded is the initial state. trailing lands on
    the group verbatim — post-list buckets rendered after the items (the
    "Never published" bucket), each carrying its own href (the plain
    facet_url fallback would replace the selection, not clear it when
    active)."""
    pool_max = max(counts.values(), default=1)
    toggleable, toggle_param, toggle_label, list_id = _toggle_wiring(
        key,
        plural,
        toggle_param,
        toggle_label,
        list_id,
    )

    items = []
    for i, (value, name) in enumerate(_master_pairs(master)):
        count = counts.get(value, 0)
        if count <= 0:
            continue
        is_included = bool(current and value in current)
        item = {
            "value": value,
            "name": name,
            "count": count,
            "active": is_included,
        }
        if current:
            rest = [x for x in current if x != value]
            if is_included:
                item["href"] = facet_url(key, ",".join(rest)) if rest else facet_url(key, "")
            else:
                item["href"] = facet_url(key, value)
        if proportions:
            item["proportion"] = count / pool_max
        if toggleable and cutoff is not None:
            item["extra"] = not expanded and i >= cutoff
        items.append(item)

    if not items and not trailing:
        return None
    group = facet_group(key, label, aria_label, items)
    if toggleable and cutoff is not None and len(items) > cutoff:
        group["list_id"] = list_id
        group["expanded"] = expanded
        group["more"] = {
            "href": facet_toggle_url(toggle_base or {}, toggle_param, expanded=not expanded),
            "expanded": expanded,
            "count": len(items) - cutoff,
            "label": toggle_label,
            "param": toggle_param,
        }
    if trailing:
        group["trailing"] = trailing
    return group
