"""Unit tests for EnvironmentProvisioner."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.environment_provisioner import EnvironmentProvisioner


class TestDetectOwnContribDependencies:
    def test_no_composer_json_returns_empty(self, tmp_path):
        result = EnvironmentProvisioner._detect_own_contrib_dependencies(str(tmp_path))
        assert result == []

    def test_extracts_drupal_package_dependencies(self, tmp_path):
        # Regression coverage: the issue's own contrib project (e.g. Encrypt)
        # is git-cloned directly rather than composer-required, so its own
        # composer.json dependencies (e.g. Encrypt -> Key) were previously
        # never fetched — `drush en` then failed with "is missing its
        # dependency module key" because the dependency's code didn't exist
        # anywhere in the environment.
        composer_json = {
            "name": "drupal/encrypt",
            "require": {
                "drupal/key": "^1",
                "php": ">=8.1",
            },
        }
        (tmp_path / "composer.json").write_text(json.dumps(composer_json))
        result = EnvironmentProvisioner._detect_own_contrib_dependencies(str(tmp_path))
        assert result == ["key"]

    def test_malformed_composer_json_returns_empty(self, tmp_path):
        (tmp_path / "composer.json").write_text("{not valid json")
        result = EnvironmentProvisioner._detect_own_contrib_dependencies(str(tmp_path))
        assert result == []

    def test_info_yml_fallback_when_no_composer_json(self, tmp_path):
        # Regression coverage: many contrib modules declare dependencies
        # only in info.yml (no composer.json at all). Entries use
        # "project:module" syntax; a "drupal:" prefix means a core module.
        (tmp_path / "webform_thing.info.yml").write_text(
            "name: Webform Thing\n"
            "type: module\n"
            "dependencies:\n"
            "  - webform:webform\n"
            "  - drupal:views\n"
            "  - token\n"
        )
        result = EnvironmentProvisioner._detect_own_contrib_dependencies(
            str(tmp_path), "webform_thing"
        )
        assert result == ["webform", "token"]

    def test_merges_composer_and_info_yml_without_duplicates(self, tmp_path):
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"drupal/key": "^1", "php": ">=8.1"}})
        )
        (tmp_path / "encrypt.info.yml").write_text(
            "name: Encrypt\ndependencies:\n  - key:key\n"
        )
        result = EnvironmentProvisioner._detect_own_contrib_dependencies(
            str(tmp_path), "encrypt"
        )
        assert result == ["key"]

    def test_excludes_core_modules_and_self(self, tmp_path):
        (tmp_path / "mymod.info.yml").write_text(
            "dependencies:\n  - system\n  - node\n  - mymod:submodule_of_self\n  - pathauto\n"
        )
        result = EnvironmentProvisioner._detect_own_contrib_dependencies(
            str(tmp_path), "mymod"
        )
        assert result == ["pathauto"]


class TestAddComposerReplace:
    def test_adds_replace_entry(self, tmp_path):
        # Regression coverage: without a replace entry, composer-requiring a
        # package that depends on the issue's own project (drupal/sodium →
        # drupal/encrypt) silently overwrote the git-cloned module with a
        # tagged release, destroying the dev checkout and issue remote.
        (tmp_path / "composer.json").write_text(
            json.dumps({"name": "drupal/drupal", "require": {}})
        )
        ok = EnvironmentProvisioner._add_composer_replace(str(tmp_path), "encrypt")
        assert ok is True
        data = json.loads((tmp_path / "composer.json").read_text())
        assert data["replace"]["drupal/encrypt"] == "*"

    def test_preserves_existing_replace_entries(self, tmp_path):
        (tmp_path / "composer.json").write_text(
            json.dumps({"replace": {"symfony/polyfill-php72": "*"}})
        )
        EnvironmentProvisioner._add_composer_replace(str(tmp_path), "webform")
        data = json.loads((tmp_path / "composer.json").read_text())
        assert data["replace"] == {
            "symfony/polyfill-php72": "*",
            "drupal/webform": "*",
        }

    def test_missing_composer_json_returns_false(self, tmp_path):
        assert EnvironmentProvisioner._add_composer_replace(str(tmp_path), "x") is False
