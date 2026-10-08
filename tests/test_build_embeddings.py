"""Unit tests for scripts/build_embeddings.py (offline — no llama-server, no DB).

Covers the deterministic algorithmic core:
- build_texts: EmbeddingGemma document prompt (`title: … | text: …`),
  desc[:500] truncation, theme/tags insertion into the body, whitespace
  collapse, and None when an item has no title and no body
- assemble_batch: null-skipping + origIndex mapping (the request/response
  alignment logic)
- constants: DIM 768, BATCH 256, model

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
from scripts.embed_text import format_document


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


def doc(title, content=""):
    # Built with the real formatter; format_document itself is covered below.
    return format_document(title, content)


def test_constants():
    assert be.DIM == 768
    assert be.BATCH == 256
    assert be.MODEL == "embeddinggemma-300m"
    assert "embeddinggemma-300m-qat-Q8_0.gguf" in be.LLAMA_SERVER
    assert "--pooling mean" in be.LLAMA_SERVER
    assert "--ctx-size 8192" in be.LLAMA_SERVER


def test_basic_title_only():
    rows = [row("a1", "Planning Applications 2020")]
    assert be.build_texts(rows) == [doc("Planning Applications 2020")]


def test_desc_appended():
    rows = [row("a1", "Planning Applications 2020", desc="Applications received and decided.")]
    assert be.build_texts(rows) == [
        doc("Planning Applications 2020", "Applications received and decided."),
    ]


def test_desc_truncated_to_500():
    desc = "x" * 700
    texts = be.build_texts([row("a1", "Long Desc", desc=desc)])
    assert texts == [doc("Long Desc", "x" * 500)]
    # exactly 500 passes through whole
    assert be.build_texts([row("a1", "T", desc="y" * 500)]) == [doc("T", "y" * 500)]


def test_null_or_empty_desc():
    assert be.build_texts([row("a1", "Title Only", desc=None)]) == [doc("Title Only")]
    assert be.build_texts([row("a1", "Title Only", desc="")]) == [doc("Title Only")]


def test_whitespace_collapse():
    rows = [row("a1", "  Census   Data \n 2021 ", desc="  Multiple\tspaces\nin desc.\n")]
    texts = be.build_texts(rows)
    assert texts == [doc("Census Data 2021", "Multiple spaces in desc.")]


def test_ordering_preserved():
    rows = [
        row("a1", "First", desc="desc one"),
        row("a2", "Second"),
        row("a3", "  Third  ", desc="desc three"),
    ]
    texts = be.build_texts(rows)
    assert texts[0] == doc("First", "desc one")
    assert texts[1] == doc("Second")
    assert texts[2] == doc("Third", "desc three")


def test_theme_appended():
    rows = [row("a1", "Roads", theme="transport")]
    assert be.build_texts(rows) == [doc("Roads", "Theme: transport.")]


def test_tags_appended():
    rows = [row("a1", "Roads", tags='["roads", "bridges", "traffic"]')]
    assert be.build_texts(rows) == [doc("Roads", "Tags: roads, bridges, traffic.")]


def test_theme_and_tags_and_desc():
    rows = [row("a1", "Flood risk", theme="environment", tags='["flood", "rivers"]', desc="River data.")]
    assert be.build_texts(rows) == [
        doc("Flood risk", "River data. Theme: environment. Tags: flood, rivers."),
    ]


def test_null_theme_and_tags_omitted():
    rows = [row("a1", "Title", desc="Some desc.", theme=None, tags=None)]
    assert be.build_texts(rows) == [doc("Title", "Some desc.")]


def test_empty_tags_json_omitted():
    rows = [row("a1", "Title", tags="[]")]
    assert be.build_texts(rows) == [doc("Title")]


def test_fallback_to_orig_title():
    rows = [row("a1", title=None, orig_title="Original Title")]
    assert be.build_texts(rows) == [doc("Original Title")]


def test_fallback_to_notes():
    rows = [row("a1", "Title", desc=None, notes="Original notes.")]
    assert be.build_texts(rows) == [doc("Title", "Original notes.")]


def test_suggested_title_takes_precedence():
    rows = [row("a1", title="Better Title", orig_title="Old Title")]
    assert be.build_texts(rows) == [doc("Better Title")]


def test_suggested_desc_takes_precedence():
    rows = [row("a1", "Title", desc="Better desc.", notes="Old notes.")]
    assert be.build_texts(rows) == [doc("Title", "Better desc.")]


def test_missing_title_uses_literal_none():
    rows = [row("a1", title=None, orig_title=None, desc="Body only.")]
    assert be.build_texts(rows) == [doc(None, "Body only.")]


def test_no_title_no_body_is_none():
    rows = [row("a1", title=None, orig_title=None, desc=None, notes=None)]
    assert be.build_texts(rows) == [None]


def test_format_document():
    assert format_document("A title", "Some body.") == "title: A title | text: Some body."
    # Empty body still keeps the title.
    assert format_document("A title", "") == "title: A title | text:"
    # Whitespace collapsed and trimmed in both fields.
    assert format_document("  A   title ", " a\n body ") == "title: A title | text: a body"
    # Nothing at all -> None so the caller stores a zero vector.
    assert format_document(None, None) is None
    assert format_document("", "   ") is None


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
