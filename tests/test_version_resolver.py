"""Unit tests for VersionResolver."""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.version_resolver import VersionResolver


class TestNormalizeBranch:
    def test_main_maps_to_11x(self):
        assert VersionResolver.normalize_branch("main") == "11.x"

    def test_dev_suffix_stripped(self):
        assert VersionResolver.normalize_branch("11.x-dev") == "11.x"
        assert VersionResolver.normalize_branch("10.3.x-dev") == "10.3.x"

    def test_annotation_stripped(self):
        assert VersionResolver.normalize_branch("4.0.x-dev (D10)") == "4.0.x"

    def test_empty_maps_to_11x(self):
        assert VersionResolver.normalize_branch("") == "11.x"
        assert VersionResolver.normalize_branch(None) == "11.x"

    def test_plain_branch_unchanged(self):
        assert VersionResolver.normalize_branch("10.x") == "10.x"


class TestDetectCoreFromContribVersion:
    def test_explicit_d10_hint(self):
        assert VersionResolver._detect_core_from_contrib_version("4.0.x-dev (D10)") == "10"

    def test_explicit_d11_hint(self):
        assert VersionResolver._detect_core_from_contrib_version("3.x-dev (D11)") == "11"

    def test_drupal_long_form_hint(self):
        assert VersionResolver._detect_core_from_contrib_version("2.x (Drupal 10)") == "10"

    def test_semver_prefix_10x(self):
        assert VersionResolver._detect_core_from_contrib_version("10.x-3.x-dev") == "10"

    def test_plain_semver_defaults_to_latest(self):
        # No core hint → falls back to CONTRIB_LEGACY_CORE_DEFAULT
        result = VersionResolver._detect_core_from_contrib_version("2.0.0")
        assert result == VersionResolver.CONTRIB_LEGACY_CORE_DEFAULT

    def test_none_defaults_to_latest(self):
        assert VersionResolver._detect_core_from_contrib_version(None) == VersionResolver.CONTRIB_LEGACY_CORE_DEFAULT

    def test_legacy_8x_prefix_defaults_to_latest_core(self):
        # Regression coverage: "8.x-3.x-dev" is the pre-D9 legacy contrib
        # branch naming scheme, not a literal "requires Drupal 8" signal.
        # This used to resolve to "8", producing checkout_ref "8.x" — a
        # branch that doesn't exist in Drupal core — which broke cloning
        # for every "8.x-*" contrib module (e.g. encrypt's "8.x-3.x-dev").
        result = VersionResolver._detect_core_from_contrib_version("8.x-3.x-dev")
        assert result == VersionResolver.CONTRIB_LEGACY_CORE_DEFAULT


class TestResolveCore:
    def test_main_gives_drupal11(self):
        meta = {"project_name": "drupal", "version": "main"}
        r = VersionResolver.resolve(meta)
        assert r["checkout_ref"] == "11.x"
        assert r["project_type"] == "drupal11"

    def test_10x_gives_drupal10(self):
        meta = {"project_name": "drupal", "version": "10.3.x-dev"}
        r = VersionResolver.resolve(meta)
        assert r["checkout_ref"] == "10.3.x"
        assert r["project_type"] == "drupal10"

    def test_9x_gives_drupal9(self):
        meta = {"project_name": "drupal", "version": "9.5.x-dev"}
        r = VersionResolver.resolve(meta)
        assert r["project_type"] == "drupal9"


class TestResolveContrib:
    def test_contrib_with_d10_hint_uses_d10_core(self):
        meta = {"project_name": "paragraphs", "version": "4.0.x-dev (D10)"}
        r = VersionResolver.resolve(meta)
        assert r["checkout_ref"] == "10.x"
        assert r["project_type"] == "drupal10"
        assert r["contrib_branch"] == "4.0.x"

    def test_contrib_no_hint_defaults_to_latest_core(self):
        meta = {"project_name": "views_bulk_operations", "version": "4.x-dev"}
        r = VersionResolver.resolve(meta)
        assert r["checkout_ref"] == f"{VersionResolver.CONTRIB_LEGACY_CORE_DEFAULT}.x"

    def test_contrib_branch_in_result(self):
        meta = {"project_name": "webform", "version": "6.x-dev (D10)"}
        r = VersionResolver.resolve(meta)
        assert "contrib_branch" in r
        assert r["contrib_branch"] == "6.x"

    def test_contrib_legacy_8x_version_gives_valid_core_branch(self):
        # End-to-end regression for the encrypt module provisioning failure:
        # checkout_ref must be a real Drupal core branch, and contrib_branch
        # must stay the module's own "8.x-3.x" branch for its own clone.
        meta = {"project_name": "encrypt", "version": "8.x-3.x-dev"}
        r = VersionResolver.resolve(meta)
        assert r["checkout_ref"] == f"{VersionResolver.CONTRIB_LEGACY_CORE_DEFAULT}.x"
        assert r["contrib_branch"] == "8.x-3.x"
