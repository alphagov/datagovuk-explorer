r"""Sync query layer for the Explorer — raw SQL through django.db.connection
with psycopg3's native `%s` placeholders.

Organised by data domain, not by consuming view: import from the module
for the table you're querying. Nothing is re-exported from the package
root, so a view's imports show exactly which domains it touches.

Two row-shape gotchas:
- jsonb columns come back as JSON strings (Django's psycopg backend
  registers str loaders for raw cursors) — the views keep their
  json.loads calls.
- A literal `%` must be doubled (%%…%%) — psycopg3 treats it as a
  placeholder; see core.py.
"""
