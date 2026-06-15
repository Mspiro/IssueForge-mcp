"""Unit tests for IssuePreviewer.format_report and format_analysis_summary — no network calls."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.issue_previewer import IssuePreviewer

_PLAN = {
    "issue_title": "EntityAutocomplete allows multiple values when #tags is FALSE",
    "detected_subsystems": ["entity_reference", "form_api"],
    "suggested_fix_strategies": ["Add validation in validateEntityAutocomplete"],
    "reproduction_steps": [
        "Create a form with an entity_reference field",
        "Set #tags = FALSE",
        "Submit multiple values",
    ],
    "detected_mrs": [
        {"mr_iid": "1234", "url": "https://git.drupalcode.org/project/drupal/-/merge_requests/1234",
         "title": "Fix validator", "state": "opened"},
    ],
    "environment_plan": {
        "checkout_ref": "11.x",
        "php_version": "8.3",
        "project_name": "drupal",
        "is_contrib": False,
        "contrib_modules": [],
        "required_modules": ["entity_reference"],
        "latest_patch_id": "9130901",
    },
    "llm_analysis": {
        "root_cause": "Missing cardinality check in validateEntityAutocomplete",
        "risk_level": "low",
        "confidence": "high",
    },
}


class TestFormatAnalysisSummary:
    def test_shows_branch_and_php(self):
        report = IssuePreviewer.format_analysis_summary(_PLAN)
        assert "11.x" in report
        assert "8.3" in report

    def test_shows_root_cause(self):
        report = IssuePreviewer.format_analysis_summary(_PLAN)
        assert "cardinality" in report

    def test_shows_patch_id(self):
        report = IssuePreviewer.format_analysis_summary(_PLAN)
        assert "9130901" in report

    def test_shows_mr(self):
        report = IssuePreviewer.format_analysis_summary(_PLAN)
        assert "!1234" in report

    def test_shows_reproduction_steps(self):
        report = IssuePreviewer.format_analysis_summary(_PLAN)
        assert "entity_reference field" in report

    def test_no_patch_shows_none(self):
        plan = {**_PLAN, "environment_plan": {**_PLAN["environment_plan"], "latest_patch_id": None}}
        report = IssuePreviewer.format_analysis_summary(plan)
        assert "none uploaded" in report

_PREVIEW = {
    "issue_id": "2692289",
    "issue_url": "https://www.drupal.org/project/drupal/issues/2692289",
    "title": "EntityAutocomplete form element allows multiple values when #tags is FALSE",
    "status": "Needs review",
    "priority": "Normal",
    "category": "Bug report",
    "component": "entity_reference.module",
    "version": "9.5.x-dev",
    "project": "drupal",
    "created": "2016-02-10",
    "updated": "2024-03-01",
    "total_comments": 42,
    "patches": [
        {"id": "9130901", "filename": "2692289-fix.patch", "size": 3072, "url": ""},
        {"id": "9130902", "filename": "2692289-tests.patch", "size": 1024, "url": ""},
    ],
    "detected_mrs": [
        {
            "project": "drupal",
            "mr_iid": "1234",
            "url": "https://git.drupalcode.org/project/drupal/-/merge_requests/1234",
            "title": "Fix EntityAutocomplete",
            "state": "opened",
            "target_branch": "11.x",
        }
    ],
    "discussion_summary": "• Bug: multi-value input silently accepted\n• Fix proposed in MR !1234",
}


class TestFormatReport:
    def test_contains_issue_id(self):
        report = IssuePreviewer.format_report(_PREVIEW)
        assert "2692289" in report

    def test_contains_title(self):
        report = IssuePreviewer.format_report(_PREVIEW)
        assert "EntityAutocomplete" in report

    def test_contains_patch_filenames(self):
        report = IssuePreviewer.format_report(_PREVIEW)
        assert "2692289-fix.patch" in report
        assert "2692289-tests.patch" in report

    def test_contains_mr_info(self):
        report = IssuePreviewer.format_report(_PREVIEW)
        assert "!1234" in report
        assert "opened" in report
        assert "11.x" in report

    def test_contains_discussion_summary(self):
        report = IssuePreviewer.format_report(_PREVIEW)
        assert "multi-value" in report

    def test_no_patches_shows_none(self):
        preview = {**_PREVIEW, "patches": []}
        report = IssuePreviewer.format_report(preview)
        assert "None uploaded" in report

    def test_no_mrs_shows_none(self):
        preview = {**_PREVIEW, "detected_mrs": []}
        report = IssuePreviewer.format_report(preview)
        assert "None detected" in report

    def test_patch_size_in_kb(self):
        report = IssuePreviewer.format_report(_PREVIEW)
        assert "3 KB" in report
