from typing import Dict


class VersionResolver:
    """
    Resolves Drupal issue target version into
    git checkout ref + DDEV project type + PHP version.
    """

    VERSION_MAP = {
        "11": ("drupal11", "8.2"),
        "10": ("drupal10", "8.1"),
        "9": ("drupal9", "8.0"),
    }

    @staticmethod
    def normalize_branch(version: str) -> str:
        """
        Convert Drupal issue version into usable git branch.
        """

        if not version:
            return "11.x"

        version = version.lower().strip()

        if version == "main":
            return "11.x"

        if version.endswith("-dev"):
            return version.replace("-dev", "")

        return version

    @staticmethod
    def detect_major(version: str) -> str:
        """
        Extract major version number from branch.
        """

        if not version:
            return "11"

        return version.split(".")[0]

    @staticmethod
    def resolve(metadata: Dict) -> Dict:
        """
        Resolve environment configuration from issue metadata.
        """

        raw_version = metadata.get("version", "main")

        checkout_ref = VersionResolver.normalize_branch(
            raw_version
        )

        major = VersionResolver.detect_major(checkout_ref)

        project_type, php_version = VersionResolver.VERSION_MAP.get(
            major,
            ("drupal11", "8.2")
        )

        return {
            "checkout_ref": checkout_ref,
            "project_type": project_type,
            "php_version": php_version,
        }