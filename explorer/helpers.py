"""Shared helpers for date formatting and theme labels."""

from datetime import UTC, datetime

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


def format_date(iso: str | None) -> str:
    """Format an ISO timestamp as dd/mm/yyyy.

    DB timestamps are naive UTC (`timestamp without time zone`): parsing
    them naively would treat them as local time and shift dates near local
    midnight by a day whenever the server TZ isn't UTC. So keep naive
    values as-is; timestamps with an explicit offset are converted to UTC.
    Invalid input is returned unchanged; falsy input becomes an em-dash.
    """
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)  # accepts trailing "Z" on 3.11+
    except ValueError:
        return iso
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
