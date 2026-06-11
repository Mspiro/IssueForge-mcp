import logging
import os
import subprocess
from typing import Dict
from services.drupal_patch_client import DrupalPatchClient

logger = logging.getLogger("IssueForge.PatchApplier")


class PatchApplier:
    """
    Handles patch dry-run checks and patch application within the environment.
    """

    @staticmethod
    def _get_patch_path(env_path: str, patch_id: str) -> str:
        return os.path.join(env_path, f"{patch_id}.patch")

    @staticmethod
    def download_if_missing(env_path: str, patch_id: str) -> str:
        patch_path = PatchApplier._get_patch_path(env_path, patch_id)
        if not os.path.exists(patch_path):
            print(f"Downloading patch {patch_id}...")
            client = DrupalPatchClient()
            client.download_patch(patch_id, patch_path)
        return patch_path

    @staticmethod
    def check_patch(env_path: str, patch_id: str) -> Dict:
        """
        Runs git apply --check to verify if the patch applies cleanly.
        Tries fallback flags if the default check fails.
        """
        try:
            patch_path = PatchApplier.download_if_missing(env_path, patch_id)
            patch_filename = os.path.basename(patch_path)

            print(f"Checking patch compatibility for {patch_filename}...")

            # Strategies to try: (args list, display name)
            strategies = [
                ([], "default"),
                (["--ignore-whitespace"], "ignore-whitespace"),
                (["--3way"], "3way"),
                (["--ignore-whitespace", "--3way"], "ignore-whitespace + 3way")
            ]

            for args, name in strategies:
                cmd = ["git", "apply"] + args + ["--check", patch_filename]
                process = subprocess.run(
                    cmd,
                    cwd=env_path,
                    capture_output=True,
                    text=True,
                )
                if process.returncode == 0:
                    print(f"Patch checks passed using {name} strategy!")
                    return {
                        "clean": True,
                        "strategy_args": args,
                        "message": f"Clean apply using {name} strategy.",
                        "patch_path": patch_path,
                    }

            # If all failed, return details from the default check
            process = subprocess.run(
                ["git", "apply", "--check", "--verbose", patch_filename],
                cwd=env_path,
                capture_output=True,
                text=True,
            )
            message = process.stdout + process.stderr
            print(f"Patch checks failed for all strategies:\n{message}")
            return {
                "clean": False,
                "strategy_args": [],
                "message": message.strip(),
                "patch_path": patch_path,
            }
        except Exception as e:
            logger.error(f"Error checking patch {patch_id}: {e}")
            return {
                "clean": False,
                "strategy_args": [],
                "message": str(e),
                "patch_path": "",
            }

    @staticmethod
    def apply_patch(env_path: str, patch_id: str) -> Dict:
        """
        Applies the patch using the resolved clean strategy and rebuilds the Drupal cache.
        """
        try:
            patch_path = PatchApplier.download_if_missing(env_path, patch_id)
            patch_filename = os.path.basename(patch_path)

            # 1. Run check first to resolve clean strategy
            check_res = PatchApplier.check_patch(env_path, patch_id)
            if not check_res["clean"]:
                return {
                    "success": False,
                    "message": (
                        f"Patch cannot be applied cleanly:\n"
                        f"{check_res['message']}"
                    ),
                }

            strategy_args = check_res.get("strategy_args", [])

            # 2. Apply patch using successful strategy
            print(f"Applying patch {patch_filename} with args {strategy_args}...")
            cmd = ["git", "apply"] + strategy_args + [patch_filename]
            process = subprocess.run(
                cmd,
                cwd=env_path,
                capture_output=True,
                text=True,
            )

            if process.returncode != 0:
                error_msg = process.stdout + process.stderr
                return {
                    "success": False,
                    "message": f"Failed to apply patch:\n{error_msg}",
                }

            print("Patch applied successfully! Rebuilding Drupal cache...")
            # 3. Clear cache
            cr_process = subprocess.run(
                ["ddev", "drush", "cr"],
                cwd=env_path,
                capture_output=True,
                text=True,
            )

            cr_output = cr_process.stdout + cr_process.stderr
            print("Cache rebuilt successfully.")

            return {
                "success": True,
                "message": "Patch applied and cache rebuilt successfully.",
                "cr_output": cr_output.strip(),
            }
        except Exception as e:
            logger.error(f"Error applying patch {patch_id}: {e}")
            return {
                "success": False,
                "message": str(e),
            }
