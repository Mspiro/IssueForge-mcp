from typing import List, Dict

from services.drupal_patch_client import DrupalPatchClient
from services.patch_analyzer import PatchAnalyzer


class MultiPatchAnalyzer:
    """
    Analyze multiple patches and select the best candidate patch.
    """

    def __init__(self):
        self.patch_client = DrupalPatchClient()

    def analyze_all_patches(self, patch_ids: List[str]) -> List[Dict]:

        results = []

        for patch_id in patch_ids:

            patch_path = f"temp_patch_{patch_id}.diff"

            try:
                _, filename = self.patch_client.download_patch(
                    patch_id,
                    patch_path
                )

                if not filename or not filename.lower().endswith((".patch", ".diff")):
                    continue

                analysis = PatchAnalyzer.analyze_patch_file(
                    patch_path
                )

                if analysis["file_count"] == 0:
                    continue

                analysis["patch_id"] = patch_id
                analysis["filename"] = filename

                results.append(analysis)

            except Exception:
                continue

        return results

    @staticmethod
    def select_best_patch(patch_results: List[Dict]) -> Dict:
        """
        Select best patch based on number of modified files.
        """

        if not patch_results:
            return {
                "modified_files": [],
                "modified_functions": [],
                "filename": None,
            }

        best_patch = max(
            patch_results,
            key=lambda x: x["file_count"]
        )

        return best_patch