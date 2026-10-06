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

Every paginated page offers "Download CSV" from the 3-dots page-actions menu
beside its pager (the `page_menu` macro — separate from `pagination`, so pages
without a pager can offer it too). The export is the page's own filtered,
sorted query with pagination removed, so the file can't drift from the table.
To add it to a page:

1. **One resolver for the page and the export.** Factor the filter/sort → `{params,
   count, list}` statement resolution into a `_listing(request)` helper in the view
   module. Both the page view and the download view call it; neither rebuilds the
   query itself.
2. **Run the whole listing.** The download uses `queries/core.iter_rows(stmt)` (the
   list statement with its `LIMIT/OFFSET` replaced by `EXPORT_ROW_LIMIT` and offset 0).
   It iterates a server-side cursor, so pass it straight to `csv_response` — never
   materialise with a list comprehension, and never re-derive the SQL for the export.
3. **Build the attachment** with `explorer/csv_export.csv_response(filename, columns,
   rows[, cell])`. It returns a streaming `StreamingHttpResponse`, so `rows` should be
   the lazy `iter_rows` generator (the CSV buffer flushes every ~64 KiB). Columns are
   `(header, row key)` pairs in the view; `cell` is only needed for fallback columns
   (see `views/reports.py::_csv_cell`).
4. **Wire it up:** a `GET <page>/download.csv` route in `config/urls.py`, the view
   exported from `views/__init__.py`, `"download_url": f"<path>/download.csv{pager_base}"`
   in the page context, and `download_url=download_url` on the pagination macro call.
   `page-menu.js` and the menu CSS are global (`_layout.html` /
   `page-menu.css`) — no per-page wiring.
5. **Columns:** the table's own columns first, entity GUIDs last (dataset `ckan_id`,
   link `resource_id`, publisher `json::jsonb->>'id'`, harvest source `id`). Dates
   serialise to ISO, `None` to `""`, booleans to `true`/`false`.
6. **Tests:** read exports with `explorer/tests/csv_helpers.csv_rows` (it consumes
   the stream for you); assert the unpaginated row count, the header row, and that
   filters/sort carry through.

Exports are streamed end to end: `iter_rows` fetches in server-side-cursor batches
and `csv_response` writes one ~64 KiB chunk at a time. `/links` (218k rows, ~69 MiB)
exports at ~3s with a peak RSS around one chunk instead of the full file — the
buffered path used to peak near 0.7 GiB. Keep it that way: don't wrap `iter_rows`
in `list()` and don't build the CSV in a `StringIO` before returning.

## Tests

Integration tests need a seeded fixture database — run `just fresh-db` first on a clean checkout. They skip automatically if the DB isn't available.

Live smoke tests (`pytest -m live`) run against the full dev database separately: `just test-live`.

Performance observation tests (`pytest -m perf`) are not correctness checks — they write a dated report to `docs/perf/YYYY-MM-DD/`. Run with `just perf`.
