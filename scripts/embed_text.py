"""Document text formatting shared by the embedding builders.

The embedding pipeline uses EmbeddingGemma-300M, which expects a task prompt
prepended to each input (see the model card). Every vector we store is a
*document*, so all of them use the document prompt

    title: {title} | text: {content}

with the literal string ``none`` when a title is missing. The model also
defines a *query* prompt (``task: search result | query: ``), which we
deliberately do not use: the app's semantic relatedness probes one stored
document embedding against the others (``explorer/queries/embeddings.py``),
so no query text is ever embedded at request time.

Both builders must format text identically — a prompt mismatch silently
degrades the KNN results without any error:

- ``scripts/build_embeddings.py`` (dataset embeddings)
- ``scripts/ingest_collections.py`` (collection embeddings)
"""

import re

_WS_RE = re.compile(r"\s+")


def format_document(title: str | None, content: str | None) -> str | None:
    """Format one item as an EmbeddingGemma document.

    title: the item's title (falls back to the literal "none").
    content: the body — description, theme, tags, etc. May be empty.

    Whitespace is collapsed and the result trimmed. Returns None when both
    title and content are empty, so the caller can skip the item (its row is
    stored as a zero vector).
    """

    title = (title or "").strip()
    content = _WS_RE.sub(" ", content or "").strip()
    if not title and not content:
        return None
    doc = f"title: {title or 'none'} | text: {content}"
    return _WS_RE.sub(" ", doc).strip()
