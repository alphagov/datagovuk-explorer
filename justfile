# data.gov.uk Explorer — command shortcuts

# Load .env (DATABASE_URL etc.) into the recipe environment so commands like
# pg_dump/pg_restore can use it. Missing .env is fine — vars stay unset.
set dotenv-path := ".env"

# Run the dev server with auto-reload. whitenoise.runserver_nostatic means
# WhiteNoise serves /static/ through the middleware chain (Cache-Control
# max-age=0 in dev, see config/settings.py), so edited CSS/JS aren't cached.
# The BasicAuth gate therefore applies to static locally too.
dev:
    uv run --env-file .env python manage.py runserver 0.0.0.0:{{env_var_or_default("PORT", "3000")}}

# Run the server (production mode — no reload; WhiteNoise serves collectstatic
# output from staticfiles/)
start:
    uv run --env-file .env python manage.py collectstatic --noinput
    uv run --env-file .env gunicorn config.wsgi --bind 0.0.0.0:{{env_var_or_default("PORT", "3000")}} --config gunicorn.conf.py

# Lint: ruff check + format check + migration drift check (runs against working tree, no stashing)
lint *args:
    uv run ruff check {{args}} .
    uv run ruff format --check {{args}} .
    uv run python manage.py makemigrations --check --dry-run

# Typecheck: Run mypy
# (Not in pre-commit/CI — run manually, like datagovuk.)
typecheck:
    uv run mypy .

# Format + lint fix
format:
    uv run ruff check --fix . && uv run ruff format .

# Fast default: unit + integration, excluding slow/live. Bare `pytest` runs
# everything in one session; the filter lives here (not in pytest addopts) so
# it stays visible. Coverage is on (source + fail_under in pyproject.toml), so
# the same command that gates CI gates local runs. Extra args are forwarded,
# so CI runs `just test --fail-on-skip` (a skip must not hide a test there).
test *args:
    # pytest-django forces settings.DEBUG=false, so the static() template tag
    # resolves through the manifest storage and needs staticfiles/staticfiles.json.
    # (The dev server skips this: DEBUG=true emits plain URLs, served by
    # WHITENOISE_USE_FINDERS. Tests render the same hashed URLs as production.)
    uv run python manage.py collectstatic --noinput
    uv run pytest -m "not slow and not live and not perf" --cov --cov-report=term-missing {{args}}

# Everything: the fast suite (incl. slow) then the opt-in live smoke, in two
# invocations. The fixture DB rewrites the default connection, so live and
# fixture tests cannot share a session; a single `pytest -m ""` would run the
# live smoke against the test DB.
test-all:
    uv run pytest -m "not live and not perf"
    uv run pytest -m live

# Opt-in smoke tests against the full live dev database (must run alone).
test-live *args:
    uv run pytest -m live {{args}}

# Performance observation — writes a dated report to docs/perf/YYYY-MM-DD/.
perf *args:
    uv run pytest -m perf -s {{args}}

# Install dependencies (first run)
setup:
    uv sync --dev

# Download the EmbeddingGemma-300M GGUF model into llm/ (needed for embeddings)
download-llm:
    uv run python -m scripts.download_llm

# Apply any pending schema migrations (idempotent — a no-op when the
# database is already up to date). Schema is migration-owned, so this is
# the step that turns a bare Postgres (or an older dump) into the schema
# the code expects.
migrate:
    uv run --env-file .env python manage.py migrate

# Rebuild the PostgreSQL database from downloads/ (DATABASE_URL comes from
# .env). Runs migrate first, so a fresh checkout or a DB restored from an
# older dump can't hit missing tables — the schema is applied before the
# build populates. Run `just build-embeddings` afterwards for embeddings.
build-db: migrate
    uv run --env-file .env python -m scripts.ingest_ckan
    uv run --env-file .env python -m scripts.build_series
    uv run --env-file .env python -m scripts.build_dataset_years
    uv run --env-file .env python -m scripts.build_fts
    uv run --env-file .env python -m scripts.ingest_views
    uv run --env-file .env python -m scripts.build_metadata
    uv run --env-file .env python -m scripts.build_dataset_api
    uv run --env-file .env python -m scripts.build_dataset_content_hash
    uv run --env-file .env python -m scripts.build_harvester_stats

# Rebuild just the dataset_api table (TRUNCATE + INSERT) — fast, no full
# rebuild needed. Use when tweaking the API detection algorithm.
build-dataset-api:
    uv run --env-file .env python -m scripts.build_dataset_api

# Reload dataset view counts from GA page views, GA Google landing pages,
# and Search Console clicks — fast, no full rebuild needed.
ingest-views:
    uv run --env-file .env python -m scripts.ingest_views

# Rebuild just the dataset_content_hash table (TRUNCATE + INSERT) — fast,
# no full rebuild needed. Use when tweaking the duplicate-detection hash.
build-dataset-content-hash:
    uv run --env-file .env python -m scripts.build_dataset_content_hash

# Rebuild just the dataset_years table (TRUNCATE + INSERT) — fast, no full
# rebuild needed. Expands temporal_periods into one row per (dataset, year).
build-dataset-years:
    uv run --env-file .env python -m scripts.build_dataset_years

# Rebuild just the tags + fts columns (TRUNCATE implicit — UPDATE all rows).
# Reads from datasets + dataset_json — run after ingest_ckan.
build-fts:
    uv run --env-file .env python -m scripts.build_fts

# Rebuild just the metadata_keys + metadata_values tables (TRUNCATE + INSERT).
# Reads raw JSON from dataset_json — run after ingest_ckan.
build-metadata:
    uv run --env-file .env python -m scripts.build_metadata

# One-shot fresh local database: create it if missing, apply the schema,
# then populate it. The path for a fresh checkout. db_name must be the
# database DATABASE_URL names (default
# postgresql://localhost:5432/datagovuk_explorer); if your Postgres needs
# credentials, create the database yourself and run `just build-db`.
fresh-db db_name="datagovuk_explorer":
    @createdb "{{db_name}}" 2>/dev/null && echo "created {{db_name}}" || echo "{{db_name}} already exists"
    uv run --env-file .env python manage.py migrate
    uv run --env-file .env python -m scripts.ingest_ckan
    uv run --env-file .env python -m scripts.build_series
    uv run --env-file .env python -m scripts.build_dataset_years
    uv run --env-file .env python -m scripts.build_fts
    uv run --env-file .env python -m scripts.ingest_views
    uv run --env-file .env python -m scripts.build_metadata
    uv run --env-file .env python -m scripts.build_dataset_api
    uv run --env-file .env python -m scripts.build_dataset_content_hash
    uv run --env-file .env python -m scripts.build_harvester_stats

# Populate denormalised stats columns on harvest_sources (dataset_count,
# last_run). Run after build-db; re-runnable.
build-harvester-stats:
    uv run --env-file .env python -m scripts.build_harvester_stats

# Build series data from dataset titles (DATABASE_URL from .env)
build-series:
    uv run --env-file .env python -m scripts.build_series

# Start llama-server with the embedding model on :8080 (keep running in a separate terminal)
# --pooling mean: EmbeddingGemma pools with the mean token embedding (not BGE's cls)
# --ctx-size 8192: 1024 tokens per slot (8 parallel) — plenty for the 500-char
#   descriptions; otherwise llama.cpp leaves only 256 tokens per slot
# --ubatch-size 2048: avoids the assertion that caps both n_batch and ubatch at 512
# --parallel 8: 8 sequences per forward pass (double the default 4)
llama-server:
    llama-server -m llm/embeddinggemma-300m-qat-Q8_0.gguf \
      --embeddings --pooling mean --embd-normalize 2 --gpu-layers all \
      --ctx-size 8192 --ubatch-size 2048 --parallel 8 --port 8080

# Build dataset embeddings (run `just llama-server` in another terminal first; DATABASE_URL from .env)
build-embeddings:
    uv run --env-file .env python -m scripts.build_embeddings

# Pre-compute related-dataset results into baked lookup tables. Run after
# build-embeddings. Required before dump-db so the deploy dump contains the
# baked tables (the embedding tables themselves are excluded from the deploy
# dump to save ~380 MB per dump/restore cycle).
build-related:
    uv run --env-file .env python -m scripts.build_related

# Dump the local dev database for deploy — excludes embedding table data so
# the dump is ~380 MB smaller and the Railway restore skips the HNSW index
# rebuild. Table definitions (schema) are still included so migrations work.
# db/backups/ is gitignored.
dump-db dump_file="db/backups/explorer-`date +%F`.dump":
    @mkdir -p db/backups
    pg_dump "{{env_var_or_default('DATABASE_URL', 'postgresql://localhost:5432/datagovuk_explorer')}}" \
      --no-owner --no-privileges --format=custom \
      --exclude-table-data=dataset_embeddings \
      --exclude-table-data=embedding_map \
      --exclude-table-data=collection_embeddings \
      --file="{{dump_file}}"
    @echo "Wrote {{dump_file}}"

# Dump the full local dev database including embedding tables — for local
# backups and testing build_related locally.
dump-db-full dump_file="db/backups/explorer-full-`date +%F`.dump":
    @mkdir -p db/backups
    pg_dump "{{env_var_or_default('DATABASE_URL', 'postgresql://localhost:5432/datagovuk_explorer')}}" \
      --no-owner --no-privileges --format=custom --file="{{dump_file}}"
    @echo "Wrote {{dump_file}}"

# Restore a dump into a target Postgres, replacing everything. Works for
# pushing local → Railway or pulling prod → local (see pull-db).
# The existing schema is dropped wholesale first — pg_restore --clean alone
# can't cascade through FK dependencies (datasets ← links/dataset_json/
# embedding_map), which is why the drop is done up front.
#
# The restore runs in three sections (pre-data → data → post-data) so the
# OS page cache from each phase can be reclaimed before the next begins.
# This reduces peak memory — Railway's cgroup metric includes page cache,
# so a single-pass restore spikes memory (and cost) unnecessarily.
#
# For Railway as the destination, the internal postgres.railway.internal host
# doesn't resolve off-Railway — open a tunnel first (`just tunnel`) and use
#   postgresql://postgres:PASS@127.0.0.1:5433/railway
# (password from `railway variables --service Postgres`, key PGPASSWORD).
# Pass it as the second arg — the tunnel prints the exact URL to use.
restore-db dump_file destination_database_url='':
    @if [ -z "{{destination_database_url}}" ]; then \
        echo "Pass the destination Postgres URL, e.g." >&2; \
        echo '  just restore-db explorer.dump postgresql://postgres:PASS@127.0.0.1:5433/railway' >&2; \
        exit 1; \
    fi
    @echo "Dropping existing schema in the target DB, then restoring {{dump_file}}"
    psql "{{destination_database_url}}" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
    @echo "Restoring schema…"
    pg_restore --no-owner --no-privileges --section=pre-data \
      --dbname="{{destination_database_url}}" "{{dump_file}}"
    @echo "Disabling autovacuum on large tables during restore…"
    psql "{{destination_database_url}}" -c " \
      ALTER TABLE IF EXISTS datasets SET (autovacuum_enabled = false); \
      ALTER TABLE IF EXISTS link_check_results SET (autovacuum_enabled = false);"
    @echo "Restoring data…"
    pg_restore --no-owner --no-privileges --section=data \
      --dbname="{{destination_database_url}}" "{{dump_file}}"
    @echo "Restoring indexes and constraints (parallel workers disabled to reduce memory)…"
    PGOPTIONS="-c max_parallel_workers_per_gather=0 -c max_parallel_workers=0" \
      pg_restore --no-owner --no-privileges --section=post-data \
      --dbname="{{destination_database_url}}" "{{dump_file}}"
    @echo "Running VACUUM ANALYZE on large tables…"
    psql "{{destination_database_url}}" -c "VACUUM ANALYZE datasets;"
    psql "{{destination_database_url}}" -c "VACUUM ANALYZE link_check_results;"
    @echo "Re-enabling autovacuum…"
    psql "{{destination_database_url}}" -c " \
      ALTER TABLE IF EXISTS datasets SET (autovacuum_enabled = true); \
      ALTER TABLE IF EXISTS link_check_results SET (autovacuum_enabled = true);"
    @echo ""
    @echo "Done. If you restored to Railway, run 'just restart-railway-db' to reset memory."

# Pull the Railway Postgres down and replace the local database.
# Needs the tunnel running in another terminal (`just tunnel`).
# Pass the Railway Postgres URL as the argument — the tunnel prints it.
# e.g.:  just pull-db postgresql://postgres:PASS@127.0.0.1:5433/railway
pull-db source_database_url='':
    @if [ -z "{{source_database_url}}" ]; then \
        echo "Pass the Railway Postgres URL, e.g." >&2; \
        echo '  just pull-db postgresql://postgres:PASS@127.0.0.1:5433/railway' >&2; \
        exit 1; \
    fi
    @mkdir -p db/backups
    pg_dump "{{source_database_url}}" \
      --no-owner --no-privileges --format=custom \
      --file="db/backups/prod-`date +%F`.dump"
    just restore-db "db/backups/prod-`date +%F`.dump" \
      "{{env_var_or_default('DATABASE_URL', 'postgresql://localhost:5432/datagovuk_explorer')}}"

# Open an encrypted tunnel to the Railway Postgres. Keep this running in a
# terminal while you restore (Ctrl+C to close). 5433 — your local Postgres
# usually owns 5432.
tunnel:
    @echo "Opening tunnel to Railway Postgres on 127.0.0.1:5433 — Ctrl+C to close"
    railway connect Postgres --tunnel-only -P 5433

# Restart the Railway Postgres container to reset cgroup memory after a
# restore. The data is on a persistent volume — nothing is lost.
restart-railway-db:
    railway restart --service Postgres -y

# Deploy the current directory to the Railway service, replacing the running
# app on the same URL. Run the dump → tunnel → restore-db dance first (the
# DB is the state; this just ships the code). Requires the dir to be linked:
#   railway link --project datagovuk-explorer --service datagovuk-explorer
# Stuck in DEPLOYING with empty logs? Check Railway's status page — they've
# had queueing incidents that clear on their own.
deploy:
    railway up -d -y

# Verify the deployed app is healthy — /health is exempt from basic auth
# (see explorer/middleware.py), so no credentials are needed.
deploy-check:
    curl -s -o /dev/null -w "health: %{http_code}\n" \
      "https://datagovuk-explorer-production.up.railway.app/health"

# Get organisations from CKAN API. Writes downloads/organisations.json,
# which build-db loads.
get-organisations:
    uv run python -m scripts.get_organisations

# Get all harvest sources from CKAN API (walks orgs, per-org filter).
# Writes downloads/harvest_sources.json, which build-db loads.
get-harvest-sources:
    uv run python -m scripts.get_harvest_sources

# Audit for unused CSS with PurgeCSS (read-only: lists selectors that
# appear in no template/JS, never rewrites files). Requires Node/npx —
# the first run downloads purgecss. The --safelist entries are classes
# built dynamically in templates (score-{{ n }}, suggestion--{{ level }},
# badge-{{ org.state/approval_status }}), which a static scan always flags.
unused-css:
    npx -y purgecss \
      --css 'explorer/static/css/**/*.css' \
      --content 'explorer/templates/**/*.html' 'explorer/static/links.js' 'explorer/static/facet-search.js' \
      --rejected \
      --safelist score-0 score-1 score-2 score-3 score-4 score-5 \
                 suggestion--low suggestion--med suggestion--high \
                 badge-active badge-approved badge-deleted badge-draft \
                 badge-rejected badge-pending \
      | python3 -c 'import json,sys; [print(x["file"].split("/")[-1] + ": " + (", ".join(r.strip() for r in x["rejected"] if r.strip()) or "clean")) for x in json.load(sys.stdin)]'

# Get all datasets for every unfetched org. Safe to interrupt and resume.
get-datasets *args:
    uv run python -m scripts.get_datasets {{args}}

# Query datasets for one org
query-datasets *args:
    uv run python -m scripts.query_datasets {{args}}

# LLM review — quality scores (loads .env for LLM/LOCAL_* vars)
review *args:
    uv run --env-file .env python -m scripts.llm.review {{args}}

# LLM suggest — theme/tags/title/description (loads .env for LLM/LOCAL_* vars)
suggest *args:
    uv run --env-file .env python -m scripts.llm.suggest {{args}}

# Load review scores into the reviews table (run after `just review`)
ingest-reviews:
    uv run --env-file .env python -m scripts.llm.ingest_reviews

# Load suggestions into the suggestions table (run after `just suggest`)
ingest-suggestions:
    uv run --env-file .env python -m scripts.llm.ingest_suggestions

# Load collection pages from data/collections/ into the collections table,
# with combined views from GA page views, GA Google landing pages, and
# Search Console clicks.
ingest-collections:
    uv run --env-file .env python -m scripts.ingest_collections

# Check every URL in the links table (HEAD → GET → Playwright fallback).
# Writes results to link_check_results; safe to interrupt and rerun.
# View live progress at /check-progress while the checker is running.
check-links *args:
    uv run --env-file .env python -m scripts.check_links {{args}}
