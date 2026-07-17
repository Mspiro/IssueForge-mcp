"""Unit tests for provision_env's IDE workspace file generation."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

import provision_env


def _write_and_load(tmp_path, issue_id, env_path, work_root):
    provision_env._write_workspace_file(
        issue_id, env_path, work_root, output_dir=str(tmp_path)
    )
    ws_file = tmp_path / f"env-{issue_id}.code-workspace"
    return json.loads(ws_file.read_text())


class TestWriteWorkspaceFile:
    def test_core_issue_has_two_folders(self, tmp_path):
        env = tmp_path / "env_123"
        env.mkdir()
        data = _write_and_load(tmp_path, "123", str(env), str(env))
        assert len(data["folders"]) == 2

    def test_contrib_issue_adds_nested_repo_folder(self, tmp_path):
        # Regression coverage: the nested modules/contrib/<name> repo was
        # never added as a workspace folder, so VS Code's Source Control
        # panel could not show the applied MR/patch diff at all (nested git
        # repos are not scanned, and openRepositoryInParentFolders is off).
        env = tmp_path / "env_2915538"
        module = env / "modules" / "contrib" / "encrypt"
        module.mkdir(parents=True)
        data = _write_and_load(tmp_path, "2915538", str(env), str(module))
        paths = [f["path"] for f in data["folders"]]
        names = [f["name"] for f in data["folders"]]
        assert str(module) in paths
        assert "encrypt (issue #2915538 repo)" in names
        assert len(data["folders"]) == 3

    def test_missing_work_root_falls_back_to_two_folders(self, tmp_path):
        env = tmp_path / "env_9"
        env.mkdir()
        data = _write_and_load(tmp_path, "9", str(env), str(env / "does_not_exist"))
        assert len(data["folders"]) == 2
