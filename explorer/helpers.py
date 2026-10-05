"""Shared helpers for date formatting and theme labels."""

from datetime import UTC, date, datetime

# data.gov.uk primary theme slugs → display labels
THEME_LABELS = {
    "towns-and-cities": "Towns & Cities",
    "government-spending": "Government Spending",
    "environment": "Environment",
    "government": "Government",
    "mapping": "Mapping",
    "crime-and-justice": "Crime & Justice",
    "transport": "Transport",
    "society": "Society",
    "business-and-economy": "Business & Economy",
    "education": "Education",
    "health": "Health",
    "defence": "Defence",
    "digital-services-performance": "Digital Services Performance",
}


def format_date(value: str | datetime | date | None) -> str:
    """Format a timestamp/date as dd/mm/yyyy.

    Accepts a real `datetime`/`date` (the typed DB columns) and an ISO
    string — the latter for values that come from JSON rather than a column
    (dataset resource `last_modified`/`created`, harvest `next_run`). Naive
    datetimes are treated as UTC (that is the DB convention now); aware ones
    are converted to UTC before formatting so the displayed day can't shift
    with the session timezone. Falsy input becomes an em-dash; an unparseable
    string is returned unchanged.
    """
    if not value:
        return "—"
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        # A plain date (e.g. collection_pages.page_last_updated) has no
        # time or zone to resolve.
        return f"{value.day:02d}/{value.month:02d}/{value.year}"
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)  # accepts trailing "Z" on 3.11+
        except ValueError:
            return value
    else:
        return str(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    # Manual zero-padding — strftime would resolve the timezone on every
    # call, and this runs per row on the big pages.
    d = dt.date()
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def theme_label(slug: str) -> str:
    """Convert a theme slug into a readable label (fallback: title-case the slug)."""
    if slug in THEME_LABELS:
        return THEME_LABELS[slug]
    return " ".join(w[:1].upper() + w[1:] for w in slug.split("-"))
