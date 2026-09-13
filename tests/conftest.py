"""Scratch Postgres fixtures for the pipeline (``scripts/``) tests.

Most of ``tests/`` is offline. ``scratch_db_url`` creates an empty throwaway
database (dropped at session end) for ``test_scripts_db.py``;
``migrated_db_url`` adds the real schema via ``manage.py migrate`` so the
write-path tests can't drift from the migrations. ``migrate`` runs in a
subprocess to keep Django out of the test process.
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
    """A throwaway postgres database, or pytest.skip if it can't be created."""
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
    """The scratch DB with the real schema (``migrate`` runs in a subprocess)."""
    subprocess.run(
        [sys.executable, "manage.py", "migrate", "--no-input"],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": scratch_db_url},
        check=True,
        capture_output=True,
    )
    return scratch_db_url
