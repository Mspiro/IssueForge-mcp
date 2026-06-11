import re
from typing import List, Dict


class PatchBranchDetector:
    """
    Detect target Drupal branch/version for a given patch based on:
    - original patch filename
    - modified file paths inside diff
    """

    VERSION_PATTERNS = [
        # Look for explicit branch identifiers like 11.x, 10.3.x, 8.x-1.x, etc.
        r"[-_](11\.x|10\.[0-9]+\.x|10\.x|9\.[0-9]+\.x|9\.x|8\.x|7\.x)[-_.]",
        r"[-_](11|10|9|8|7)\.x[-_.]",
    ]

    @staticmethod
    def detect_branch_from_filename(filename: str) -> str:
        """
        Extract branch reference from patch filename if present.
        """
        if not filename:
            return None

        filename_lower = filename.lower()
        for pattern in PatchBranchDetector.VERSION_PATTERNS:
            match = re.search(pattern, filename_lower)
            if match:
                return match.group(1)

        return None

    @staticmethod
    def detect_major_from_paths(modified_files: List[str]) -> str:
        """
        Detect if patch is Drupal 7 or Drupal 8+ based on paths.
        Drupal 8+ has core/ directory structure.
        """
        if not modified_files:
            return None

        has_core = any(path.startswith("core/") for path in modified_files)

        if has_core:
            return "8+"

        return "7"

    @staticmethod
    def check_compatibility(
        patch_filename: str,
        modified_files: List[str],
        checkout_ref: str
    ) -> Dict:
        """
        Check if the patch is compatible with the target checkout branch/version.
        """
        detected_branch = PatchBranchDetector.detect_branch_from_filename(
            patch_filename
        )
        detected_major_paths = PatchBranchDetector.detect_major_from_paths(
            modified_files
        )

        warning = None
        is_compatible = True

        # Rule 1: Drupal 7 vs Drupal 8+ mismatch
        if checkout_ref.startswith("7.") or checkout_ref == "7":
            if detected_major_paths == "8+":
                is_compatible = False
                warning = (
                    f"Patch targets Drupal 8+ (uses 'core/' path prefix), "
                    f"but issue checkout ref is Drupal 7 ({checkout_ref})."
                )
        else:
            # Checkout ref is 8, 9, 10, 11
            # Note: only check core/ prefix mismatch if it's Drupal core project.
            # If the path does not have 'core/' and it's core, it's incompatible.
            # But let's check if modified_files has any core prefix.
            # Usually, core patches modify files in core/ structure.
            if detected_major_paths == "7" and any(
                p.endswith(".module") or p.endswith(".php") or p.endswith(".install")
                for p in modified_files
            ):
                # We should be careful about contrib modules which might not have 'core/' prefix.
                # However, for a generic comparison, warning is good.
                pass

        # Rule 2: Explicit branch mismatch (e.g., patch targets 10.3.x but we checked out 11.x)
        if is_compatible and detected_branch:
            clean_checkout = checkout_ref.replace(".x", "")
            clean_detected = detected_branch.replace(".x", "")

            # If detected version does not match checkout branch prefix
            if not (
                clean_checkout.startswith(clean_detected)
                or clean_detected.startswith(clean_checkout)
            ):
                is_compatible = False
                warning = (
                    f"Patch target branch is '{detected_branch}', "
                    f"but issue checkout ref is '{checkout_ref}'."
                )

        return {
            "detected_branch": detected_branch,
            "detected_major_paths": detected_major_paths,
            "is_compatible": is_compatible,
            "warning": warning,
        }
