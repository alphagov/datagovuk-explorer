# data.gov.uk Explorer

A Django 6 web app that audits the quality of the data on
[data.gov.uk](https://www.data.gov.uk): the catalogue's publisher and
dataset inventory, data-quality issue reports (datasets with no links,
duplicate titles, unparseable URLs, …), a browseable `/datasets` and
`/links` index with sidebar facets, LLM-generated reviews and suggestions,
and a `/metadata` field-adoption report.

Data is pulled from data.gov.uk's CKAN API by a standalone Python pipeline
(`scripts/`) into PostgreSQL; the web app serves it through a raw-SQL query
layer (`explorer/queries`) and Jinja2 templates. There is no ORM query layer —
the Django models exist to own the schema via migrations.

## Layout

```
config/    Django project settings, URLconf, WSGI entry point
explorer/  The app: models, migrations, raw-SQL query layer (queries/),
           views, middleware, Jinja2 backend, templates/, shared helpers
scripts/   Standalone pipeline: fetch/download datasets, build the DB,
           build series, run LLM review/suggest, ingest reviews
explorer/static/  Static assets (collected into staticfiles/ for prod)
tests/     pytest suite — app tests against the live DB + offline unit tests
data/      Pipeline inputs (tracked): reviews JSONL, views CSV
db/        Local backups (gitignored)
llm/       Embedding model (gitignored) — fetch with `just download-llm`
```

## Quickstart

Requires Python 3.13, `uv`, and a local PostgreSQL server.

```bash
just setup                    # uv sync --dev
cp .env.example .env          # then set DATABASE_URL (and secrets)
just fetch-organisations      # downloads/organisations.json from the CKAN API
just fetch-harvest-sources   # downloads/harvest_sources.json (walks publishers, per-publisher filter)
just download-datasets        # dataset JSON under downloads/ (gitignored)
just build-db --skip-embeddings   # populate the database (offline build)
just dev                      # runserver on :3000
```

Embeddings (semantic search over datasets) are optional: run
`just download-llm` once to fetch the bge-base-en-v1.5 GGUF model into
`llm/` (from CompendiumLabs on Hugging Face, with a sha256 check), then
rebuild the DB without `--skip-embeddings` (or run `just embed-only`) with
llama-server serving the model on :8080 — see `scripts/embeddings.py`.

Other commands — `just` lists them all: `download-llm`, `build-series`,
`embed-only` (needs llama-server on :8080), `review-suggest` +
`ingest-reviews` (LLM reviews), `start` (prod: collectstatic + gunicorn).

## Environment variables

See `.env.example` for the full list. The essentials:

| Var | Purpose |
|---|---|
| `DATABASE_URL` | postgresql:// connection for the app and the pipeline |
| `APP_ENV` | `production` enables basic auth (requires `BASIC_AUTH_USER`/`BASIC_AUTH_PASS`) |
| `SECRET_KEY` | Django secret (required in production) |
| `DEBUG` | Django debug flag; must be `false` in production |
| `ALLOWED_HOSTS` | Comma-separated; defaults to `*` |
| `LLM_*` / `LOCAL_*` | LLM provider config for `review-suggest` |

## Tests

```bash
just lint     # ruff check + format check
just test     # pytest (app tests need a built DB; otherwise they skip)
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

Requires the directory to be linked first: `railway link --project
datagovuk-explorer --service datagovuk-explorer`.

## Naming

The project is **data.gov.uk Explorer** (the branding used on the
basic-auth gate and in the `justfile`). Machine names: the Python
distribution is `datagovuk-explorer`, the importable package is `explorer`.
