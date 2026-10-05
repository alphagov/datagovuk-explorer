# National Data Library Explorer

A Django 6 web app that audits the quality of the data on the
[National Data Library](https://www.data.gov.uk): the publishers and
datasets, quality issues (datasets with no links, duplicates, etc),
with facets, and experimental LLM-generated reviews and suggestions.

Data comes from a Python pipeline (`scripts/`) into PostgreSQL.
Sources include the data.gov.uk CKAN API, Google Analytics and Search Console,
link checks, and LLM generated reviews and suggestions.
The web app serves it through a raw-SQL query layer (`explorer/queries`)
and Jinja2 templates. There is no ORM query layer — the Django models
exist to own the schema via migrations.

## Layout

```
config/         Django project settings, URLconf, WSGI entry point
explorer/       The app: models, migrations, raw-SQL query layer (queries/),
                views, middleware, Jinja2 backend, templates/, static/, tests/
scripts/        Standalone pipeline: fetch datasets, build the DB, build series,
                run LLM agents (review/suggest), check links, ingest collections
tests/          Pipeline/scripts tests (pytest, no Django)
docs/           Design docs, data analyses, planning notes
data/           Pipeline inputs (tracked): views CSVs, collections pages
downloads/      Pipeline output from scripts (gitignored)
db/             Local backups (gitignored)
llm/            Embedding model (gitignored) — fetch with `just download-llm`
```

## Quickstart

Requires Python 3.13, `uv`, and PostgreSQL 16+ with the `vector` extension
(pgvector).


```bash
just setup                    # uv sync --dev
cp .env.example .env          # then set DATABASE_URL (and secrets)
just get-organisations        # downloads/organisations.json from the CKAN API
just get-harvest-sources     # downloads/harvest_sources.json (walks publishers, per-publisher filter)
just get-datasets             # downloads to downloads/
just fresh-db                 # create DB if missing + apply schema + populate (offline build)
just ingest-reviews           # load LLM review scores into the reviews table
just ingest-suggestions       # load LLM suggestions into the suggestions table
just ingest-collections       # load collections pages and their view counts
just dev                      # runserver on :3000 (or PORT if set)
```

`fresh-db` is the new-machine path: it creates the database if missing,
runs `migrate` to apply the schema, then populates it. If the database
already exists you can run `just build-db` instead — it runs `migrate`
first too, so missing tables are never a thing to remember.

`build-db` runs the full pipeline sequence: core ingestion (`ingest_ckan`),
then all derived tables in order (dataset_years, FTS, views, metadata,
dataset_api, dataset_content_hash). Each derived-table script is also a
standalone recipe, so individual tables can be rebuilt without a full run.

`ingest-reviews` and `ingest-suggestions` are required steps after every
`build-db` (or full rebuild): the build only populates the pipeline tables
and leaves `reviews` and `suggestions` empty, so the Reviews, Suggestions
and dataset-review UI all show nothing until they're run. Both are
idempotent (TRUNCATE + reload), so running them again is always safe.

Embeddings (semantic search over datasets) are optional: run
`just download-llm` once to fetch the model into `llm/`, then
run `just build-embeddings` with llama-server serving the model on :8080 —
see `scripts/build_embeddings.py`.
Semantic "more like this" is served by an HNSW index on the embedding
column. The index is approximate — `HNSW_EF_SEARCH` (default 400)
trades recall for latency.

Other commands — `just --list` lists them all. Notable ones:

| Command | What it does |
|---|---|
| `just check-links` | Check every resource URL — HEAD → GET → Playwright fallback; safe to interrupt and resume |
| `just ingest-views` | Reload dataset view counts from the GA/Search Console CSVs in `data/` |
| `just build-fts` | Rebuild the FTS (tsvector) and tags columns on datasets — run after `ingest_ckan` |
| `just build-metadata` | Rebuild metadata field/value usage tables — run after `ingest_ckan` |
| `just build-dataset-years` | Rebuild the dataset_years summary table from temporal_periods |
| `just build-dataset-api` | Rebuild the dataset_api detection table |
| `just build-dataset-content-hash` | Rebuild the content-hash deduplication table |
| `just pull-db` | Pull Railway Postgres down to replace the local DB (needs tunnel open) |
| `just build-series` | Build dataset series groupings from titles |
| `just download-llm` | Fetch the bge-base-en-v1.5 embedding model into `llm/` |
| `just build-embeddings` | Build embedding vectors (needs `just llama-server` running on :8080) |
| `just start` | Production mode: collectstatic + gunicorn |

The `review` and `suggest` scripts support remote (API key via `LLM`) and local (llama.cpp via `LOCAL_BASE_URL`) modes; see the env vars table below.

## Environment variables

See `.env.example` for the full list. The essentials:

| Var | Purpose |
|---|---|
| `DATABASE_URL` | postgresql:// connection for the app and the pipeline |
| `APP_ENV` | `production` enables basic auth (requires `BASIC_AUTH_USER`/`BASIC_AUTH_PASS`) |
| `SECRET_KEY` | Django secret (required in production) |
| `DEBUG` | Django debug flag; must be `false` in production |
| `ALLOWED_HOSTS` | Comma-separated; defaults to `*` |
| `LLM` | API key for remote LLM (`review` / `suggest`); also accepts `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` |
| `LLM_MODEL` / `LLM_BASE_URL` | Remote model ID and API base URL |
| `LOCAL_MODEL` / `LOCAL_BASE_URL` | Local llama.cpp model ID and server URL (fallback when `LLM` is unset) |

## Tests

```bash
just lint       # ruff check + format check
just test       # pytest (app tests need a built DB; otherwise they skip)
just test-live  # smoke tests against the full live dev database
just perf       # performance observation — writes docs/perf/YYYY-MM-DD/ report
just perf explorer/tests/test_perf_organisations.py  # one file only
```

## Deploying to Railway

The app runs on Railway. The DB is the state; the code just ships, so a
deploy has two halves — sync the Postgres, then push the code:

1. Dump the local DB:  `just dump-db`
   → writes `db/backups/explorer-YYYY-MM-DD.dump`
2. Open a tunnel:      `just tunnel`
   → runs `railway connect Postgres --tunnel-only -P 5433`;
   keep this terminal open (Ctrl+C closes it)
3. Restore:            `just restore-db explorer.dump postgresql://postgres:PASS@127.0.0.1:5433/railway`

`restore-db` drops the target schema up front and replaces everything
(see the recipe comments in the justfile for why). The URL uses the
tunnel's host/port; the credentials are the Railway Postgres's own —
find the password in `railway variables --service Postgres`
(`PGPASSWORD`). The tunnel prints the exact URL to use. The
internal `postgres.railway.internal` host from `DATABASE_URL`
won't resolve off-Railway, so the tunnel is required.

Then ship the code and verify:

```bash
just deploy         # railway up -d -y
just deploy-check   # GET /health on the production URL
```
