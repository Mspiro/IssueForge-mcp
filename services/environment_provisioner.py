import logging
import os
import shutil
import subprocess
from typing import Dict

from config import (
    ENVIRONMENTS_DIR,
    PROVISIONER_COMMAND_TIMEOUT,
    PROVISIONER_REUSE_EXISTING,
    PROVISIONER_CLONE_DEPTH,
    GIT_USER_NAME,
    GIT_USER_EMAIL,
)

logger = logging.getLogger("IssueForge.EnvironmentProvisioner")


class EnvironmentProvisioner:
    """
    Automates OS-level workspace creation and DDEV environment provisioning.

    Key behaviours:
    - Reuses an existing, running environment when PROVISIONER_REUSE_EXISTING=true
      (default) and the checkout_ref matches — avoids minutes of unnecessary cloning.
    - Times out each command individually (PROVISIONER_COMMAND_TIMEOUT seconds).
    - Cleans up the DDEV project and directory on any unexpected failure so a
      subsequent run starts from a clean state.
    """

    @staticmethod
    def run_command(args: list, cwd: str = None, timeout: int = None) -> bool:
        timeout = timeout or PROVISIONER_COMMAND_TIMEOUT
        logger.info("Running: %s (cwd=%s, timeout=%ds)", " ".join(args), cwd or ".", timeout)
        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            try:
                for line in process.stdout:
                    print(line, end="")
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                logger.error("Command timed out after %ds: %s", timeout, " ".join(args))
                return False

            if process.returncode != 0:
                logger.error("Command failed (exit %d): %s", process.returncode, " ".join(args))
                return False
            return True
        except Exception as e:
            logger.error("Error running command %s: %s", " ".join(args), e)
            return False

    @staticmethod
    def _is_env_running(env_name: str) -> bool:
        """Return True if DDEV reports the named project as running."""
        try:
            result = subprocess.run(
                ["ddev", "describe", env_name, "--json-output"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _checkout_ref_matches(env_path: str, expected_ref: str) -> bool:
        """Return True if the cloned repo's checked-out branch matches expected_ref."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=env_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            current = result.stdout.strip()
            # Accept both exact match and HEAD (detached for tags/commits)
            return current == expected_ref or current == "HEAD"
        except Exception:
            return False

    @staticmethod
    def _cleanup(env_name: str, env_path: str):
        """Stop DDEV and remove the directory — called on failure."""
        logger.warning("Cleaning up failed environment: %s", env_name)
        try:
            subprocess.run(
                ["ddev", "stop", "--omit-snapshot", "--unlist", env_name],
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass
        if os.path.exists(env_path):
            try:
                shutil.rmtree(env_path)
            except Exception as e:
                logger.warning("Could not remove %s: %s", env_path, e)

    @staticmethod
    def _filter_existing_modules(modules: list) -> list:
        """
        Check each module against the drupal.org API and drop any that
        don't exist as real project_module nodes.  Prevents composer require
        from failing on names scraped from issue text that aren't real packages.
        """
        import requests
        verified = []
        for name in modules:
            try:
                resp = requests.get(
                    "https://www.drupal.org/api-d7/node.json",
                    params={"type": "project_module", "field_project_machine_name": name},
                    timeout=8,
                )
                exists = bool(resp.status_code == 200 and resp.json().get("list"))
            except Exception:
                exists = True  # network error — keep it and let composer decide
            if exists:
                verified.append(name)
            else:
                print(f"  [Skip] '{name}' is not a real drupal.org module — skipping.")
        return verified

    @staticmethod
    def provision(issue_id: str, env_plan: Dict) -> Dict:
        for tool in ["git", "ddev", "docker"]:
            if shutil.which(tool) is None:
                raise EnvironmentError(f"Required tool '{tool}' is not installed.")

        env_name = f"env-{issue_id}"
        env_path = os.path.join(ENVIRONMENTS_DIR, f"env_{issue_id}")
        os.makedirs(ENVIRONMENTS_DIR, exist_ok=True)

        checkout_ref = env_plan.get("checkout_ref", "11.x")

        # ------------------------------------------------------------------
        # Environment reuse: skip full provisioning when the environment is
        # already running and on the correct branch.
        # ------------------------------------------------------------------
        if (
            PROVISIONER_REUSE_EXISTING
            and os.path.exists(env_path)
            and EnvironmentProvisioner._is_env_running(env_name)
            and EnvironmentProvisioner._checkout_ref_matches(env_path, checkout_ref)
        ):
            site_url = f"https://{env_name}.ddev.site"
            logger.info("Reusing existing environment %s at %s", env_name, site_url)
            print(f"[Reuse] Environment {env_name} already running — skipping provisioning.")
            return {
                "success": True,
                "env_name": env_name,
                "env_path": env_path,
                "site_url": site_url,
                "reused": True,
            }

        # ------------------------------------------------------------------
        # Full provisioning
        # ------------------------------------------------------------------
        git_name = env_plan.get("git_name", GIT_USER_NAME) or "IssueForge User"
        git_email = env_plan.get("git_email", GIT_USER_EMAIL) or "issueforge@example.com"

        try:
            return EnvironmentProvisioner._provision_full(
                issue_id, env_name, env_path, env_plan, checkout_ref,
                git_name=git_name, git_email=git_email,
            )
        except Exception as exc:
            EnvironmentProvisioner._cleanup(env_name, env_path)
            raise

    @staticmethod
    def _provision_full(
        issue_id: str,
        env_name: str,
        env_path: str,
        env_plan: Dict,
        checkout_ref: str,
        git_name: str = "IssueForge User",
        git_email: str = "issueforge@example.com",
    ) -> Dict:
        # 1. Stop and remove any pre-existing conflicting project
        EnvironmentProvisioner.run_command(
            ["ddev", "stop", "--omit-snapshot", "--unlist", env_name],
            cwd=os.path.dirname(env_path),
            timeout=30,
        )
        if os.path.exists(env_path):
            logger.info("Removing existing directory %s", env_path)
            shutil.rmtree(env_path, ignore_errors=True)

        # 2. Clone Drupal
        repo = env_plan.get("repository", "https://git.drupalcode.org/project/drupal.git")
        clone_depth = str(PROVISIONER_CLONE_DEPTH)
        print(f"Cloning Drupal ({checkout_ref}, depth={clone_depth}) into {env_path}...")
        if not EnvironmentProvisioner.run_command(
            ["git", "clone", "--branch", checkout_ref, "--depth", clone_depth, repo, env_path],
            timeout=300,
        ):
            raise RuntimeError("Failed to clone Drupal repository.")

        # Clone contrib module if applicable
        is_contrib = env_plan.get("is_contrib", False)
        project_name = env_plan.get("project_name", "drupal")
        contrib_branch = env_plan.get("contrib_branch")
        if is_contrib and project_name != "drupal":
            contrib_dir = os.path.join(env_path, "modules", "contrib")
            os.makedirs(contrib_dir, exist_ok=True)
            contrib_repo = f"https://git.drupalcode.org/project/{project_name}.git"
            print(f"Cloning {project_name} ({contrib_branch}) into {contrib_dir}/{project_name}...")
            if not EnvironmentProvisioner.run_command(
                ["git", "clone", "--branch", contrib_branch, "--depth", "1",
                 contrib_repo, os.path.join(contrib_dir, project_name)],
                timeout=120,
            ):
                raise RuntimeError(f"Failed to clone contrib module {project_name}.")

        # 3. Configure DDEV
        project_type = env_plan.get("project_type", "drupal11")
        print("Configuring DDEV...")
        if not EnvironmentProvisioner.run_command(
            ["ddev", "config", f"--project-type={project_type}",
             "--docroot=", f"--project-name={env_name}"],
            cwd=env_path,
            timeout=30,
        ):
            raise RuntimeError("Failed to configure DDEV.")

        # 4. Start DDEV
        print("Starting DDEV...")
        if not EnvironmentProvisioner.run_command(
            ["ddev", "start"], cwd=env_path, timeout=120
        ):
            raise RuntimeError("Failed to start DDEV.")

        # 5. Composer install
        print("Installing Composer dependencies...")
        if not EnvironmentProvisioner.run_command(
            ["ddev", "composer", "install"], cwd=env_path, timeout=PROVISIONER_COMMAND_TIMEOUT
        ):
            raise RuntimeError("Failed to run composer install.")

        is_drupal7 = project_type == "drupal7" or checkout_ref.startswith("7")

        # 6. Install Drush (Drupal 8+)
        if not is_drupal7:
            print("Installing Drush...")
            drush_ok = EnvironmentProvisioner.run_command(
                ["ddev", "composer", "require", "drush/drush", "--dev", "--no-update"],
                cwd=env_path, timeout=60,
            )
            if drush_ok:
                drush_ok = EnvironmentProvisioner.run_command(
                    ["ddev", "composer", "update", "drush/drush"],
                    cwd=env_path, timeout=180,
                )
            if not drush_ok:
                raise RuntimeError("Failed to install Drush.")

        # 7. Drush site install
        install_profile = env_plan.get("install_profile", "standard")
        print(f"Installing Drupal site (profile: {install_profile})...")
        if not EnvironmentProvisioner.run_command(
            ["ddev", "drush", "si", install_profile, "-y"],
            cwd=env_path, timeout=PROVISIONER_COMMAND_TIMEOUT,
        ):
            raise RuntimeError("Failed to install Drupal site.")

        # 8. Download and enable contrib modules
        contrib_modules = env_plan.get("contrib_modules", [])
        if is_contrib and project_name in contrib_modules:
            contrib_modules = [m for m in contrib_modules if m != project_name]
        if contrib_modules:
            contrib_modules = EnvironmentProvisioner._filter_existing_modules(contrib_modules)
        if contrib_modules:
            print(f"Downloading contrib modules: {contrib_modules}...")
            packages = [f"drupal/{m}" for m in contrib_modules]
            dl_ok = EnvironmentProvisioner.run_command(
                ["ddev", "composer", "require"] + packages + ["--no-update"],
                cwd=env_path, timeout=120,
            )
            if dl_ok:
                dl_ok = EnvironmentProvisioner.run_command(
                    ["ddev", "composer", "update"] + packages,
                    cwd=env_path, timeout=PROVISIONER_COMMAND_TIMEOUT,
                )
            if not dl_ok:
                raise RuntimeError(f"Failed to download contrib modules: {contrib_modules}")

        # 9. Download contrib themes
        contrib_themes = env_plan.get("contrib_themes", [])
        if contrib_themes:
            print(f"Downloading contrib themes: {contrib_themes}...")
            packages = [f"drupal/{t}" for t in contrib_themes]
            dl_ok = EnvironmentProvisioner.run_command(
                ["ddev", "composer", "require"] + packages + ["--no-update"],
                cwd=env_path, timeout=120,
            )
            if dl_ok:
                dl_ok = EnvironmentProvisioner.run_command(
                    ["ddev", "composer", "update"] + packages,
                    cwd=env_path, timeout=PROVISIONER_COMMAND_TIMEOUT,
                )
            if not dl_ok:
                raise RuntimeError(f"Failed to download contrib themes: {contrib_themes}")

        # 10. Enable modules
        required_modules = env_plan.get("required_modules", [])
        if required_modules:
            print(f"Enabling modules: {required_modules}...")
            if not EnvironmentProvisioner.run_command(
                ["ddev", "drush", "en"] + required_modules + ["-y"],
                cwd=env_path, timeout=120,
            ):
                raise RuntimeError(f"Failed to enable modules: {required_modules}")

        # 11. Enable and set default theme
        required_themes = env_plan.get("required_themes", [])
        if required_themes:
            print(f"Enabling themes: {required_themes}...")
            if not EnvironmentProvisioner.run_command(
                ["ddev", "drush", "theme:enable"] + required_themes + ["-y"],
                cwd=env_path, timeout=60,
            ):
                raise RuntimeError(f"Failed to enable themes: {required_themes}")
            EnvironmentProvisioner.run_command(
                ["ddev", "drush", "config:set", "system.theme",
                 "default", required_themes[0], "-y"],
                cwd=env_path, timeout=30,
            )

        # 12. Set up git workspace: identity + working branch
        from services.git_workspace_manager import GitWorkspaceManager
        workspace = GitWorkspaceManager.setup_workspace(
            env_path, issue_id, git_name, git_email
        )
        if workspace.get("warnings"):
            for w in workspace["warnings"]:
                logger.warning(w)

        # 13. Add Drupal.org issue fork as the 'issue' remote and fetch
        #     existing branches if any contributor already pushed work.
        fork_info = GitWorkspaceManager.setup_issue_remote(
            env_path, project_name, issue_id
        )
        if fork_info.get("fetched") and fork_info.get("remote_branches"):
            print(
                f"[Fork] Existing branches on issue fork: "
                f"{', '.join(fork_info['remote_branches'])}"
            )
        else:
            # Fork doesn't exist yet — wait for user to click Get Push Access
            GitWorkspaceManager.wait_for_fork(
                env_path, project_name, issue_id
            )

        site_url = f"https://{env_name}.ddev.site"
        print(f"\nEnvironment successfully created! Access url: {site_url}")
        print(f"Working branch: {workspace['branch']}")
        print(f"Push command:   {GitWorkspaceManager.get_push_command(env_path)}\n")

        return {
            "success": True,
            "env_name": env_name,
            "env_path": env_path,
            "site_url": site_url,
            "reused": False,
            "branch": workspace["branch"],
        }
