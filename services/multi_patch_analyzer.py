from typing import List, Dict

from services.drupal_patch_client import DrupalPatchClient
from services.patch_analyzer import PatchAnalyzer


class MultiPatchAnalyzer:
    """
    Analyze multiple patches and select the best candidate.

    Selection strategy (in priority order):
    1. Most recent patch that applies cleanly (highest numeric patch ID).
    2. If no clean-apply check is possible, fall back to the most recent ID.

    The old heuristic (most files changed) is a poor proxy for patch quality —
    a large noisy patch is worse than a small targeted one.
    """

    def __init__(self):
        self.patch_client = DrupalPatchClient()

    def analyze_all_patches(self, patch_ids: List[str]) -> List[Dict]:
        results = []
        for patch_id in patch_ids:
            patch_path = f"temp_patch_{patch_id}.diff"
            try:
                _, filename = self.patch_client.download_patch(patch_id, patch_path)

                if not filename or not filename.lower().endswith((".patch", ".diff")):
                    continue

                analysis = PatchAnalyzer.analyze_patch_file(patch_path)
                if analysis["file_count"] == 0:
                    continue

                analysis["patch_id"] = patch_id
                analysis["filename"] = filename
                # Numeric ID as recency proxy — higher ID = uploaded later.
                analysis["numeric_id"] = int(patch_id) if patch_id.isdigit() else 0

                results.append(analysis)

            except Exception:
                continue

        return results

    @staticmethod
    def select_best_patch(patch_results: List[Dict]) -> Dict:
        """
        Return the most recently uploaded patch (highest numeric ID).

        Rationale: Drupal.org file IDs are monotonically increasing.  The
        latest patch is almost always the most up-to-date candidate.  A
        clean-apply check is done later in the apply_patch script; here we
        just pick the best candidate without requiring an environment.
        """
        if not patch_results:
            return {
                "modified_files": [],
                "modified_functions": [],
                "filename": None,
            }

        return max(patch_results, key=lambda x: x.get("numeric_id", 0))
