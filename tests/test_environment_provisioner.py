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
