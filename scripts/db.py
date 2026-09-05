r"""Sync psycopg3 database layer for the standalone pipeline.

connect() / prepare() / exec() / transaction() / close() — fully
synchronous, and it never touches Django (no DJANGO_SETTINGS_MODULE, no
django.db, no settings). The seam between the pipeline and the web app is
the database, not the runtime: the app reads what the pipeline populates.

SQL translation: SQLite-style `?` placeholders become psycopg `%s`;
escaped `\?` literals (URL regexes in the report SQL) are left untouched.
The app-side query layer (explorer/queries) writes native `%s` directly;
the scripts keep `?` so the statements carry over unchanged.

Design consequences of one sync connection:

- autocommit on: each top-level statement commits itself; transaction()
  wraps an explicit BEGIN/COMMIT/ROLLBACK on that same connection.
- Rows come back as dicts (psycopg dict_row) — row["n"] key access.
- psycopg parses jsonb columns into Python objects (its default
  JsonbLoader); Django's connection returns JSON strings. Scripts reading
  jsonb get objects; scripts writing them pass JSON-encoded text, which
  psycopg parses on the way in. Register JsonbTextLoader in connect() if a
  script ever needs string parity with the app.
- A literal `%` in a statement that carries params raises in psycopg, so
  no-param statements use plain execute (no placeholder parsing), and any
  literal `%` added to a parameterized statement must be doubled (%%), as
  in explorer/queries.
"""

import os
import re
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.rows import dict_row

# SQLite-style `?` → psycopg `%s`, leaving escaped `\?` literals (URL
# regexes in the report SQL) untouched.
_PLACEHOLDER_RE = re.compile(r"\\\?|\?")


def _translate(sql: str) -> str:
    return _PLACEHOLDER_RE.sub(
        lambda m: m.group(0) if m.group(0) == r"\?" else "%s",
        sql,
    )


def database_url() -> str:
    """Return DATABASE_URL from the environment, failing loudly if unset."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set — add it to .env (see .env.example)")
    return url


class Query:
    """A compiled (translated) SQL query with get/all/run methods."""

    def __init__(self, db: "Db", sql: str):
        self._db = db
        self._sql = _translate(sql)

    def get(self, *params: Any) -> dict | None:
        """First row or None."""
        rows = self._fetch(params, one=True)
        return rows

    def all(self, *params: Any) -> list[dict]:
        """All rows."""
        return self._fetch(params, one=False)

    def run(self, *params: Any) -> None:
        """Execute without fetching (INSERT/UPDATE/DELETE inside
        transactions)."""
        with self._db.conn.cursor() as cur:
            if params:
                cur.execute(self._sql, params)
            else:
                cur.execute(self._sql)

    def _fetch(self, params: tuple, *, one: bool) -> dict | list[dict] | None:
        with self._db.conn.cursor() as cur:
            if params:
                cur.execute(self._sql, params)
            else:
                # Plain execute skips psycopg's placeholder parsing.
                cur.execute(self._sql)
            if one:
                return cur.fetchone()
            return cur.fetchall()


class Db:
    """Database handle — wraps a single sync psycopg3 connection."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def exec(self, sql: str) -> None:
        """Execute one or more SQL statements (split on ;)."""
        for stmt in sql.split(";"):
            trimmed = stmt.strip()
            if trimmed:
                with self.conn.cursor() as cur:
                    cur.execute(trimmed)

    def prepare(self, sql: str) -> Query:
        """Compile a parameterized query and return { get, all, run }."""
        return Query(self, sql)

    def transaction(self, fn: Callable[["Db"], Any]) -> Any:
        """Run fn inside a transaction. fn receives a tx Db handle; the
        transaction commits on success and rolls back on exception."""
        with self.conn.transaction():
            return fn(self)

    def close(self) -> None:
        """Close the connection."""
        self.conn.close()


def connect(url: str | None = None) -> Db:
    """Open a sync psycopg3 connection and return a Db handle."""
    return Db(
        psycopg.connect(url or database_url(), row_factory=dict_row, autocommit=True),
    )
