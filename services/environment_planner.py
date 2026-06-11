from typing import Dict, List

from services.module_requirement_detector import ModuleRequirementDetector
from services.theme_requirement_detector import ThemeRequirementDetector
from services.version_resolver import VersionResolver


class EnvironmentPlanner:
    """
    Builds a reproducible Drupal environment plan
    based on issue metadata + detected code context.
    """

    @staticmethod
    def plan(
        metadata: Dict,
        modified_files: List[str] = None,
        valid_patch_ids: List[str] = None,
    ) -> Dict:
        """
        Generate environment setup instructions required
        to reproduce a Drupal issue locally.
        """

        modified_files = modified_files or []

        # Resolve correct branch + PHP version + project type
        version_info = VersionResolver.resolve(metadata)

        component = metadata.get("component", "")

        # Detect required modules
        required_modules = ModuleRequirementDetector.detect(
            metadata
        )

        # Detect required themes
        required_themes = ThemeRequirementDetector.detect(
            metadata,
            modified_files
        )

        # Detect patch availability
        patch_ids = (
            valid_patch_ids
            if valid_patch_ids is not None
            else metadata.get("patch_file_ids", [])
        )
        latest_patch_id = patch_ids[-1] if patch_ids else None

        contrib_modules = [
            m for m in required_modules
            if ModuleRequirementDetector.is_contrib(m)
        ]

        contrib_themes = [
            t for t in required_themes
            if ThemeRequirementDetector.is_contrib(t)
        ]

        return {
            "repository": "https://git.drupalcode.org/project/drupal.git",
            "checkout_ref": version_info["checkout_ref"],
            "component": component,
            "install_profile": "standard",
            "project_type": version_info["project_type"],
            "required_modules": required_modules,
            "required_themes": required_themes,
            "contrib_modules": contrib_modules,
            "contrib_themes": contrib_themes,
            "php_version": version_info["php_version"],
            "patch_available": bool(latest_patch_id),
            "latest_patch_id": latest_patch_id,
        }