# Comment plan

Where we're taking comments across this codebase, and how to review one.

## Goal

Comments should be **short, simple and helpful**. The code should be easy
to follow on its own; a comment earns its place by adding context the code
doesn't show. Most comments don't need to be historical — they should
describe the code as it is now.

## Rules of thumb

1. **No history.** Cut or reword anything that describes how things used to
   be, or a past version of this code:
   - "used to be filtered in Python... now it's SQL"
   - "workstream E/F", "docs/pagination-plan.md"
   - "the old Python sorter", "mirrors the old `_apply_filters`"
   - "no longer its own nav item" → "not a top-level nav item"
   - references to earlier apps, earlier versions ("v1"), or "we moved this"
   If the current behaviour is what matters, just state it.

2. **Plain language, no jargon.** If you need to stop and decode a word,
   so will the next reader:
   - "the ORDER BY tail pins tied rows" → "If sort values tie, order by id.
     Keeps pages stable."
   - "tiebreak", "pins", "unpinned ORDER BY", "trailing bucket" → only keep
     if it's the established UI term (e.g. facet "trailing bucket" is used
     on the pages themselves); otherwise say what happens in plain words.

3. **Don't restate the code.** Delete comments that just name what the next
   line does:
   ```python
   s = re.sub(r"[^a-z0-9]+", "-", s)  # non-alphanumeric → dash   ← cut
   s = re.sub(r"^-+|-+$", "", s)      # trim dashes                ← cut
   return s[:80]                       # keep reasonable length     ← cut
   ```

4. **Keep genuinely useful "why" — short.** Rationale that prevents a
   future regression or a wrong edit stays, but trimmed to a couple of
   lines:
   - dedup rule: "latest ok review per dataset — later in the file =
     higher id"
   - psycopg3: "ILIKE patterns are doubled (%%…%%) because psycopg3 treats
     a single % as a placeholder"
   - API report: "a JSON resource only counts as an API when its URL looks
     like a service endpoint, not a .json file"
   - "not a FK: the build truncates both tables independently"

5. **Beware stale specifics.** Numbers that evidence a *design decision*
   (e.g. why ArcGIS REST labels collapse to one bucket) can stay, but
   prefer the decision to the figure — "ONS alone accounts for 73%",
   "930 of 931 orgs", "up to 5.6k rows" will drift.

6. **Section banners are fine.** Keep the structural headers
   (`# --- /datasets query builder ---`, `# ── Memoised fixed fetches ──`)
   — they help navigate long files. Only the prose under them gets cut.

7. **Tests follow the same rules.** Short per-case annotations are
   useful and current — keep things like `# en dash` next to a magic input
   string. Apply rules 1–5 to anything long or historical in tests too.

## Reviewing a comment

Ask, in order:

1. Does it say anything the code doesn't already show? If no → cut.
2. Is it about the past? → cut, or rewrite to describe the present.
3. Is it more than ~2–4 lines? → can it be shorter?
4. Would a reader have to decode a word ("tail", "pin")? → reword.
5. Is it a "why" that stops a future mistake? → keep, short.

## Progress so far

Done:

- `explorer/queries/*` — all modules trimmed (history, jargon, long
  return-shape docstrings).
- `explorer/views/*` — trimmed (pagination-plan refs, "old Python rules",
  "no longer" phrasing in tests).
- `explorer/helpers.py` — fixed mangled docstring.
- `scripts/download_datasets.py`, `scripts/build_db.py` — first pass
  (docstring wraps, "tail" wording, format-bucket essay, restating
  comments).  (commits `9f79fa0`, `3c4861d`)
- Rest of `scripts/` (commit `ffb1849`): `build_series.py` (stale
  root_title/DATE_PATTERNS comments now match the code; figures dropped
  from `MIN_WORDS`; "planned follow-up" cut), `experiment_series.py`
  (v1/tail comments stale now that the range patterns live in
  build_series — noted at the top), `review_suggest.py` ("earlier
  outputs", JS `appendFileSync` ref, wrong `process_one` pointer),
  `embeddings.py`, `embed_only.py` (broken comment wrap + UTF-16 corner
  note), `fetch_harvest_sources.py` (site-count figure), `ingest_link_errors.py`
  (run dates + ~figures in the docstring), `rate_limit.py` (dead
  "async version" ref), `db.py` (docstring essay trimmed).
- `config/settings.py` — long WhiteNoise/static comments trimmed to the
  essential why.
- Test sweep — tests keep their short per-case annotations; long or
  jargon-y ones were reworded: "pins"/"tiebreak"/"workstream E/F"/
  "regression ... fixed"/plan-doc refs in `explorer/tests`, hash-test
  "pins" and the "(verified: ...)" aside in `tests/`.

Clean with nothing to change: `scripts/query_datasets.py`,
`fetch_organisations.py`, `ingest_reviews.py`, `download_llm.py`.

A useful starting point is a comment inventory by file:

```bash
python3 - <<'EOF'
import tokenize, pathlib
for p in sorted(pathlib.Path('.').rglob('*.py')):
    parts = p.resolve().parts
    if any(x in parts for x in ('.venv','node_modules','__pycache__','.git',
                                 'migrations','.mypy_cache','.pytest_cache','.ruff_cache')):
        continue
    try:
        toks = list(tokenize.tokenize(open(p,'rb').readline))
    except Exception:
        continue
    n = sum(1 for t in toks if t.type == tokenize.COMMENT)
    if n: print(n, p)
EOF
```
