"""Unit tests for EnvironmentProvisioner."""
import json
import os
import socket
import sys
from unittest.mock import patch, MagicMock

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


class TestPortIsFree:
    def test_occupied_port_reports_not_free(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            assert EnvironmentProvisioner._port_is_free(port) is False
        finally:
            sock.close()

    def test_free_port_reports_free(self):
        # Reserve a port, close it immediately — no listener remains bound.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        assert EnvironmentProvisioner._port_is_free(port) is True


class TestFindFreePortPair:
    def test_skips_occupied_pair_and_finds_next(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        occupied = sock.getsockname()[1]
        try:
            http_port, https_port = EnvironmentProvisioner._find_free_port_pair(
                start=occupied, end=occupied + 20
            )
            assert http_port != occupied
            assert https_port == http_port + 1
        finally:
            sock.close()

    def test_raises_when_no_free_pair_in_range(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        occupied = sock.getsockname()[1]
        try:
            import pytest
            with pytest.raises(RuntimeError):
                EnvironmentProvisioner._find_free_port_pair(start=occupied, end=occupied + 2)
        finally:
            sock.close()


class TestEnsureRouterPortsFree:
    """
    Regression coverage for a real bug found testing MR !139 on #3392735:
    DDEV's fallback router port (33000) was silently held by an unrelated
    host process, and provisioning failed twice before the conflict was
    root-caused manually. `ddev poweroff` (the documented fix) didn't help
    since the conflict wasn't DDEV's own stale state.

    All these patch _ddev_router_is_running to False — a real one running
    on this machine (serving another environment) would short-circuit the
    check entirely, which is exactly TestDdevRouterIsRunning's job to cover.
    """

    def test_does_nothing_when_configured_ports_are_free(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        free_port = sock.getsockname()[1]
        sock.close()  # now genuinely free again

        fake_config = MagicMock(
            stdout=json.dumps({"raw": {
                "router-http-port": str(free_port),
                "router-https-port": str(free_port + 1),
            }})
        )
        with patch.object(EnvironmentProvisioner, "_ddev_router_is_running", return_value=False), \
             patch("subprocess.run", return_value=fake_config), \
             patch.object(EnvironmentProvisioner, "run_command") as mock_reconfigure:
            EnvironmentProvisioner._ensure_router_ports_free()
            mock_reconfigure.assert_not_called()

    def test_reconfigures_when_configured_port_is_occupied(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        occupied_port = sock.getsockname()[1]
        try:
            fake_config = MagicMock(
                stdout=json.dumps({"raw": {
                    "router-http-port": str(occupied_port),
                    "router-https-port": str(occupied_port + 1),
                }})
            )
            with patch.object(EnvironmentProvisioner, "_ddev_router_is_running", return_value=False), \
                 patch("subprocess.run", return_value=fake_config), \
                 patch.object(EnvironmentProvisioner, "run_command", return_value=True) as mock_reconfigure:
                EnvironmentProvisioner._ensure_router_ports_free()
                mock_reconfigure.assert_called_once()
                called_args = mock_reconfigure.call_args[0][0]
                assert called_args[:3] == ["ddev", "config", "global"]
                assert any(a.startswith("--router-http-port=") for a in called_args)
                assert any(a.startswith("--router-https-port=") for a in called_args)
        finally:
            sock.close()

    def test_skips_check_entirely_when_router_already_running(self):
        # The exact bug found in this session's own testing: env_3392735's
        # DDEV router was legitimately bound to the configured ports, and
        # without this guard the check misread that as a foreign-process
        # conflict and remapped global config unnecessarily.
        with patch.object(EnvironmentProvisioner, "_ddev_router_is_running", return_value=True), \
             patch("subprocess.run") as mock_run, \
             patch.object(EnvironmentProvisioner, "run_command") as mock_reconfigure:
            EnvironmentProvisioner._ensure_router_ports_free()
            mock_run.assert_not_called()
            mock_reconfigure.assert_not_called()


class TestDdevRouterIsRunning:
    def test_returns_true_when_docker_reports_router_running(self):
        fake_result = MagicMock(stdout="ddev-router\n")
        with patch("subprocess.run", return_value=fake_result):
            assert EnvironmentProvisioner._ddev_router_is_running() is True

    def test_returns_false_when_router_not_in_output(self):
        fake_result = MagicMock(stdout="")
        with patch("subprocess.run", return_value=fake_result):
            assert EnvironmentProvisioner._ddev_router_is_running() is False

    def test_returns_false_on_docker_command_failure(self):
        with patch("subprocess.run", side_effect=Exception("docker not found")):
            assert EnvironmentProvisioner._ddev_router_is_running() is False
