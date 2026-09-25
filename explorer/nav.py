"""The site nav in one place.

A view sets `nav_key` to its page key; the layouts derive the top-nav
highlight and the section sub-nav from it.
"""

PRIMARY_NAV = [
    {"key": "dashboard", "label": "Home", "url": "/"},
    {"key": "orgs", "label": "Publishers", "url": "/organisations"},
    {"key": "datasets", "label": "Datasets", "url": "/datasets"},
    {"key": "collections", "label": "Collections", "url": "/collections"},
    {"key": "links", "label": "Links", "url": "/links"},
    {"key": "metadata", "label": "Metadata", "url": "/metadata"},
]

# Section key -> its child report pages, in nav order. The first is the
# landing page and supplies the sub-nav's label.
SECTIONS = {
    "orgs": [
        {"key": "orgs", "label": "Publishers", "url": "/organisations"},
        {"key": "harvesters", "label": "Harvesters", "url": "/harvesters"},
    ],
    "datasets": [
        {"key": "datasets", "label": "Datasets", "url": "/datasets"},
        {"key": "series", "label": "Series", "url": "/series"},
        {"key": "reviews", "label": "Reviews", "url": "/reviews"},
        {"key": "suggestions", "label": "Suggestions", "url": "/suggestions"},
    ],
    "links": [
        {"key": "links", "label": "Links", "url": "/links"},
        {"key": "errors", "label": "Status", "url": "/links/status"},
    ],
}

_TAB_SECTION = {tab["key"]: key for key, tabs in SECTIONS.items() for tab in tabs}

# Tab pages highlight their own section; detail pages highlight the section
# they belong to. Anything else (search, 404) has no nav item.
_PAGE_SECTION = _TAB_SECTION | {
    "organisation": "orgs",
    "harvester": "orgs",
    "dataset": "datasets",
    "series-detail": "datasets",
    "collections": "collections",
    "dashboard": "dashboard",
    "metadata": "metadata",
    "search": "search",
}


def section_for(page_key: str) -> str | None:
    """Top-nav section key for a page, or None if it has no nav item."""
    return _PAGE_SECTION.get(page_key)


def subnav_for(page_key: str) -> dict | None:
    """`{label, tabs}` for a section tab page, else None."""
    section = _TAB_SECTION.get(page_key)
    if section is None:
        return None
    tabs = SECTIONS[section]
    return {"label": tabs[0]["label"], "tabs": tabs}
