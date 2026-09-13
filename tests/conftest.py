"""Shared database fixtures for the pipeline (``scripts/``) tests.

Most of ``tests/`` is offline and touches no database. These fixtures are
the exception: the scripts' write paths (TRUNCATE + INSERT) are exercised
against a throwaway Postgres database, never the dev DB.

Two scopes:

- ``scratch_db_url`` — a brand-new empty database, created from the
  maintenance DB and dropped (``WITH (FORCE)``) at session end. Used by
  ``test_scripts_db.py``, which builds its own tables.
- ``migrated_db_url`` — the same scratch DB with the real schema, built by
  running ``manage.py migrate``. The write-path tests use this so they can
  never drift from the migrations.

``migrate`` runs in a subprocess: Django loads in the child, so the test
process (and the rest of ``tests/``) stays Django-free.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def scratch_db_url():
    """A throwaway postgres database, or pytest.skip if we can't create one.

    Created from the postgres maintenance DB (the usual local layout);
    dropped with (FORCE) at session end so leftover connections (a crashed
    earlier run) don't block the drop.
    """
    maintenance = os.getenv(
        "TEST_POSTGRES_MAINTENANCE_URL",
        "postgresql://localhost:5432/postgres",
    )
    name = f"explorer_scratch_{uuid.uuid4().hex[:12]}"
    try:
        admin = psycopg.connect(maintenance, autocommit=True)
    except psycopg.OperationalError as e:
        pytest.skip(f"cannot reach postgres maintenance DB ({maintenance}): {e}")
    try:
        with admin.cursor() as cur:
            cur.execute(f"CREATE DATABASE {name}")
    except psycopg.Error as e:
        admin.close()
        pytest.skip(f"cannot create scratch database (CREATEDB privilege?): {e}")
    admin.close()

    url = f"postgresql://localhost:5432/{name}"
    yield url

    try:
        admin = psycopg.connect(maintenance, autocommit=True)
        with admin.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.close()
    except psycopg.Error:
        pass  # best-effort cleanup — the name is unique per run


@pytest.fixture(scope="session")
def migrated_db_url(scratch_db_url):
    """The scratch DB with the real schema (migrations applied once).

    Shells out to ``manage.py migrate`` so Django never enters the test
    process. ``DATABASE_URL`` in the child points at the scratch DB, so the
    dev database is untouched. A failure here is a real setup failure — the
    CalledProcessError carries migrate's output.
    """
    subprocess.run(
        [sys.executable, "manage.py", "migrate", "--no-input"],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": scratch_db_url},
        check=True,
        capture_output=True,
    )
    return scratch_db_url
