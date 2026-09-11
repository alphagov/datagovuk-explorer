"""Cross-section search queries for /search."""

from .core import Query, fetch_parallel

PREVIEW_LIMIT = 5
SEARCH_PAGE_SIZE = 25

# ── Publishers ────────────────────────────────────────────────────────────────

_PUBLISHERS_PREVIEW = Query(
    """SELECT slug,
              COALESCE(display_name, title, name) AS display_name,
              COALESCE(package_count, 0) AS package_count
         FROM organisations
        WHERE COALESCE(display_name, title, name, '') ILIKE %s
        ORDER BY LOWER(COALESCE(display_name, title, name))
        LIMIT %s""",
)

_PUBLISHERS_COUNT = Query(
    """SELECT COUNT(*) AS n
         FROM organisations
        WHERE COALESCE(display_name, title, name, '') ILIKE %s""",
)

_PUBLISHERS_PAGE = Query(
    """SELECT slug,
              COALESCE(display_name, title, name) AS display_name,
              COALESCE(package_count, 0) AS package_count
         FROM organisations
        WHERE COALESCE(display_name, title, name, '') ILIKE %s
        ORDER BY LOWER(COALESCE(display_name, title, name))
        LIMIT %s OFFSET %s""",
)

# ── Datasets ──────────────────────────────────────────────────────────────────

_DATASETS_PREVIEW = Query(
    """WITH q AS (SELECT websearch_to_tsquery('english', %s) AS q)
       SELECT d.id, d.org_slug, d.title, d.org_display_name,
              ts_rank(d.fts, q.q) AS rank
         FROM datasets d, q
        WHERE d.fts @@ q.q
        ORDER BY rank DESC, d.title
        LIMIT %s""",
)

_DATASETS_COUNT = Query(
    """WITH q AS (SELECT websearch_to_tsquery('english', %s) AS q)
       SELECT COUNT(*) AS n FROM datasets d, q WHERE d.fts @@ q.q""",
)

_DATASETS_PAGE = Query(
    """WITH q AS (SELECT websearch_to_tsquery('english', %s) AS q)
       SELECT d.id, d.org_slug, d.title, d.org_display_name,
              ts_rank(d.fts, q.q) AS rank
         FROM datasets d, q
        WHERE d.fts @@ q.q
        ORDER BY rank DESC, d.title
        LIMIT %s OFFSET %s""",
)

# ── Public API ────────────────────────────────────────────────────────────────

def search_all(q: str) -> dict:
    """Preview + counts for both sections, all in parallel. Returns:
      { 'publishers': [...], 'publisher_count': int,
        'datasets': [...],   'dataset_count': int }
    """
    like = f"%{q}%"
    publishers, pub_count, datasets, ds_count = fetch_parallel([
        lambda: _PUBLISHERS_PREVIEW.all(like, PREVIEW_LIMIT),
        lambda: (_PUBLISHERS_COUNT.get(like) or {}).get("n", 0),
        lambda: _DATASETS_PREVIEW.all(q, PREVIEW_LIMIT),
        lambda: (_DATASETS_COUNT.get(q) or {}).get("n", 0),
    ])
    return {
        "publishers": publishers,
        "publisher_count": pub_count,
        "datasets": datasets,
        "dataset_count": ds_count,
    }


def search_publishers_page(q: str, offset: int) -> list[dict]:
    like = f"%{q}%"
    return _PUBLISHERS_PAGE.all(like, SEARCH_PAGE_SIZE, offset)


def search_datasets_page(q: str, offset: int) -> list[dict]:
    return _DATASETS_PAGE.all(q, SEARCH_PAGE_SIZE, offset)


def count_publishers(q: str) -> int:
    like = f"%{q}%"
    return (_PUBLISHERS_COUNT.get(like) or {}).get("n", 0)


def count_datasets(q: str) -> int:
    return (_DATASETS_COUNT.get(q) or {}).get("n", 0)
