# Agents

@readme.md

## Key rules

- `explorer/` and `scripts/` never import from each other — they share only the database.
- The schema is migration-owned. Never manually alter tables.
- Never use background agents, the codebase is small enough that it is quicker not to
- The local database always exists. Do not assume it is missing based on connection errors — check the connection string and `.env` instead.

## Query layer (`explorer/queries/`)

Every database read in the app goes through this package — never the ORM.

- `core.py` defines `Query` and `_fetch_all`: all queries return `list[dict]` (rows as dicts keyed by column name), or `dict | None` for `.get()`.
- Simple queries are module-level `Query("SELECT …")` constants. Complex ones (datasets, with filters/facets/sort) are builder functions that return a `Query`.
- Views import named queries from the relevant module (`from explorer.queries.datasets import …`).
- All SQL uses `%s` placeholders (psycopg3). Literal `%` in LIKE patterns must be doubled (`%%`).

## CSV downloads

Every paginated page offers "Download CSV" from the 3-dots menu beside its pager.
The export is the page's own filtered, sorted query with pagination removed, so
the file can't drift from the table. To add it to a page:

1. **One resolver for the page and the export.** Factor the filter/sort → `{params,
   count, list}` statement resolution into a `_listing(request)` helper in the view
   module. Both the page view and the download view call it; neither rebuilds the
   query itself.
2. **Run the whole listing.** The download uses `queries/core.all_rows(stmt)` (the
   list statement with its `LIMIT/OFFSET` replaced by `EXPORT_ROW_LIMIT` and offset 0).
   Never re-derive the SQL for the export.
3. **Build the attachment** with `explorer/csv_export.csv_response(filename, columns,
   rows[, cell])`. Columns are `(header, row key)` pairs in the view; `cell` is only
   needed for fallback columns (see `views/reports.py::_csv_cell`).
4. **Wire it up:** a `GET <page>/download.csv` route in `config/urls.py`, the view
   exported from `views/__init__.py`, `"download_url": f"<path>/download.csv{pager_base}"`
   in the page context, and `download_url=download_url` on the pagination macro call.
   `page-menu.js` and the menu CSS are global (`_layout.html` / `pagination.css`) — no
   per-page wiring.
5. **Columns:** the table's own columns first, entity GUIDs last (dataset `ckan_id`,
   link `resource_id`, publisher `json::jsonb->>'id'`, harvest source `id`). Dates
   serialise to ISO, `None` to `""`, booleans to `true`/`false`.
6. **Tests:** read exports with `explorer/tests/csv_helpers.csv_rows`; assert the
   unpaginated row count, the header row, and that filters/sort carry through.

Known gap: `csv_response` buffers the whole file in memory and `all_rows` fetches
all rows, so the biggest pages (`/links`, `/datasets`) need a streaming/cursor path
before they get a download. The current exports are small enough not to.

## Tests

Integration tests need a seeded fixture database — run `just fresh-db` first on a clean checkout. They skip automatically if the DB isn't available.

Live smoke tests (`pytest -m live`) run against the full dev database separately: `just test-live`.

Performance observation tests (`pytest -m perf`) are not correctness checks — they write a dated report to `docs/perf/YYYY-MM-DD/`. Run with `just perf`.
