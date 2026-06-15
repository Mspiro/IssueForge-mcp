"""Unit tests for MultiPatchAnalyzer patch selection."""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.multi_patch_analyzer import MultiPatchAnalyzer


def _patch(patch_id, file_count=1):
    return {
        "patch_id": patch_id,
        "numeric_id": int(patch_id) if patch_id.isdigit() else 0,
        "file_count": file_count,
        "modified_files": ["core/a.php"] * file_count,
        "modified_functions": [],
        "filename": f"{patch_id}.patch",
    }


class TestSelectBestPatch:
    def test_returns_highest_id(self):
        patches = [_patch("100"), _patch("200"), _patch("50")]
        best = MultiPatchAnalyzer.select_best_patch(patches)
        assert best["patch_id"] == "200"

    def test_ignores_file_count(self):
        # Even though patch 50 has more files, patch 200 should win (more recent)
        patches = [_patch("50", file_count=10), _patch("200", file_count=1)]
        best = MultiPatchAnalyzer.select_best_patch(patches)
        assert best["patch_id"] == "200"

    def test_single_patch_returned(self):
        patches = [_patch("999")]
        assert MultiPatchAnalyzer.select_best_patch(patches)["patch_id"] == "999"

    def test_empty_returns_empty_dict(self):
        result = MultiPatchAnalyzer.select_best_patch([])
        assert result["modified_files"] == []
        assert result["filename"] is None

    def test_non_numeric_ids_handled(self):
        # Non-digit IDs get numeric_id=0, so a real numeric ID always wins
        patches = [_patch("abc"), _patch("500")]
        best = MultiPatchAnalyzer.select_best_patch(patches)
        assert best["patch_id"] == "500"
