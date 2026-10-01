# Agents

@readme.md

## Key rules

- `explorer/` and `scripts/` never import from each other — they share only the database.
- The schema is migration-owned. Never manually alter tables.

## Query layer (`explorer/queries/`)

Every database read in the app goes through this package — never the ORM.

- `core.py` defines `Query` and `_fetch_all`: all queries return `list[dict]` (rows as dicts keyed by column name), or `dict | None` for `.get()`.
- Simple queries are module-level `Query("SELECT …")` constants. Complex ones (datasets, with filters/facets/sort) are builder functions that return a `Query`.
- Views import named queries from the relevant module (`from explorer.queries.datasets import …`).
- All SQL uses `%s` placeholders (psycopg3). Literal `%` in LIKE patterns must be doubled (`%%`).

## Tests

Integration tests need a seeded fixture database — run `just fresh-db` first on a clean checkout. They skip automatically if the DB isn't available.

Live smoke tests (`pytest -m live`) run against the full dev database separately: `just test-live`.
