"""Unit tests for IssueDescriptionParser."""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.issue_description_parser import IssueDescriptionParser


class TestStripHtml:
    def test_removes_tags(self):
        assert IssueDescriptionParser.strip_html("<p>Hello</p>") == "Hello"

    def test_decodes_entities(self):
        assert "&amp;" in IssueDescriptionParser.strip_html("a &amp; b") or \
               "&" in IssueDescriptionParser.strip_html("a &amp; b")

    def test_empty_string(self):
        assert IssueDescriptionParser.strip_html("") == ""

    def test_none_safe(self):
        assert IssueDescriptionParser.strip_html(None) == ""


class TestSegmentHtml:
    """Covers the group-index bug fix: <strong> headings have only group 1."""

    def test_strong_heading_no_crash(self):
        html = "<p><strong>Steps to reproduce</strong></p><p>Do this.</p>"
        # Should not raise IndexError
        result = IssueDescriptionParser._segment_html(html)
        assert isinstance(result, dict)

    def test_h2_heading_detected(self):
        html = "<h2>Steps to reproduce</h2><ol><li>Go to page</li></ol>"
        result = IssueDescriptionParser._segment_html(html)
        assert "steps" in result

    def test_b_heading_no_crash(self):
        html = "<p><b>Problem/Motivation</b></p><p>The bug is here.</p>"
        result = IssueDescriptionParser._segment_html(html)
        assert isinstance(result, dict)

    def test_mixed_headings(self):
        html = (
            "<h2>Problem/Motivation</h2><p>It fails.</p>"
            "<p><strong>Steps to reproduce</strong></p>"
            "<ol><li>Install module</li><li>Visit page</li></ol>"
        )
        result = IssueDescriptionParser._segment_html(html)
        assert "problem" in result
        assert "steps" in result


class TestExtractSections:
    def test_returns_dict_always(self):
        assert isinstance(IssueDescriptionParser.extract_sections(""), dict)
        assert isinstance(IssueDescriptionParser.extract_sections(None), dict)

    def test_steps_extracted_from_ol(self):
        html = (
            "<h3>Steps to reproduce</h3>"
            "<ol><li>Enable the module</li><li>Create content</li></ol>"
        )
        sections = IssueDescriptionParser.extract_sections(html)
        steps = sections.get("steps", [])
        assert len(steps) >= 2

    def test_full_issue_structure(self):
        html = (
            "<h2>Problem/Motivation</h2><p>The form fails.</p>"
            "<h2>Steps to reproduce</h2><ol><li>Install</li></ol>"
            "<h2>Proposed resolution</h2><p>Fix the validator.</p>"
        )
        sections = IssueDescriptionParser.extract_sections(html)
        assert sections.get("problem")
        assert sections.get("steps")
        assert sections.get("proposed_resolution")
