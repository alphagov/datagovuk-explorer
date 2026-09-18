# API & MCP plan

Add a read-only JSON API and an MCP endpoint to data.gov.uk Explorer,
so LLMs and other tools can query the catalogue programmatically.

---

## Context

The app already has:

- A raw-SQL query layer (`explorer/queries/`) that returns dicts —
  the views are thin renderers, so producing JSON instead of HTML is
  mostly plumbing.
- One existing JSON endpoint: `GET /api/publishers` (autocomplete
  suggestions).
- Full-text search via `tsvector`.
- ~66k datasets, ~400k links, ~900 organisations, 10+ data-quality
  reports, LLM reviews and suggestions.
- Django 6 on Python 3.13, deployed to Railway.

The `ideas.md` "Quality API" section already identifies this as a
longer-term goal. This plan makes it concrete.

---

## Part 1: JSON API

### Design principles

- **Read-only.** The DB is a build-time snapshot; there's nothing to
  write.
- **Same data as the UI.** Every API endpoint mirrors an existing page —
  no new queries, no schema drift.
- **Offset pagination** for list endpoints (matching the existing
  `paginate()` helper).
- **No auth for now.** The app already has optional basic auth
  (`APP_ENV=production`); the API sits behind the same gate. A future
  API-key layer can wrap these endpoints without changing them.
- **Flat JSON.** Dicts from the query layer serialise directly —
  no serialiser framework, no ORM, just `JsonResponse`.

### URL structure

All API routes live under `/api/v1/`.

```
GET /api/v1/stats                        Dashboard summary (all cards)
GET /api/v1/datasets                     Paginated dataset list (same filters as /datasets)
GET /api/v1/datasets/:org/:id            Single dataset detail (full JSON + review + related)
GET /api/v1/organisations                Paginated organisation list (same filters as /organisations)
GET /api/v1/organisations/:slug          Single organisation detail
GET /api/v1/links                        Paginated link list (same filters as /links)
GET /api/v1/links/errors                 Paginated link-error list (same filters as /links/errors)
GET /api/v1/reports                      List of report keys + counts
GET /api/v1/reports/:key                 One report's paginated rows
GET /api/v1/search                       Combined search (publishers + datasets)
GET /api/v1/reviews                      Paginated reviews
GET /api/v1/suggestions                  Paginated suggestions
GET /api/v1/series                       Paginated series list
GET /api/v1/series/:id                   Single series + member datasets
GET /api/v1/metadata                     Metadata field-adoption summary
GET /api/v1/harvesters                   Paginated harvester list
```

### Response shape

Detail endpoints return the object directly:

```json
{ "id": "...", "title": "...", "org_slug": "..." }
```

List endpoints return the array with pagination metadata:

```json
{
  "results": [ ... ],
  "total": 1234,
  "page": 1,
  "page_size": 100,
  "total_pages": 13
}
```

Errors use HTTP status codes (404, 400, etc.) with a plain message:

```json
{ "error": "Not found" }
```

### Implementation approach

1. **`explorer/api/` package** — a new Django app (or just a subpackage
   of `explorer`) with its own views. Each view function calls the same
   query-layer functions the HTML views call, then wraps the result in
   `JsonResponse`.

2. **`config/urls.py`** — a new `path("api/v1/", include("explorer.api.urls"))`
   block, added before the catch-all 404.

3. **No new dependencies.** `JsonResponse` is built into Django. No
   DRF, no Pydantic, no OpenAPI generator. The API is small enough that
   hand-written views stay simpler than a framework's abstractions.

5. **Tests** — `explorer/tests/test_api.py`, hitting the endpoints
   against the seeded test DB (same pattern as the existing integration
   tests).

### Endpoints mapped to existing query functions

| Endpoint | Query module | Key function(s) |
|---|---|---|
| `/stats` | `queries/dashboard` | `cards()` |
| `/datasets` | `queries/datasets` | `dataset_list()`, `dataset_count()` |
| `/datasets/:org/:id` | `queries/datasets` + `reviews` | `DATASET_JSON`, `get_review()` |
| `/organisations` | `queries/organisations` | `organisations()` |
| `/organisations/:slug` | `queries/organisations` + `datasets` | `ORG`, `ORG_AGGREGATES` |
| `/links` | `queries/links` | `link_list()`, `link_count()` |
| `/links/errors` | `queries/link_errors` | same pattern |
| `/reports` | `queries/reports` | `REPORTS` list + `report_dashboard_count()` |
| `/reports/:key` | `queries/reports` | `report_stmts()` |
| `/search` | `queries/search` | `search_all()` |
| `/reviews` | `queries/reviews` | existing list query |
| `/suggestions` | `queries/reviews` | existing list query (filtered to suggestions) |
| `/series` | `queries/series` | existing list query |
| `/series/:id` | `queries/series` | `SERIES_DETAIL`, `SERIES_DATASETS` |
| `/metadata` | `queries/metadata` | existing overview query |
| `/harvesters` | `queries/harvesters` | existing list query |

### Search endpoints in detail

**`GET /api/v1/search?q=flood+data`** — combined full-text search:

```json
{
  "publishers": [ {"slug": "...", "display_name": "...", "package_count": 42} ],
  "publisher_count": 3,
  "datasets": [ {"id": "...", "title": "...", "org_slug": "...", "rank": 0.98} ],
  "dataset_count": 127
}
```

### Work estimate

The query layer already does the heavy lifting. Each API view is 10–30
lines (call query, wrap in `JsonResponse`). The whole API is an
`explorer/api/` package with a urls file, a views file, and tests.

---

## Part 2: MCP endpoint

### What it does

An MCP (Model Context Protocol) endpoint served by Django exposes the
query layer as tools that LLMs can call. An LLM connected to this
endpoint can:

- Search the catalogue by keyword
- Look up a specific dataset, organisation, or report
- Get quality statistics and identify problem areas
- Browse link errors, reviews, and suggestions

### Architecture

The MCP endpoint is a **Django view** inside the same app — no separate
process, no intermediate HTTP hop. It calls the query layer directly,
the same way the HTML views and API views do:

```
LLM ←→ Django app (/mcp/ endpoint, Streamable HTTP) ←→ query layer ←→ PostgreSQL
```

This is the simplest possible architecture: one deployment, one process,
one URL. The `django-mcp` package (or the `mcp` SDK's ASGI/WSGI
integration) handles the MCP protocol; the tool handlers are plain
functions that call `explorer/queries/` and return dicts.

### URL

```
POST /mcp/    MCP Streamable HTTP endpoint
```

A single URL. MCP clients (Claude Desktop, Claude Code, remote agents)
point at it. The existing basic-auth gate covers it in production.

### Tool definitions

Tool names follow MCP conventions (snake_case, verb-noun). Each tool
reuses the same handler functions as the API views — one set of
functions, two interfaces (JSON API and MCP).

```
search_datasets          Search by keyword (FTS)
get_stats                Dashboard summary
list_datasets            Browse datasets (with filters)
get_dataset              One dataset's full detail
list_organisations       Browse organisations
get_organisation         One organisation's detail
list_reports             All reports with counts
get_report               One report's rows
list_links               Browse resource links
list_link_errors         Browse link-check errors
list_reviews             Browse LLM reviews
list_suggestions         Browse LLM suggestions
list_series              Browse detected series
get_series               One series + members
get_metadata             Field-adoption overview
list_harvesters          Browse harvest sources
```

### Tool input schemas

Each tool's parameters match the query-string filters the existing pages
accept, defined as JSON Schema in the MCP tool registration. Examples:

```json
{
  "name": "search_datasets",
  "description": "Search the data.gov.uk catalogue by keyword. Uses PostgreSQL full-text search. Returns matching publishers and datasets ranked by relevance.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "q": {
        "type": "string",
        "description": "Search query (e.g. 'flood risk', 'NHS prescriptions')"
      }
    },
    "required": ["q"]
  }
}
```

```json
{
  "name": "list_datasets",
  "description": "List datasets from the data.gov.uk catalogue with optional filters for publisher, theme, format, temporal coverage, and harvest status. Returns a paginated list sorted by the chosen column.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "org": { "type": "string", "description": "Filter by publisher slug" },
      "theme": { "type": "string", "description": "Filter by primary theme" },
      "format": { "type": "string", "description": "Filter by resource format (e.g. CSV, JSON, XML)" },
      "sort": { "type": "string", "enum": ["title", "organisation", "metadata_created", "metadata_modified", "resources", "views"] },
      "dir": { "type": "string", "enum": ["asc", "desc"] },
      "page": { "type": "integer", "minimum": 1 }
    }
  }
}
```

### Implementation

**Files:**

```
explorer/mcp/
  __init__.py
  tools.py           Tool definitions + handlers (~300 lines)
```

**Tool handler pattern (`tools.py`):**

Each handler calls the query layer directly and returns a dict:

```python
from explorer.queries.search import search_all

def handle_search_datasets(q: str) -> dict:
    return search_all(q)
```

The MCP SDK serialises the return value. No HTTP in the middle.

**URL wiring (`config/urls.py`):**

```python
from explorer.mcp import mcp_view

urlpatterns += [
    path("mcp/", mcp_view),
]
```

The exact view integration depends on which MCP SDK approach we use
(see below).

### MCP SDK options

**A. `django-mcp-server`** — a Django integration that provides a
ready-made view. Define tools as decorated functions, mount the view
at a URL, done.

**B. `mcp` SDK with ASGI** — Anthropic's official SDK includes an ASGI
app. Django 6 supports ASGI natively, so the MCP app can be mounted at
`/mcp/` in the ASGI config. The tool handlers are the same either way.

Either approach keeps everything in one deployment. Recommendation:
evaluate both at implementation time and pick whichever is more mature.
The tool handler code is identical — only the wiring differs.

### Connecting clients

**Claude Desktop / Claude Code (local):**

```json
{
  "mcpServers": {
    "datagovuk": {
      "type": "url",
      "url": "http://localhost:3030/mcp/"
    }
  }
}
```

**Against production (Railway):**

```json
{
  "mcpServers": {
    "datagovuk": {
      "type": "url",
      "url": "https://datagovuk-explorer.up.railway.app/mcp/",
      "headers": {
        "Authorization": "Basic <base64>"
      }
    }
  }
}
```

No separate process to run, no stdio, no sidecar. Point the client at
the URL and it works.

---

## Implementation order

### Phase 1: JSON API

1. Create `explorer/api/` — start with `/api/v1/stats` to prove the pattern
2. Add the remaining endpoints, with shared handler functions that both
   the API views and the MCP tools will call
3. Tests

### Phase 2: MCP endpoint

4. Add MCP SDK to dependencies
5. Create `explorer/mcp/` — tool definitions that call the shared
   handler functions from phase 1
6. Mount the MCP view at `/mcp/`
7. Test with Claude Desktop / Claude Code
8. Document in README

---

## What this enables

- **Claude Code / Claude Desktop** can browse the catalogue, search
  for datasets, and inspect quality issues — just point at the `/mcp/`
  URL.
- **External dashboards** can pull live data from the API without
  scraping HTML.
- **Publishers** could build CI checks ("does my org have any new
  quality issues?") by polling the reports endpoint.
- **Other LLM tools** (agents, RAG pipelines) can use the API directly
  or via MCP.
- **CSV/JSON export** (the `ideas.md` item) is essentially free once
  the API exists — add `Accept: text/csv` content negotiation or a
  `?format=csv` parameter to any list endpoint.

---

## Dependencies

No new runtime dependencies for the JSON API (Django's `JsonResponse` is
enough).

For the MCP endpoint, one of:

```toml
# pyproject.toml — pick one
"mcp>=1.0",              # Anthropic's official MCP SDK (ASGI integration)
"django-mcp-server",     # or: Django-specific MCP wrapper
```

Evaluate both at implementation time. The tool handler code is the same
either way — only the view wiring differs.

---

## Not in scope

- **Write endpoints** — the DB is a build-time snapshot; mutations
  belong in the pipeline.
- **Authentication beyond basic auth** — API keys, OAuth, JWT are
  future work if the API goes public.
- **GraphQL** — the query patterns are fixed and well-known; REST is
  simpler for this shape of data.
- **WebSocket subscriptions** — the data changes on rebuild (weekly),
  not in real time.
