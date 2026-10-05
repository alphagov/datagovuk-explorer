"""Unit tests for scripts.ingest_collections parsing helpers."""

from scripts.ingest_collections import _normalise_slug, parse_collection


class TestNormaliseSlug:
    def test_passthrough(self):
        assert _normalise_slug("transport/road-traffic") == "transport/road-traffic"

    def test_slug_alias(self):
        assert _normalise_slug("people") == "people/births"

    def test_category_alias(self):
        assert _normalise_slug("government/election-results") == "government-and-parliament/election-results"

    def test_slug_alias_takes_precedence(self):
        assert _normalise_slug("government") == "government-and-parliament/election-results"

    def test_no_slash(self):
        assert _normalise_slug("environment") == "environment/weather"

    def test_unknown_passthrough(self):
        assert _normalise_slug("something/else") == "something/else"

    def test_unknown_no_slash(self):
        assert _normalise_slug("unknown") == "unknown"


class TestParseCollection:
    def test_valid_file(self, tmp_path):
        md = tmp_path / "topic" / "page.md"
        md.parent.mkdir()
        md.write_text("---\ntitle: My Page\nstatus: live\n---\nSome description.")
        rec = parse_collection(md, tmp_path)
        assert rec["slug"] == "topic/page"
        assert rec["collection"] == "topic"
        assert rec["title"] == "My Page"
        assert rec["description"] == "Some description."
        assert rec["status"] == "live"

    def test_no_frontmatter(self, tmp_path):
        md = tmp_path / "page.md"
        md.write_text("Just some text, no frontmatter.")
        assert parse_collection(md, tmp_path) == {}

    def test_unclosed_frontmatter(self, tmp_path):
        md = tmp_path / "page.md"
        md.write_text("---\ntitle: Broken")
        assert parse_collection(md, tmp_path) == {}

    def test_empty_body(self, tmp_path):
        md = tmp_path / "topic" / "page.md"
        md.parent.mkdir()
        md.write_text("---\ntitle: No Body\n---\n")
        rec = parse_collection(md, tmp_path)
        assert rec["description"] is None

    def test_optional_fields_default_to_none(self, tmp_path):
        md = tmp_path / "topic" / "page.md"
        md.parent.mkdir()
        md.write_text("---\ntitle: Minimal\n---\nBody.")
        rec = parse_collection(md, tmp_path)
        for key in ("websites", "api", "dataset", "page_last_updated", "visualisation_data"):
            assert rec[key] is None
