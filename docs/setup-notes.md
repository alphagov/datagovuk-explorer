# Setup Notes — macOS (Apple Silicon, Zscaler network)

Recorded during first-time setup on 2026-09-06.

---

## Environment

- macOS 15 (Darwin 25.6.0), Apple Silicon
- Python 3.13.13 via pyenv
- PostgreSQL 18.6 via Postgres.app (bundles pgvector — no separate install needed)
- Corporate network behind Zscaler SSL inspection

---

## What went smoothly

### Python + uv

`uv` was already installed. Running `uv run python` for the first time auto-created `.venv` and installed all 57 packages from `uv.lock` without issues (~30 seconds).

### PostgreSQL

Postgres.app was already running with pgvector bundled. No configuration needed. `createdb` / `psql` were on PATH via Postgres.app's CLI tools. The default `DATABASE_URL=postgresql://localhost:5432/datagovuk_explorer` in `.env.example` worked without changes.

### `.env` setup

```bash
cp .env.example .env
```

One change is required: set `DEBUG=true`. The example ships with `DEBUG=false` (correct for production), but locally WhiteNoise needs `DEBUG=true` to enable `WHITENOISE_USE_FINDERS`, which serves static files directly from `explorer/static/`. Without it, WhiteNoise only looks in `staticfiles/` (populated only after `collectstatic`), so all assets 404.

### Migrations

`just fresh-db` applied all 10 migrations cleanly on first run once the database existed.

### Fetching CKAN data

Once the SSL issue was resolved (see below), `just get-organisations` and `just get-harvest-sources` ran successfully. `get-harvest-sources` takes a few minutes — it walks all publishers to fetch per-publisher harvest sources from the CKAN API.

---

## What didn't go smoothly

### SSL certificate failure (Zscaler)

**Symptom:** `just get-organisations` failed immediately:

```
Error: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
unable to get local issuer certificate (_ssl.c:1032)
```

**Root cause:** Zscaler performs SSL inspection and injects its own root CA into the macOS system keychain. `curl` uses the system keychain and works fine. Python (via pyenv) uses Homebrew's OpenSSL cert bundle (`/opt/homebrew/etc/openssl@3/cert.pem`), which does not include the Zscaler CA.

**First attempt — combined cert file:**

```bash
cat $(uv run python -c "import certifi; print(certifi.where())") \
    ~/certs/zscaler.pem > ~/certs/python-combined.pem
```

Added `SSL_CERT_FILE=/Users/JLanman/certs/python-combined.pem` to `.env`. This changed the error to:

```
certificate verify failed: Basic Constraints of CA cert not marked critical
```

Python 3.13 tightened RFC 5280 validation and rejects the Zscaler cert's non-critical Basic Constraints extension. The combined file approach doesn't work on Python 3.13.

**Fix — `truststore` library:**

`truststore` makes Python delegate SSL verification to the native OS trust store (macOS Security framework), which already trusts the Zscaler CA and doesn't apply Python's stricter validation.

```bash
uv add truststore
```

Added to `scripts/__init__.py` (runs automatically for every `python -m scripts.*`):

```python
import truststore
truststore.inject_into_ssl()
```

This resolved all SSL errors. The `SSL_CERT_FILE` line in `.env` is now redundant and can be removed.

**If the Django app ever needs to make outbound HTTPS requests**, add the same two lines to `manage.py` before the Django setup block.

---

## Steps completed

| Step | Command | Outcome |
|---|---|---|
| Install deps | `just setup` (implicit — `uv run` triggers it) | ✓ 57 packages |
| Create .env | `cp .env.example .env` | ✓ |
| Fix SSL | `uv add truststore` + `scripts/__init__.py` | ✓ |
| Get orgs | `just get-organisations` | ✓ 1043 orgs |
| Get harvest sources | `just get-harvest-sources` | ✓ 515 sources |
| Create DB + migrate | `just fresh-db` | ✓ (0 datasets — `get-datasets` not yet run) |

## Steps remaining

**Total time from scratch: ~20 minutes** — the download dominates (~9 min), followed by `fresh-db` (~3 min). Everything else is negligible.

```bash
just get-datasets --continuous --per-org all   # fetch ALL orgs AND all datasets per org
just fresh-db                                       # re-run after full download to populate dataset tables
just ingest-reviews                                 # load LLM reviews (data/dataset-reviews-suggestions.jsonl is tracked in git — 521 reviews)
just dev                                            # runserver on :3000
```

### Important ordering notes

- **Always use `--per-org all` for a complete build.** The default caps at 1000 datasets per org. Large publishers (ONS, Natural England, BGS, Marine Environmental Data Information Network) have more than 1000 datasets each — without `--per-org all` their tail is silently dropped, causing `ingest-reviews` to fail with FK violations because some reviewed datasets are missing.
- **`get-datasets` default only fetches 50 orgs** — always pass `--continuous` as well. It's resumable: safe to interrupt and re-run.
- **`ingest-reviews` requires a complete dataset table** — the reviews JSONL has FK references to `datasets.id`. Running it against a partial download fails with `ForeignKeyViolation`. Run it only after `fresh-db` has ingested the full dataset download.
- **`data/dataset-reviews-suggestions.jsonl` is tracked in git** — 521 pre-generated LLM reviews are committed. You don't need to run `review-suggest` to get started; that's only needed to regenerate or expand them.
