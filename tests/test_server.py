"""Unit tests for IssueForgeServer's comment-thread helpers."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server import IssueForgeServer


class TestCleanCommentHtml:
    def test_strips_real_formatting_tags(self):
        result = IssueForgeServer._clean_comment_html("<p>Hello <em>world</em></p>")
        assert result == "Hello world"

    def test_preserves_intentionally_escaped_example_markup(self):
        # A commenter quoting real HTML as evidence (e.g. showing rendered
        # markup for comparison) encodes it as entities so it displays as
        # literal text, not real tags. Stripping tags BEFORE unescaping
        # entities (not after) means this literal example survives instead
        # of being destroyed as if it were comment formatting.
        result = IssueForgeServer._clean_comment_html(
            "<p>I see: &lt;label for=&quot;x&quot;&gt;Test&lt;/label&gt;</p>"
        )
        assert '<label for="x">Test</label>' in result

    def test_collapses_whitespace(self):
        result = IssueForgeServer._clean_comment_html("<p>Line one</p>\n\n<p>Line two</p>")
        assert result == "Line one Line two"

    def test_empty_input_returns_empty_string(self):
        assert IssueForgeServer._clean_comment_html("") == ""
        assert IssueForgeServer._clean_comment_html(None) == ""


class TestFormatCommentDate:
    def test_formats_unix_timestamp(self):
        # 2026-07-28 00:00:00 UTC-ish; just check the date portion format.
        result = IssueForgeServer._format_comment_date(1785196800)
        assert result.count("-") == 2
        assert result.startswith("2026-")

    def test_none_timestamp_returns_empty_string(self):
        assert IssueForgeServer._format_comment_date(None) == ""

    def test_invalid_timestamp_returns_empty_string(self):
        assert IssueForgeServer._format_comment_date("not-a-timestamp") == ""
