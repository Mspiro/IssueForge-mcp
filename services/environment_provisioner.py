import logging
import os
import shutil
import subprocess
from typing import Dict

logger = logging.getLogger("IssueForge.EnvironmentProvisioner")


class EnvironmentProvisioner:
    """
    Automates OS-level workspace creation and DDEV environment provisioning.
    """

    @staticmethod
    def run_command(args: list, cwd: str = None) -> bool:
        """
        Runs a shell command and logs output in real-time.
        """
        logger.info(f"Running: {' '.join(args)} in {cwd or '.'}")
        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            # Print output in real-time
            for line in process.stdout:
                print(line, end="")

            process.wait()
            if process.returncode != 0:
                logger.error(
                    f"Command failed with exit code {process.returncode}"
                )
                return False
            return True
        except Exception as e:
            logger.error(f"Error running command: {e}")
            return False

    @staticmethod
    def provision(issue_id: str, env_plan: Dict) -> Dict:
        """
        Main entry point for provisioning the environment.
        """
        # Validate tools
        for tool in ["git", "ddev", "docker"]:
            if shutil.which(tool) is None:
                raise Exception(
                    f"Required system tool '{tool}' is not installed."
                )

        # Determine workspace directory paths
        base_dir = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        envs_dir = os.path.join(base_dir, "environments")
        env_name = f"env-{issue_id}"
        env_path = os.path.join(envs_dir, f"env_{issue_id}")

        os.makedirs(envs_dir, exist_ok=True)

        # 1. Cleanup old environment if exists
        if os.path.exists(env_path):
            print(f"Cleaning up existing environment in {env_path}...")
            # Try to stop and delete DDEV container first
            EnvironmentProvisioner.run_command(
                ["ddev", "stop", "--omit-snapshot", "--unlist", env_name],
                cwd=base_dir,
            )
            try:
                shutil.rmtree(env_path)
            except Exception as e:
                logger.warning(
                    f"Failed to remove directory {env_path}: {e}"
                )

        # 2. Clone Drupal
        repo = env_plan.get(
            "repository", "https://git.drupalcode.org/project/drupal.git"
        )
        checkout_ref = env_plan.get("checkout_ref", "11.x")
        print(f"Cloning Drupal ({checkout_ref}) into {env_path}...")

        clone_ok = EnvironmentProvisioner.run_command([
            "git",
            "clone",
            "--branch",
            checkout_ref,
            "--depth",
            "1",
            repo,
            env_path,
        ])
        if not clone_ok:
            raise Exception("Failed to clone Drupal repository.")

        # Clone Contrib Module if applicable
        is_contrib = env_plan.get("is_contrib", False)
        project_name = env_plan.get("project_name", "drupal")
        contrib_branch = env_plan.get("contrib_branch")

        if is_contrib and project_name != "drupal":
            contrib_dir = os.path.join(env_path, "modules", "contrib")
            os.makedirs(contrib_dir, exist_ok=True)
            module_dir = os.path.join(contrib_dir, project_name)
            contrib_repo = f"https://git.drupalcode.org/project/{project_name}.git"
            print(f"Cloning Contrib Module {project_name} ({contrib_branch}) into {module_dir}...")

            module_clone_ok = EnvironmentProvisioner.run_command([
                "git",
                "clone",
                "--branch",
                contrib_branch,
                "--depth",
                "1",
                contrib_repo,
                module_dir,
            ])
            if not module_clone_ok:
                raise Exception(f"Failed to clone contrib module {project_name}.")

        # 3. Configure DDEV
        project_type = env_plan.get("project_type", "drupal11")
        print("Configuring DDEV...")
        config_ok = EnvironmentProvisioner.run_command([
            "ddev",
            "config",
            f"--project-type={project_type}",
            "--docroot=",
            f"--project-name={env_name}",
        ], cwd=env_path)
        if not config_ok:
            raise Exception("Failed to configure DDEV.")

        # 4. Start DDEV
        print("Starting DDEV...")
        start_ok = EnvironmentProvisioner.run_command(
            ["ddev", "start"], cwd=env_path
        )
        if not start_ok:
            raise Exception("Failed to start DDEV.")

        # 5. Composer Install
        print("Installing Composer dependencies...")
        composer_ok = EnvironmentProvisioner.run_command(
            ["ddev", "composer", "install"], cwd=env_path
        )
        if not composer_ok:
            raise Exception("Failed to run composer install.")

        # Require Drush for Drupal 8+ core installations
        is_drupal7 = (
            project_type == "drupal7" or checkout_ref.startswith("7")
        )
        if not is_drupal7:
            print("Installing Drush...")
            drush_ok = EnvironmentProvisioner.run_command(
                ["ddev", "composer", "require", "drush/drush", "--dev", "-W"],
                cwd=env_path,
            )
            if not drush_ok:
                raise Exception("Failed to install Drush.")

        # 6. Drush Site Install
        install_profile = env_plan.get("install_profile", "standard")
        print(f"Installing Drupal site (profile: {install_profile})...")
        si_ok = EnvironmentProvisioner.run_command(
            ["ddev", "drush", "si", install_profile, "-y"], cwd=env_path
        )
        if not si_ok:
            raise Exception("Failed to install Drupal site.")

        is_drupal7 = (
            project_type == "drupal7" or checkout_ref.startswith("7")
        )

        # 7. Download Contrib Modules
        contrib_modules = env_plan.get("contrib_modules", [])
        is_contrib = env_plan.get("is_contrib", False)
        project_name = env_plan.get("project_name", "drupal")
        if is_contrib:
            contrib_modules = [m for m in contrib_modules if m != project_name]

        if contrib_modules:
            print(f"Downloading contrib modules: {contrib_modules}...")
            if is_drupal7:
                dl_ok = EnvironmentProvisioner.run_command(
                    ["ddev", "drush", "dl"] + contrib_modules + ["-y"],
                    cwd=env_path,
                )
            else:
                packages = [f"drupal/{m}" for m in contrib_modules]
                dl_ok = EnvironmentProvisioner.run_command(
                    ["ddev", "composer", "require"] + packages + ["-W"],
                    cwd=env_path,
                )
            if not dl_ok:
                raise Exception("Failed to download contrib modules.")

        # 8. Download Contrib Themes
        contrib_themes = env_plan.get("contrib_themes", [])
        if contrib_themes:
            print(f"Downloading contrib themes: {contrib_themes}...")
            if is_drupal7:
                dl_ok = EnvironmentProvisioner.run_command(
                    ["ddev", "drush", "dl"] + contrib_themes + ["-y"],
                    cwd=env_path,
                )
            else:
                packages = [f"drupal/{t}" for t in contrib_themes]
                dl_ok = EnvironmentProvisioner.run_command(
                    ["ddev", "composer", "require"] + packages + ["-W"],
                    cwd=env_path,
                )
            if not dl_ok:
                raise Exception("Failed to download contrib themes.")

        # 9. Enable Modules
        required_modules = env_plan.get("required_modules", [])
        if required_modules:
            print(f"Enabling modules: {required_modules}...")
            en_ok = EnvironmentProvisioner.run_command(
                ["ddev", "drush", "en"] + required_modules + ["-y"],
                cwd=env_path,
            )
            if not en_ok:
                raise Exception("Failed to enable modules.")

        # 10. Enable Themes
        required_themes = env_plan.get("required_themes", [])
        if required_themes:
            print(f"Enabling themes: {required_themes}...")
            theme_enable_ok = EnvironmentProvisioner.run_command(
                ["ddev", "drush", "theme:enable"] + required_themes + ["-y"],
                cwd=env_path,
            )
            if not theme_enable_ok:
                raise Exception("Failed to enable themes.")

            # Set first theme as default
            print(f"Setting default theme to {required_themes[0]}...")
            theme_set_ok = EnvironmentProvisioner.run_command(
                [
                    "ddev",
                    "drush",
                    "config:set",
                    "system.theme",
                    "default",
                    required_themes[0],
                    "-y",
                ],
                cwd=env_path,
            )
            if not theme_set_ok:
                print("Warning: Failed to set default theme.")

        # Retrieve DDEV details
        site_url = f"https://{env_name}.ddev.site"
        print(
            f"\nEnvironment successfully created! Access url: {site_url}\n"
        )

        return {
            "success": True,
            "env_name": env_name,
            "env_path": env_path,
            "site_url": site_url,
        }
