"""Unit tests for scripts/build_embeddings.py (offline — no llama-server, no DB).

Covers the deterministic algorithmic core:
- build_texts: BGE prefix, desc[:500] truncation, theme/tags insertion,
  whitespace collapse, title-only when all optional fields are empty
- assemble_batch: null-skipping + origIndex mapping (the request/response
  alignment logic)
- constants: DIM 768, BATCH 256, model, prefix

The full pipeline (texts -> llama-server -> pgvector write) is verified
separately against a scratch DB by comparing the stored embeddings with
float tolerance.

Run with: uv run pytest tests/test_build_embeddings.py
"""

import os

# The module-level guard fires on import if DATABASE_URL is unset — tests
# never connect, so give it a dummy URL.
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/test-db")

import scripts.build_embeddings as be


def row(id_, title=None, **kwargs):
    return {
        "id": id_,
        "title": title,
        "theme": None,
        "tags": None,
        "desc": None,
        "orig_title": None,
        "notes": None,
        **kwargs,
    }


PREFIX = "Represent this sentence for searching relevant passages: "


def test_constants():
    assert be.DIM == 768
    assert be.BATCH == 256
    assert be.MODEL == "bge-base-en-v1.5"
    assert be.BGE_PREFIX == PREFIX


def test_basic_title_only():
    rows = [row("a1", "Planning Applications 2020")]
    assert be.build_texts(rows) == [PREFIX + "Planning Applications 2020"]


def test_desc_appended():
    rows = [row("a1", "Planning Applications 2020", desc="Applications received and decided.")]
    assert be.build_texts(rows) == [
        PREFIX + "Planning Applications 2020 Applications received and decided.",
    ]


def test_desc_truncated_to_500():
    desc = "x" * 700
    texts = be.build_texts([row("a1", "Long Desc", desc=desc)])
    assert texts == [PREFIX + f"Long Desc {'x' * 500}"]
    # exactly 500 passes through whole
    assert be.build_texts([row("a1", "T", desc="y" * 500)]) == [PREFIX + "T " + "y" * 500]


def test_null_or_empty_desc():
    assert be.build_texts([row("a1", "Title Only", desc=None)]) == [PREFIX + "Title Only"]
    assert be.build_texts([row("a1", "Title Only", desc="")]) == [PREFIX + "Title Only"]


def test_whitespace_collapse():
    rows = [row("a1", "  Census   Data \n 2021 ", desc="  Multiple\tspaces\nin desc.\n")]
    texts = be.build_texts(rows)
    assert texts == [PREFIX + "Census Data 2021 Multiple spaces in desc."]


def test_ordering_preserved():
    rows = [
        row("a1", "First", desc="desc one"),
        row("a2", "Second"),
        row("a3", "  Third  ", desc="desc three"),
    ]
    texts = be.build_texts(rows)
    assert texts[0] == PREFIX + "First desc one"
    assert texts[1] == PREFIX + "Second"
    assert texts[2] == PREFIX + "Third desc three"


def test_theme_appended():
    rows = [row("a1", "Roads", theme="transport")]
    assert be.build_texts(rows) == [PREFIX + "Roads Theme: transport."]


def test_tags_appended():
    rows = [row("a1", "Roads", tags='["roads", "bridges", "traffic"]')]
    assert be.build_texts(rows) == [PREFIX + "Roads Tags: roads, bridges, traffic."]


def test_theme_and_tags_and_desc():
    rows = [row("a1", "Flood risk", theme="environment", tags='["flood", "rivers"]', desc="River data.")]
    assert be.build_texts(rows) == [
        PREFIX + "Flood risk Theme: environment. Tags: flood, rivers. River data.",
    ]


def test_null_theme_and_tags_omitted():
    rows = [row("a1", "Title", desc="Some desc.", theme=None, tags=None)]
    assert be.build_texts(rows) == [PREFIX + "Title Some desc."]


def test_empty_tags_json_omitted():
    rows = [row("a1", "Title", tags="[]")]
    assert be.build_texts(rows) == [PREFIX + "Title"]


def test_fallback_to_orig_title():
    rows = [row("a1", title=None, orig_title="Original Title")]
    assert be.build_texts(rows) == [PREFIX + "Original Title"]


def test_fallback_to_notes():
    rows = [row("a1", "Title", desc=None, notes="Original notes.")]
    assert be.build_texts(rows) == [PREFIX + "Title Original notes."]


def test_suggested_title_takes_precedence():
    rows = [row("a1", title="Better Title", orig_title="Old Title")]
    assert be.build_texts(rows) == [PREFIX + "Better Title"]


def test_suggested_desc_takes_precedence():
    rows = [row("a1", "Title", desc="Better desc.", notes="Old notes.")]
    assert be.build_texts(rows) == [PREFIX + "Title Better desc."]


def test_assemble_batch_skips_none():
    texts: list[str | None] = ["t0", None, "t2", "t3", None]
    inp, idx = be.assemble_batch(texts, 0, 5)
    assert inp == ["t0", "t2", "t3"]
    assert idx == [0, 2, 3]
    # partial window
    inp, idx = be.assemble_batch(texts, 2, 5)
    assert inp == ["t2", "t3"]
    assert idx == [2, 3]
    # window with only nulls
    inp, idx = be.assemble_batch(texts, 1, 2)
    assert inp == []
    assert idx == []
    # empty window
    inp, idx = be.assemble_batch(texts, 4, 4)
    assert inp == []
    assert idx == []
