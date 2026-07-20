import json
import logging
import os
import re
import shutil
import socket
import subprocess
from typing import Dict, Tuple

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
    def _apply_profile_recipe(env_path: str, install_profile: str) -> bool:
        """
        Apply core/recipes/<install_profile> if it exists in this checkout.

        Uses core/scripts/dr (current) or core/scripts/drupal (deprecated
        fallback for slightly older checkouts) to invoke `recipe <path>`.
        Non-fatal on failure: provisioning continues, but a warning is
        logged so the gap is visible rather than silently swallowed.
        """
        recipe_dir = os.path.join(env_path, "core", "recipes", install_profile)
        if not os.path.isdir(recipe_dir):
            return True

        dr_script = os.path.join(env_path, "core", "scripts", "dr")
        drupal_script = os.path.join(env_path, "core", "scripts", "drupal")
        if os.path.exists(dr_script):
            script = "core/scripts/dr"
        elif os.path.exists(drupal_script):
            script = "core/scripts/drupal"
        else:
            return True

        print(f"Applying '{install_profile}' recipe (default content types, etc.)...")
        recipe_ok = EnvironmentProvisioner.run_command(
            ["ddev", "exec", "php", script, "recipe", f"core/recipes/{install_profile}"],
            cwd=env_path, timeout=180,
        )
        if not recipe_ok:
            logger.warning(
                "Recipe application for '%s' failed — the site may be missing "
                "default content types (e.g. 'page'). Continuing provisioning.",
                install_profile,
            )
        return recipe_ok

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
    def _port_is_free(port: int) -> bool:
        """True if nothing is already listening on 127.0.0.1:<port>."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False

    @staticmethod
    def _find_free_port_pair(start: int = 33010, end: int = 33999) -> Tuple[int, int]:
        """Find two consecutive free TCP ports for DDEV's router ports."""
        port = start
        while port < end:
            if (
                EnvironmentProvisioner._port_is_free(port)
                and EnvironmentProvisioner._port_is_free(port + 1)
            ):
                return port, port + 1
            port += 2
        raise RuntimeError(f"No free port pair found in range {start}-{end}.")

    @staticmethod
    def _ddev_router_is_running() -> bool:
        """
        True if DDEV's shared router container is already up. It's one
        container reused across every running DDEV project on the machine —
        if it's already running, whatever it's bound to is DDEV's own
        legitimate state (serving other currently-running projects), not a
        conflict, and a new project just attaches to it. Checking port
        availability in that case would misread the router's own bind as a
        foreign-process conflict.
        """
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=^ddev-router$",
                 "--filter", "status=running", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=10,
            )
            return "ddev-router" in result.stdout
        except Exception:
            return False

    @staticmethod
    def _ensure_router_ports_free():
        """
        DDEV's router ports are global (shared by every DDEV project on this
        machine), not per-project, so a per-project `ddev config` can't fix a
        conflict here. A prior field session hit this exact failure twice:
        DDEV's own port-80 fallback (33000) was silently held by an
        unrelated host process (an IDE and its language server) — nothing to
        do with Docker or DDEV state — and `ddev poweroff`, the documented
        fix for stale DDEV state, did nothing, because the conflict wasn't
        DDEV's own. Verify the *currently configured* router ports are
        actually free before every `ddev start`, and remap to a confirmed-
        free pair if not, rather than trusting DDEV's own fallback selection.

        Only checks when the router isn't already running — see
        _ddev_router_is_running().
        """
        if EnvironmentProvisioner._ddev_router_is_running():
            return

        try:
            result = subprocess.run(
                ["ddev", "config", "global", "--json-output"],
                capture_output=True, text=True, timeout=15,
            )
            raw = json.loads(result.stdout).get("raw", {})
            http_port = int(raw.get("router-http-port", 80))
            https_port = int(raw.get("router-https-port", 443))
        except Exception as e:
            logger.warning("Could not read DDEV global router ports: %s", e)
            return

        if (
            EnvironmentProvisioner._port_is_free(http_port)
            and EnvironmentProvisioner._port_is_free(https_port)
        ):
            return

        print(
            f"[Provisioner] DDEV router port {http_port}/{https_port} is "
            f"already in use by something else on this machine — picking a "
            f"free pair instead."
        )
        try:
            new_http, new_https = EnvironmentProvisioner._find_free_port_pair()
        except RuntimeError as e:
            logger.warning("%s Provisioning will proceed with the conflicting ports.", e)
            return

        ok = EnvironmentProvisioner.run_command(
            ["ddev", "config", "global",
             f"--router-http-port={new_http}", f"--router-https-port={new_https}"],
            timeout=15,
        )
        if ok:
            print(f"[Provisioner] DDEV router ports set to {new_http}/{new_https}.")
        else:
            logger.warning(
                "Failed to reconfigure DDEV router ports — provisioning may "
                "still hit the port conflict."
            )

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
    def _detect_own_contrib_dependencies(module_path: str, project_name: str = "") -> list:
        """
        Detect the git-cloned contrib project's own module dependencies so
        they can be composer-required (the project itself bypasses Composer).

        Two sources, merged:
        1. composer.json "require" entries under the drupal/ namespace.
        2. info.yml `dependencies:` entries — the fallback for the many
           contrib modules that declare dependencies only in info.yml
           (entries look like "key:key", "drupal:views", or bare "token";
           the part before the colon is the drupal.org project name, and a
           "drupal:" prefix means a core module, never a contrib project).
        """
        import json
        from services.module_requirement_detector import ModuleRequirementDetector

        found = []

        composer_json_path = os.path.join(module_path, "composer.json")
        if os.path.isfile(composer_json_path):
            try:
                with open(composer_json_path) as f:
                    data = json.load(f)
                found.extend(
                    package.split("/", 1)[1]
                    for package in data.get("require", {})
                    if package.startswith("drupal/")
                )
            except Exception as e:
                logger.warning(
                    "Could not parse composer.json at %s: %s", composer_json_path, e
                )

        info_yml_path = os.path.join(module_path, f"{project_name}.info.yml")
        if project_name and os.path.isfile(info_yml_path):
            try:
                with open(info_yml_path) as f:
                    lines = f.read().splitlines()
                in_deps = False
                for line in lines:
                    if re.match(r"^dependencies:\s*$", line):
                        in_deps = True
                        continue
                    if in_deps:
                        item = re.match(r"^\s+-\s+['\"]?([\w:]+)['\"]?\s*$", line)
                        if not item:
                            in_deps = False  # end of the dependencies block
                            continue
                        dep_project = item.group(1).split(":", 1)[0]
                        if dep_project == "drupal":
                            continue  # core module namespace
                        if not ModuleRequirementDetector.is_contrib(dep_project):
                            continue
                        found.append(dep_project)
            except Exception as e:
                logger.warning(
                    "Could not parse info.yml at %s: %s", info_yml_path, e
                )

        deduped = list(dict.fromkeys(found))
        if project_name in deduped:
            deduped.remove(project_name)
        return deduped

    @staticmethod
    def _add_composer_replace(env_path: str, project_name: str) -> bool:
        """
        Mark the git-cloned contrib project as already-provided in the site's
        composer.json ("replace": {"drupal/<name>": "*"}).

        Without this, a later `composer require` of any package that depends
        on the project (e.g. drupal/sodium depending on drupal/encrypt)
        silently overwrites the git clone at modules/contrib/<name> with a
        tagged release — destroying the dev-branch checkout, the issue-fork
        remote, and any applied patch.
        """
        import json
        composer_json_path = os.path.join(env_path, "composer.json")
        try:
            with open(composer_json_path) as f:
                data = json.load(f)
            data.setdefault("replace", {})[f"drupal/{project_name}"] = "*"
            with open(composer_json_path, "w") as f:
                json.dump(data, f, indent=4)
                f.write("\n")
            return True
        except Exception as e:
            logger.warning(
                "Could not add composer replace entry for drupal/%s: %s",
                project_name, e,
            )
            return False

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

    # Total user-visible stages printed by _provision_full — keep in sync
    # with the _stage() calls below. Stage lines are greppable
    # ("[STAGE n/8] label — ~duration") so a caller running provisioning in
    # the background can poll the output file and relay live progress.
    TOTAL_STAGES = 8

    @staticmethod
    def _stage(n: int, label: str, eta: str = ""):
        suffix = f" — {eta}" if eta else ""
        print(
            f"\n[STAGE {n}/{EnvironmentProvisioner.TOTAL_STAGES}] {label}{suffix}",
            flush=True,
        )

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
        EnvironmentProvisioner._stage(1, f"Cloning Drupal core ({checkout_ref})", "~1 min")
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
        own_dependencies = []
        module_path = None
        if is_contrib and project_name != "drupal":
            EnvironmentProvisioner._stage(
                2, f"Cloning contrib module '{project_name}' + detecting its dependencies"
            )
            contrib_dir = os.path.join(env_path, "modules", "contrib")
            os.makedirs(contrib_dir, exist_ok=True)
            contrib_repo = f"https://git.drupalcode.org/project/{project_name}.git"
            module_path = os.path.join(contrib_dir, project_name)
            print(f"Cloning {project_name} ({contrib_branch}) into {contrib_dir}/{project_name}...")
            if not EnvironmentProvisioner.run_command(
                ["git", "clone", "--branch", contrib_branch, "--depth", "1",
                 contrib_repo, module_path],
                timeout=120,
            ):
                raise RuntimeError(f"Failed to clone contrib module {project_name}.")
            # The issue's own project is git-cloned directly (to preserve its
            # dev branch for patch application) rather than composer-required,
            # so Composer never processes its composer.json — any real
            # dependency it declares (e.g. Encrypt requiring Key) would
            # otherwise be silently missing, and `drush en` fails with
            # "is missing its dependency module ...".
            own_dependencies = EnvironmentProvisioner._detect_own_contrib_dependencies(
                module_path, project_name
            )
            # And protect the clone from Composer: without a "replace" entry,
            # requiring any package that depends on this project would
            # overwrite the git checkout with a tagged release.
            EnvironmentProvisioner._add_composer_replace(env_path, project_name)

        # 3. Configure DDEV
        if not (is_contrib and project_name != "drupal"):
            EnvironmentProvisioner._stage(2, "Contrib module setup (skipped — core issue)")
        project_type = env_plan.get("project_type", "drupal11")
        EnvironmentProvisioner._stage(3, "Configuring and starting DDEV", "~30s")
        print("Configuring DDEV...")
        if not EnvironmentProvisioner.run_command(
            ["ddev", "config", f"--project-type={project_type}",
             "--docroot=", f"--project-name={env_name}"],
            cwd=env_path,
            timeout=30,
        ):
            raise RuntimeError("Failed to configure DDEV.")

        EnvironmentProvisioner._ensure_router_ports_free()

        # Selenium/Chrome add-on, installed before the first `ddev start` so
        # the container comes up in that same start (no extra restart). Any
        # module whose tests are 100% FunctionalJavascript otherwise gets a
        # false "all tests fail: connection refused on port 4444" signal
        # from the regression checker, indistinguishable from a real
        # regression, since there's no WebDriver for Chrome to run against.
        print("Adding Selenium/Chrome add-on for browser-driven tests...")
        selenium_ok = EnvironmentProvisioner.run_command(
            ["ddev", "add-on", "get", "ddev/ddev-selenium-standalone-chrome"],
            cwd=env_path, timeout=120,
        )
        if not selenium_ok:
            logger.warning(
                "Could not install the Selenium/Chrome add-on — "
                "FunctionalJavascript tests will fail with a WebDriver "
                "connection error, not a real regression."
            )

        # 4. Start DDEV
        print("Starting DDEV...")
        if not EnvironmentProvisioner.run_command(
            ["ddev", "start"], cwd=env_path, timeout=120
        ):
            raise RuntimeError("Failed to start DDEV.")

        # 5. Composer install
        EnvironmentProvisioner._stage(4, "Installing Composer dependencies", "~1-2 min")
        print("Installing Composer dependencies...")
        if not EnvironmentProvisioner.run_command(
            ["ddev", "composer", "install"], cwd=env_path, timeout=PROVISIONER_COMMAND_TIMEOUT
        ):
            raise RuntimeError("Failed to run composer install.")

        is_drupal7 = project_type == "drupal7" or checkout_ref.startswith("7")

        # 6. Install Drush (Drupal 8+)
        EnvironmentProvisioner._stage(5, "Installing Drush", "~30s")
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
        EnvironmentProvisioner._stage(
            6, f"Installing Drupal site (profile: {install_profile}) + recipe", "~1-2 min"
        )
        print(f"Installing Drupal site (profile: {install_profile})...")
        if not EnvironmentProvisioner.run_command(
            ["ddev", "drush", "si", install_profile, "-y"],
            cwd=env_path, timeout=PROVISIONER_COMMAND_TIMEOUT,
        ):
            raise RuntimeError("Failed to install Drupal site.")

        # 7b. Apply the install profile's recipe, if this checkout has one.
        #
        # Since Drupal 10.3+, profiles like "standard" no longer ship their
        # default bundles (e.g. the "page" content type) as profile
        # config/install — that setup moved into a recipe under
        # core/recipes/<profile>, applied as a separate step. `drush si`
        # alone produces a site with zero content types on these versions,
        # which silently breaks reproduction of anything content-type
        # related. Older checkouts (pre-recipes, or Drupal 7) simply won't
        # have this directory, so this is a no-op there.
        if not is_drupal7:
            EnvironmentProvisioner._apply_profile_recipe(env_path, install_profile)

        # 8. Download and enable contrib modules
        EnvironmentProvisioner._stage(7, "Downloading and enabling modules/themes")
        contrib_modules = env_plan.get("contrib_modules", [])
        if own_dependencies:
            contrib_modules = list(dict.fromkeys(contrib_modules + own_dependencies))
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

        EnvironmentProvisioner._stage(8, "Git workspace + issue fork remote")
        # 12. Set up git workspace: identity + working branch.
        #
        # For contrib issues the repo under test is the nested clone at
        # modules/contrib/<project> (it has its own .git) — NOT the outer
        # Drupal core clone. Branching/remoting the core repo would make
        # every later diff, commit, and push target the wrong repository.
        from services.git_workspace_manager import GitWorkspaceManager
        work_root = module_path if module_path else env_path
        workspace = GitWorkspaceManager.setup_workspace(
            work_root, issue_id, git_name, git_email
        )
        if workspace.get("warnings"):
            for w in workspace["warnings"]:
                logger.warning(w)

        # 13. Add Drupal.org issue fork as the 'issue' remote and fetch
        #     existing branches if any contributor already pushed work.
        fork_info = GitWorkspaceManager.setup_issue_remote(
            work_root, project_name, issue_id
        )
        if fork_info.get("fetched") and fork_info.get("remote_branches"):
            print(
                f"[Fork] Existing branches on issue fork: "
                f"{', '.join(fork_info['remote_branches'])}"
            )
        else:
            # Fork doesn't exist yet — wait for user to click Get Push Access
            GitWorkspaceManager.wait_for_fork(
                work_root, project_name, issue_id
            )

        site_url = f"https://{env_name}.ddev.site"
        print(f"\nEnvironment successfully created! Access url: {site_url}")
        print(f"Working branch: {workspace['branch']}")
        if work_root != env_path:
            print(f"Working repo:   {work_root}")
        print(f"Push command:   {GitWorkspaceManager.get_push_command(work_root)}\n")

        return {
            "success": True,
            "env_name": env_name,
            "env_path": env_path,
            "work_root": work_root,
            "site_url": site_url,
            "reused": False,
            "branch": workspace["branch"],
        }
