from typing import Dict, List

from services.module_requirement_detector import ModuleRequirementDetector
from services.theme_requirement_detector import ThemeRequirementDetector
from services.version_resolver import VersionResolver
from services.distribution_registry import KNOWN_DISTRIBUTIONS


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

        project_name = metadata.get("project_name", "drupal")
        is_distribution = project_name in KNOWN_DISTRIBUTIONS
        is_contrib = (project_name != "drupal") and not is_distribution

        if is_contrib and project_name not in required_modules:
            required_modules.append(project_name)

        contrib_modules = [
            m for m in required_modules
            if ModuleRequirementDetector.is_contrib(m)
        ]

        contrib_themes = [
            t for t in required_themes
            if ThemeRequirementDetector.is_contrib(t)
        ]

        repository = (
            f"https://git.drupalcode.org/project/{project_name}.git"
            if is_distribution
            else "https://git.drupalcode.org/project/drupal.git"
        )
        # Distributions install via their own installer (e.g. Drupal CMS's
        # `drush site:install --yes`, no profile argument) — "standard" is
        # core's install profile and doesn't apply here.
        install_profile = None if is_distribution else "standard"

        plan = {
            "repository": repository,
            "checkout_ref": version_info["checkout_ref"],
            "component": component,
            "install_profile": install_profile,
            "project_type": version_info["project_type"],
            "required_modules": required_modules,
            "required_themes": required_themes,
            "contrib_modules": contrib_modules,
            "contrib_themes": contrib_themes,
            "php_version": version_info["php_version"],
            "patch_available": bool(latest_patch_id),
            "latest_patch_id": latest_patch_id,
            "is_contrib": is_contrib,
            "is_distribution": is_distribution,
            "project_name": project_name,
            "contrib_branch": version_info.get("contrib_branch") if is_contrib else None,
        }
        if is_distribution:
            plan["distribution_name"] = project_name
        return plan