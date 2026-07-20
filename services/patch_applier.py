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
    def _get_apply_cwd(env_path: str, patch_path: str) -> str:
        """
        Auto-detect the target repository directory within the environment.
        For Drupal core issues, this is the root env_path.
        For contrib module issues, this is the subdirectory of the contrib module.
        """
        if not os.path.exists(patch_path):
            return env_path

        first_file = None
        try:
            with open(patch_path, "r", errors="ignore") as f:
                for line in f:
                    if line.startswith("+++ b/"):
                        parts = line[6:].strip().split("\t")
                        first_file = parts[0].strip()
                        break
        except Exception:
            pass

        if first_file:
            contrib_base = os.path.join(env_path, "modules", "contrib")
            if os.path.exists(contrib_base):
                for item in os.listdir(contrib_base):
                    item_path = os.path.join(contrib_base, item)
                    if os.path.isdir(item_path):
                        if os.path.exists(os.path.join(item_path, first_file)):
                            print(f"Auto-detected target directory for patch: {item_path}")
                            return item_path
        return env_path

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
            apply_cwd = PatchApplier._get_apply_cwd(env_path, patch_path)

            # Strategies to try: (args list, display name)
            strategies = [
                ([], "default"),
                (["--ignore-whitespace"], "ignore-whitespace"),
                (["--3way"], "3way"),
                (["--ignore-whitespace", "--3way"], "ignore-whitespace + 3way")
            ]

            for args, name in strategies:
                cmd = ["git", "apply"] + args + ["--check", patch_path]
                process = subprocess.run(
                    cmd,
                    cwd=apply_cwd,
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
                ["git", "apply", "--check", "--verbose", patch_path],
                cwd=apply_cwd,
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
    def _is_already_applied(apply_cwd: str, patch_path: str) -> bool:
        """
        A patch that's already applied always fails a forward `git apply
        --check` (the "before" context no longer matches) — indistinguishable
        from a genuine conflict by that check alone. `git apply --check
        --reverse` succeeding means the tree already matches the patch's
        "after" state, which only happens when it's already applied; a
        genuinely conflicting patch fails both directions. Verified: forward
        check fails identically in both cases, reverse check only succeeds
        for the already-applied case.
        """
        for args in ([], ["--ignore-whitespace"]):
            check = subprocess.run(
                ["git", "apply", "--check", "--reverse"] + args + [patch_path],
                cwd=apply_cwd, capture_output=True, text=True,
            )
            if check.returncode == 0:
                return True
        return False

    @staticmethod
    def apply_patch_file(env_path: str, patch_path: str) -> Dict:
        """
        Apply a patch from a local file path (not a remote patch_id).
        Used by apply_mr.py which already has the diff on disk.
        """
        if not os.path.exists(patch_path):
            return {"success": False, "message": f"Patch file not found: {patch_path}"}

        patch_filename = os.path.basename(patch_path)
        apply_cwd = PatchApplier._get_apply_cwd(env_path, patch_path)

        strategies = [
            ([], "default"),
            (["--ignore-whitespace"], "ignore-whitespace"),
            (["--3way"], "3way"),
            (["--ignore-whitespace", "--3way"], "combined"),
        ]

        # Find clean strategy
        winning_args = None
        for args, name in strategies:
            check = subprocess.run(
                ["git", "apply"] + args + ["--check", patch_path],
                cwd=apply_cwd, capture_output=True, text=True,
            )
            if check.returncode == 0:
                winning_args = args
                break

        if winning_args is None:
            if PatchApplier._is_already_applied(apply_cwd, patch_path):
                return {
                    "success": True,
                    "already_applied": True,
                    "message": f"{patch_filename} is already applied — working tree already matches.",
                    "target_root": apply_cwd,
                }
            return {
                "success": False,
                "message": "Patch cannot be applied cleanly with any strategy.",
                "target_root": apply_cwd,
            }

        result = subprocess.run(
            ["git", "apply"] + winning_args + [patch_path],
            cwd=apply_cwd, capture_output=True, text=True,
        )
        if result.returncode != 0:
            return {
                "success": False,
                "message": result.stdout + result.stderr,
                "target_root": apply_cwd,
            }

        # Cache rebuild
        subprocess.run(["ddev", "drush", "cr"], cwd=env_path, capture_output=True, text=True)
        return {
            "success": True,
            "message": f"Applied {patch_filename} successfully.",
            # The repo the diff actually landed in — for contrib issues this
            # is modules/contrib/<name>, whose own git must be used for all
            # follow-up diff/commit/push operations.
            "target_root": apply_cwd,
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
            apply_cwd = PatchApplier._get_apply_cwd(env_path, patch_path)

            # 2. Apply patch using successful strategy
            print(f"Applying patch {patch_filename} with args {strategy_args}...")
            cmd = ["git", "apply"] + strategy_args + [patch_path]
            process = subprocess.run(
                cmd,
                cwd=apply_cwd,
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
