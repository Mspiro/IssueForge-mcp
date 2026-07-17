"""Unit tests for ContribModuleDetector."""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.contrib_module_detector import ContribModuleDetector


def _meta(**kwargs):
    base = {"title": None, "component": None, "problem_description_html": None,
            "version": None, "tags": None}
    base.update(kwargs)
    return base


class TestProjectLinks:
    def test_detects_drupal_org_link(self):
        meta = _meta(problem_description_html='See <a href="https://drupal.org/project/gin">gin</a>')
        assert "gin" in ContribModuleDetector.detect(meta)

    def test_ignores_drupal_core_in_link(self):
        meta = _meta(problem_description_html="drupal.org/project/drupal is the core repo")
        detected = ContribModuleDetector.detect(meta)
        assert "drupal" not in detected

    def test_multiple_links(self):
        meta = _meta(problem_description_html=(
            "drupal.org/project/webform and drupal.org/project/token required"
        ))
        detected = ContribModuleDetector.detect(meta)
        assert "webform" in detected
        assert "token" in detected


class TestComposerRequirePattern:
    def test_composer_require_detected(self):
        meta = _meta(problem_description_html="Run `composer require drupal/pathauto`")
        assert "pathauto" in ContribModuleDetector.detect(meta)

    def test_bare_drupal_slash(self):
        meta = _meta(problem_description_html="Install drupal/paragraphs as a dependency")
        assert "paragraphs" in ContribModuleDetector.detect(meta)

    def test_issue_url_not_misread_as_composer_package(self):
        # Regression: drupal.org/project/drupal/issues/NNN contains the
        # substring "drupal/issues", which the composer-require regex used
        # to misread as `composer require drupal/issues`.
        meta = _meta(problem_description_html=(
            "This was added in https://www.drupal.org/project/drupal/issues/2557815: "
            "Automatically bubble the cache context"
        ))
        detected = ContribModuleDetector.detect(meta)
        assert "issues" not in detected


class TestKeywordFallback:
    def test_known_module_keyword(self):
        meta = _meta(title="Bug in paragraphs field rendering")
        assert "paragraphs" in ContribModuleDetector.detect(meta)

    def test_core_module_not_flagged(self):
        meta = _meta(problem_description_html="This affects the views module in core")
        # "views" is in KNOWN_MODULES but also in CORE_MODULES — should NOT be detected
        # (it would only be excluded if listed in CORE_MODULES; views IS in core_modules)
        detected = ContribModuleDetector.detect(meta)
        assert "views" not in detected

    def test_empty_metadata(self):
        assert ContribModuleDetector.detect(_meta()) == []

    def test_no_duplicates(self):
        # Both a link and a keyword mention the same module
        meta = _meta(
            problem_description_html=(
                "drupal.org/project/webform — install drupal/webform"
            )
        )
        detected = ContribModuleDetector.detect(meta)
        assert detected.count("webform") == 1


class TestAmbiguousKeywords:
    """
    Regression coverage for a real false-positive: a core layout_builder
    issue (#3115759) got "entity" and "flag" injected as contrib
    dependencies purely because those words appeared in ordinary prose
    ("an entity+bundle", "a feature flag module") with no relation to the
    drupal.org/project/entity or /flag contrib modules.
    """

    def test_generic_entity_prose_not_flagged(self):
        meta = _meta(problem_description_html=(
            "Whenever a new field is added to an entity+bundle with LB "
            "enabled, a instance of the field is added to the layout."
        ))
        assert "entity" not in ContribModuleDetector.detect(meta)

    def test_generic_feature_flag_prose_not_flagged(self):
        meta = _meta(problem_description_html=(
            "Added a new feature flag module to control if new fields "
            "are added to the layout."
        ))
        assert "flag" not in ContribModuleDetector.detect(meta)

    def test_explicit_the_x_module_phrasing_still_detected(self):
        meta = _meta(problem_description_html=(
            "You'll need the Flag module installed for this to work."
        ))
        assert "flag" in ContribModuleDetector.detect(meta)

    def test_explicit_link_still_detected_regardless_of_ambiguity(self):
        meta = _meta(problem_description_html="drupal.org/project/entity")
        assert "entity" in ContribModuleDetector.detect(meta)
