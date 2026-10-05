"""One-off: undo migration 0009 (links.created → timestamptz, drop year_created).

Run once against a dev DB that had 0009 applied, after reverting the Phase 3
code. Recreates the derived links.year_created column, restores links.created
to text, rebuilds idx_links_year, and removes the 0009 row from
django_migrations so `manage.py migrate` sees 0008 as the latest.

Throwaway — delete after use. Uses raw SQL (no app imports) so it works with
the code already reverted. Quick and dirty, not idempotent-proof beyond the
IF EXISTS / type guards.

    uv run --env-file .env python scripts/revert_0009_links.py
"""

import os

import psycopg

STATEMENTS = [
    "ALTER TABLE links ADD COLUMN IF NOT EXISTS year_created text",
    # Re-derive the year from the dataset, pinned to UTC (the ingest convention).
    """
    UPDATE links l
       SET year_created = EXTRACT(YEAR FROM d.metadata_created AT TIME ZONE 'UTC')::text
      FROM datasets d
     WHERE d.id = l.dataset_id
       AND l.year_created IS NULL
    """,
    "CREATE INDEX IF NOT EXISTS idx_links_year ON links (year_created)",
    # links.created back to the original ISO text form (only if it was converted).
    """
    DO $$
    BEGIN
      IF (SELECT data_type FROM information_schema.columns
           WHERE table_name = 'links' AND column_name = 'created') <> 'text' THEN
        ALTER TABLE links ALTER COLUMN created TYPE text
          USING to_char(created AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US');
      END IF;
    END $$;
    """,
    ("DELETE FROM django_migrations WHERE app = 'explorer' AND name = '0009_links_created_drop_year_created'"),
]


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set (use: uv run --env-file .env ...)")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        for stmt in STATEMENTS:
            cur.execute(stmt)
        cur.execute("SELECT count(*), count(year_created) FROM links")
        total, with_year = cur.fetchone()
        cur.execute(
            "SELECT data_type FROM information_schema.columns WHERE table_name = 'links' AND column_name = 'created'",
        )
        created_type = cur.fetchone()[0]
    print(f"links: {total} rows, {with_year} with year_created")
    print(f"links.created type: {created_type}")
    print("reverted 0009 — run `just migrate` to confirm it is a no-op")


if __name__ == "__main__":
    main()
