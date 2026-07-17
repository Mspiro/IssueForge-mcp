"""
Git workspace manager for provisioned DDEV environments.

After the environment is provisioned (which clones the repo), this service:
1. Configures the git user identity so commits/branches have the right author.
2. Creates a working branch named after the issue.
3. Provides helpers to inspect what changed after a patch/MR is applied.

The resulting branch can be pushed directly from the provisioned env so the
user can open a PR on Drupal.org GitLab without leaving the terminal.
"""

import logging
import os
import subprocess
import time
from typing import Dict, List, Optional

from config import PROVISIONER_BRANCH_PATTERN

logger = logging.getLogger("IssueForge.GitWorkspaceManager")

_ISSUE_FORK_BASE = "https://git.drupalcode.org/issue"
# Pushing needs authentication. Anonymous HTTPS can fetch a public fork but
# can never push, so the push URL uses the SSH form — the exact one shown in
# the issue page's "Get push access" command block (host git.drupal.org, not
# git.drupalcode.org), authenticated by the contributor's GitLab SSH key.
_ISSUE_FORK_SSH_BASE = "git@git.drupal.org:issue"


class GitWorkspaceManager:

    @staticmethod
    def _git(args: List[str], cwd: str, check: bool = False, timeout: int = 30) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                ["git"] + args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Git command timed out after %ds: git %s", timeout, " ".join(args))
            return subprocess.CompletedProcess(
                args=["git"] + args,
                returncode=1,
                stdout="",
                stderr=f"git {' '.join(args)}: timed out after {timeout}s",
            )

    @staticmethod
    def setup_workspace(
        env_path: str,
        issue_id: str,
        git_name: str,
        git_email: str,
    ) -> Dict:
        """
        Configure git identity and create the issue working branch.

        Returns a dict with 'branch', 'identity_set', and any warnings.
        """
        warnings = []

        # 1. Set git identity (local to this repo only)
        name_ok = GitWorkspaceManager._git(
            ["config", "user.name", git_name], env_path
        ).returncode == 0
        email_ok = GitWorkspaceManager._git(
            ["config", "user.email", git_email], env_path
        ).returncode == 0

        if not (name_ok and email_ok):
            warnings.append("Could not set git identity — commits may lack an author.")
            logger.warning("git config user.name/email failed in %s", env_path)

        # 2. Create and checkout the working branch
        branch = PROVISIONER_BRANCH_PATTERN.format(issue_id=issue_id)
        result = GitWorkspaceManager._git(
            ["checkout", "-b", branch], env_path
        )
        if result.returncode != 0:
            # Branch may already exist — try checking it out
            result = GitWorkspaceManager._git(["checkout", branch], env_path)
            if result.returncode != 0:
                warnings.append(f"Could not create/checkout branch '{branch}'.")
                logger.warning("git checkout -b %s failed: %s", branch, result.stderr)
                branch = _get_current_branch(env_path) or "unknown"

        logger.info("Git workspace ready. Branch=%s env=%s", branch, env_path)
        return {
            "branch": branch,
            "identity_set": name_ok and email_ok,
            "warnings": warnings,
        }

    @staticmethod
    def get_status(env_path: str) -> Dict:
        """
        Return a summary of what has changed in the working tree since the
        last commit (i.e., what the applied patch/MR modified).
        """
        status_result = GitWorkspaceManager._git(["status", "--short"], env_path)
        diff_stat = GitWorkspaceManager._git(
            ["diff", "--stat", "HEAD"], env_path
        )
        changed_files = [
            line[3:].strip()
            for line in status_result.stdout.splitlines()
            if line.strip()
        ]
        return {
            "changed_files": changed_files,
            "diff_stat": diff_stat.stdout.strip(),
            "has_changes": bool(changed_files),
        }

    @staticmethod
    def get_diff(env_path: str, stat_only: bool = False) -> str:
        """Return the full unified diff or just the stat."""
        args = ["diff", "HEAD"]
        if stat_only:
            args.append("--stat")
        result = GitWorkspaceManager._git(args, env_path)
        return result.stdout

    @staticmethod
    def stage_and_commit(
        env_path: str,
        message: str,
    ) -> bool:
        """
        Stage all changes and create a commit so the state can be pushed.
        Returns True on success.
        """
        add_result = GitWorkspaceManager._git(["add", "-A"], env_path)
        if add_result.returncode != 0:
            logger.error("git add -A failed: %s", add_result.stderr)
            return False

        commit_result = GitWorkspaceManager._git(["commit", "-m", message], env_path)
        if commit_result.returncode != 0:
            logger.error("git commit failed: %s", commit_result.stderr)
            return False

        logger.info("Committed changes: %s", message)
        return True

    @staticmethod
    def _find_ddev_root(path: str) -> str:
        """Walk up from path to the directory holding .ddev (the Drupal root)."""
        current = os.path.abspath(path)
        for _ in range(8):
            if os.path.isdir(os.path.join(current, ".ddev")):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return path

    @staticmethod
    def files_pending_submission(env_path: str) -> List[str]:
        """
        Repo-relative paths of everything that would leave this machine on
        the next push/patch: uncommitted changes (staged + unstaged) plus
        commits not yet on the upstream branch (when an upstream exists).
        """
        files = set()
        for args in (
            ["diff", "--name-only", "HEAD"],
            ["diff", "--name-only", "--cached"],
        ):
            out = GitWorkspaceManager._git(args, env_path).stdout
            files.update(f for f in out.splitlines() if f.strip())
        upstream = GitWorkspaceManager._git(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
            env_path,
        )
        if upstream.returncode == 0 and upstream.stdout.strip():
            out = GitWorkspaceManager._git(
                ["diff", "--name-only", f"{upstream.stdout.strip()}..HEAD"],
                env_path,
            ).stdout
            files.update(f for f in out.splitlines() if f.strip())
        return sorted(files)

    @staticmethod
    def run_coding_standards_gate(env_path: str, ddev_root: str = "") -> bool:
        """
        Pre-submission PHPCS gate: check the pending files, autofix with
        phpcbf, re-check. Returns True when clean (or nothing to lint /
        toolchain unavailable); False when violations remain after autofix.

        ddev_root: the directory DDEV commands run from (the Drupal root).
        For contrib work_roots this differs from env_path — file paths are
        re-anchored onto it so phpcs inside the container can find them.
        """
        from services.coding_standards_checker import CodingStandardsChecker

        pending = GitWorkspaceManager.files_pending_submission(env_path)
        root = ddev_root or env_path
        if os.path.realpath(root) != os.path.realpath(env_path):
            prefix = os.path.relpath(env_path, root)
            pending = [os.path.join(prefix, f) for f in pending]

        result = CodingStandardsChecker.check_and_fix(root, pending)
        if result.get("skipped_reason"):
            print(f"  [CS] Skipped: {result['skipped_reason']}")
            return True
        if result.get("autofixed"):
            print("  [CS] phpcbf auto-fixed coding-standards violations "
                  "(now part of your working tree).")
        if result["passed"]:
            print(f"  [CS] PHPCS clean ({len(result['checked'])} file(s)).")
            return True
        print("  [CS] PHPCS violations remain after autofix:")
        for line in result["output"].splitlines()[-25:]:
            print(f"    {line}")
        return False

    @staticmethod
    def issue_remote_name(project: str, issue_id: str) -> str:
        """
        The remote name drupal.org's own "Get push access" instructions use:
        "<project>-<issue_id>" (e.g. "encrypt-2915538"). Matching it means
        every command IssueForge prints can be cross-checked 1:1 against the
        command block on the issue page.
        """
        return f"{project}-{issue_id}"

    @staticmethod
    def find_issue_remote(env_path: str) -> Optional[str]:
        """
        Find the issue-fork remote by URL rather than by name, so both the
        canonical "<project>-<issue_id>" name and the legacy "issue" name
        (environments provisioned by older IssueForge versions) are found.
        """
        result = GitWorkspaceManager._git(["remote", "-v"], env_path)
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "/issue/" in parts[1]:
                return parts[0]
        return None

    @staticmethod
    def checkout_mr_branch(env_path: str, remote_name: str, branch: str) -> Dict:
        """
        Check out an existing MR's source branch from the issue fork, exactly
        like the issue page instructs:
            git checkout -b '<branch>' --track '<remote>/<branch>'

        This is the only correct way to UPDATE an existing MR: a locally
        created work branch has diverged history (the MR's changes exist
        there as commits, locally as an applied diff), so pushing
        HEAD:<branch> from it is rejected as non-fast-forward.

        Refuses to run on a dirty tree — a checkout over uncommitted changes
        that overlap the MR's files would either conflict or silently mix
        states. Returns {success, branch, message}.
        """
        status = GitWorkspaceManager._git(["status", "--porcelain"], env_path)
        if status.stdout.strip():
            return {
                "success": False,
                "branch": branch,
                "message": (
                    "Working tree has uncommitted changes. Commit, stash, or "
                    "discard them before checking out the MR branch."
                ),
            }

        fetch = GitWorkspaceManager._git(
            ["fetch", remote_name, "--quiet"], env_path, timeout=120
        )
        if fetch.returncode != 0:
            return {
                "success": False,
                "branch": branch,
                "message": f"Could not fetch {remote_name}: {fetch.stderr.strip()}",
            }

        # Existing local branch → plain checkout; otherwise create tracking.
        exists = GitWorkspaceManager._git(
            ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], env_path
        )
        if exists.returncode == 0:
            result = GitWorkspaceManager._git(["checkout", branch], env_path)
        else:
            result = GitWorkspaceManager._git(
                ["checkout", "-b", branch, "--track", f"{remote_name}/{branch}"],
                env_path,
            )
        if result.returncode != 0:
            return {
                "success": False,
                "branch": branch,
                "message": result.stderr.strip(),
            }
        logger.info("Checked out MR branch %s tracking %s/%s",
                    branch, remote_name, branch)
        return {"success": True, "branch": branch, "message": ""}

    @staticmethod
    def setup_issue_remote(env_path: str, project: str, issue_id: str) -> Dict:
        """
        Add the Drupal.org issue fork as a remote, then try to fetch any
        existing branches (in case a contributor already pushed work).

        Matches the issue page's "Get push access" command block exactly:
            remote name: <project>-<issue_id>
            fetch: https://git.drupalcode.org/issue/<project>-<issue_id>.git
            push:  git@git.drupal.org:issue/<project>-<issue_id>.git

        Fetch stays on anonymous HTTPS (works without any credentials); the
        push URL is the SSH form from those instructions — anonymous HTTPS
        pushes are always rejected, which previously made every push fail.

        Returns a dict with remote_name, remote_url, push_url, fetched
        (bool), remote_branches, warnings.
        """
        remote_name = GitWorkspaceManager.issue_remote_name(project, issue_id)
        fork_url = f"{_ISSUE_FORK_BASE}/{project}-{issue_id}.git"
        push_url = f"{_ISSUE_FORK_SSH_BASE}/{project}-{issue_id}.git"
        warnings = []

        # Replace any stale remote (including the legacy 'issue' name used
        # by environments provisioned before the rename).
        GitWorkspaceManager._git(["remote", "remove", "issue"], env_path)
        GitWorkspaceManager._git(["remote", "remove", remote_name], env_path)
        add_result = GitWorkspaceManager._git(
            ["remote", "add", remote_name, fork_url], env_path
        )
        if add_result.returncode != 0:
            msg = f"Could not add issue remote: {add_result.stderr.strip()}"
            warnings.append(msg)
            logger.warning(msg)
            return {"remote_name": remote_name, "remote_url": fork_url,
                    "push_url": push_url, "fetched": False,
                    "remote_branches": [], "warnings": warnings}

        push_result = GitWorkspaceManager._git(
            ["remote", "set-url", "--push", remote_name, push_url], env_path
        )
        if push_result.returncode != 0:
            warnings.append(
                f"Could not set SSH push URL: {push_result.stderr.strip()}"
            )

        # Fetch — may fail if the fork has not been created yet; that is normal
        fetch_result = GitWorkspaceManager._git(
            ["fetch", remote_name, "--quiet"], env_path
        )
        fetched = fetch_result.returncode == 0

        remote_branches: List[str] = []
        if fetched:
            ls_result = GitWorkspaceManager._git(
                ["branch", "-r", "--list", f"{remote_name}/*"], env_path
            )
            for line in ls_result.stdout.splitlines():
                b = line.strip()
                if b.startswith(f"{remote_name}/"):
                    b = b[len(remote_name) + 1:]
                if b:
                    remote_branches.append(b)

        if not fetched:
            warnings.append(
                "Issue fork not yet created. "
                "On the issue page click 'Get push access' to initialise it, "
                f"then run: git push --set-upstream {remote_name} HEAD"
            )

        logger.info(
            "Issue remote set up. name=%s fork=%s push=%s fetched=%s branches=%s",
            remote_name, fork_url, push_url, fetched, remote_branches,
        )
        return {
            "remote_name": remote_name,
            "remote_url": fork_url,
            "push_url": push_url,
            "fetched": fetched,
            "remote_branches": remote_branches,
            "warnings": warnings,
        }

    @staticmethod
    def wait_for_fork(
        env_path: str,
        project: str,
        issue_id: str,
        poll_interval: int = 2,
        timeout: int = 300,
    ) -> bool:
        """
        Block until the Drupal.org issue fork becomes available, polling
        every `poll_interval` seconds.  Prints a live counter so the user
        can see the tool is watching.

        Returns True when the fork is ready (and fetches it), False if the
        user cancels with Ctrl+C or the timeout is reached.

        How it works:
          `git ls-remote <fork_url>` exits 0 as soon as the repository is
          created — no credentials needed for public Drupal.org forks.
          Once confirmed, a full `git fetch issue` runs to pull any branches.
        """
        fork_url = f"{_ISSUE_FORK_BASE}/{project}-{issue_id}.git"
        remote_name = GitWorkspaceManager.issue_remote_name(project, issue_id)
        issue_page = (
            f"https://www.drupal.org/project/{project}/issues/{issue_id}"
        )

        print()
        print("  ┌─ Get push access ───────────────────────────────────────┐")
        print(f"  │  1. Open the issue page:                                │")
        print(f"  │     {issue_page:<53}│")
        print(f"  │  2. Scroll to the 'Merge requests' section              │")
        print(f"  │  3. Click  'Get push access'                            │")
        print(f"  │                                                          │")
        print(f"  │  IssueForge will detect it automatically.               │")
        print(f"  │  Press Ctrl+C to skip and push manually later.          │")
        print("  └──────────────────────────────────────────────────────────┘")
        print()

        elapsed = 0
        try:
            while elapsed < timeout:
                result = subprocess.run(
                    ["git", "ls-remote", "--quiet", fork_url],
                    capture_output=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    print(f"\r[Fork] Fork detected after {elapsed}s! Fetching branches…")
                    GitWorkspaceManager._git(
                        ["fetch", remote_name, "--quiet"], env_path
                    )

                    ls = GitWorkspaceManager._git(
                        ["branch", "-r", "--list", f"{remote_name}/*"], env_path
                    )
                    remote_branches = []
                    for line in ls.stdout.splitlines():
                        b = line.strip()
                        if b.startswith(f"{remote_name}/"):
                            b = b[len(remote_name) + 1:]
                        if b:
                            remote_branches.append(b)

                    if remote_branches:
                        print(
                            f"[Fork] Branches on fork: {', '.join(remote_branches)}"
                        )
                    else:
                        print("[Fork] Fork is empty — ready for your first push.")

                    print(
                        f"[Fork] Push command: "
                        f"{GitWorkspaceManager.get_push_command(env_path)}"
                    )
                    return True

                print(
                    f"\r  Waiting for fork… {elapsed}s "
                    f"(timeout in {timeout - elapsed}s)   ",
                    end="",
                    flush=True,
                )
                time.sleep(poll_interval)
                elapsed += poll_interval

        except KeyboardInterrupt:
            print("\n[Fork] Skipped. When ready, run:")
            print(
                f"  git -C <env_path> fetch {remote_name} && "
                f"{GitWorkspaceManager.get_push_command(env_path)}"
            )
            return False

        print(f"\n[Fork] Timed out after {timeout}s. Run manually when ready:")
        print(f"  git fetch {remote_name} && git push --set-upstream {remote_name} HEAD")
        return False

    @staticmethod
    def submit_with_confirmation(
        env_path: str,
        issue_id: str = "",
        suggested_commit_msg: str = "",
        drupal_username: str = "",
        drupal_password: str = "",
    ) -> bool:
        """
        Show the full picture of pending changes, then let the user choose
        how to submit:

          [m] Merge Request — commit + push to the Drupal.org issue fork
          [p] Upload patch  — generate a .patch file and upload to the issue
          [n] Skip          — do nothing, handle manually

        Nothing is sent anywhere without an explicit 'y' at the final step.
        Returns True if the chosen action completed successfully.
        """
        W = 65
        sep = "=" * W

        # ---- Gather state --------------------------------------------------
        status_r = GitWorkspaceManager._git(["status", "--short"], env_path)
        uncommitted = [l for l in status_r.stdout.splitlines() if l.strip()]
        diff_stat = GitWorkspaceManager._git(
            ["diff", "HEAD", "--stat"], env_path
        ).stdout.strip()
        log_r = GitWorkspaceManager._git(["log", "--oneline", "-5", "HEAD"], env_path)
        recent = [l for l in log_r.stdout.splitlines() if l.strip()]

        branch = _get_current_branch(env_path) or "unknown"
        remote_name = GitWorkspaceManager.find_issue_remote(env_path) or "origin"
        remote_url = GitWorkspaceManager._git(
            ["remote", "get-url", remote_name], env_path
        ).stdout.strip()

        # ---- Display summary -----------------------------------------------
        print()
        print(sep)
        print("  Changes ready to submit")
        print(sep)
        print(f"  Branch  : {branch}")
        print(f"  Remote  : {remote_name}  →  {remote_url}")
        print()

        if uncommitted:
            print(f"  Uncommitted changes ({len(uncommitted)} file(s)):")
            for line in uncommitted:
                print(f"    {line}")
            print()

        if diff_stat:
            print("  Diff summary:")
            for line in diff_stat.splitlines():
                print(f"    {line}")
            print()

        if recent:
            print("  Recent commits:")
            for line in recent:
                print(f"    {line}")
            print()

        print(sep)
        print()

        # ---- Choose submission method --------------------------------------
        print("  How would you like to submit?")
        print("  [m] Merge Request — commit and push to the issue fork on GitLab")
        print("  [p] Upload patch  — generate a .patch file and attach to the issue")
        print("  [n] Skip          — I'll handle it manually")
        print()

        try:
            choice = input("  Choice [m/p/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return False

        if choice == "m":
            return GitWorkspaceManager.push_with_confirmation(
                env_path, suggested_commit_msg=suggested_commit_msg
            )

        if choice == "p":
            return GitWorkspaceManager._submit_as_patch(
                env_path, issue_id, suggested_commit_msg,
                drupal_username, drupal_password
            )

        print("  Skipped. Run manually when ready:")
        print(f"    cd {env_path}")
        print(f"    {GitWorkspaceManager.get_push_command(env_path)}")
        return False

    @staticmethod
    def _submit_as_patch(
        env_path: str,
        issue_id: str,
        suggested_name: str,
        drupal_username: str,
        drupal_password: str,
    ) -> bool:
        """
        Generate a .patch file from current changes, then either upload it to
        Drupal.org (when credentials are present) or save it locally with
        manual upload instructions.
        """
        from services.drupal_patch_uploader import DrupalPatchUploader
        import os

        # Suggest a patch filename
        slug = (
            suggested_name.lower()
            .replace(" ", "-")
            .replace("/", "-")
            .replace("\\", "-")[:40]
        ) if suggested_name else "fix"
        default_filename = f"{issue_id}-{slug}.patch" if issue_id else f"{slug}.patch"

        print()
        try:
            typed = input(
                f"  Patch filename [{default_filename}]: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return False
        patch_filename = typed or default_filename

        patch_path = os.path.join(env_path, patch_filename)

        # Coding-standards gate — a patch with PHPCS violations fails the
        # drupal.org pipeline the moment anyone applies it in an MR.
        print("\n  Running coding-standards gate (phpcs + autofix)…")
        cs_clean = GitWorkspaceManager.run_coding_standards_gate(
            env_path, GitWorkspaceManager._find_ddev_root(env_path)
        )
        if not cs_clean:
            try:
                answer = input(
                    "  PHPCS violations remain. Generate the patch anyway? "
                    "[y/N]: "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  Cancelled.")
                return False
            if answer not in ("y", "yes"):
                print("  Patch generation cancelled.")
                return False

        print(f"\n  Generating patch → {patch_path}")
        if not DrupalPatchUploader.generate_patch(env_path, patch_path):
            print("  [ERROR] No diff found — nothing to save.")
            return False
        size_kb = os.path.getsize(patch_path) // 1024
        print(f"  [OK] Patch saved ({size_kb} KB)")
        print()

        # ---- Upload or manual instructions --------------------------------
        if drupal_username and drupal_password:
            issue_url = (
                f"https://www.drupal.org/node/{issue_id}"
                if issue_id else "the issue page"
            )
            print(f"  Will upload to: {issue_url}")
            print(f"  File           : {patch_filename}")
            print(f"  As user        : {drupal_username}")
            print()
            try:
                answer = input("  Upload now? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  Upload cancelled — patch saved locally.")
                return False

            if answer not in ("y", "yes"):
                print(f"  Upload cancelled — patch saved at:\n    {patch_path}")
                return False

            print("  Uploading…")
            result = DrupalPatchUploader.upload_to_issue(
                patch_path, issue_id, drupal_username, drupal_password
            )
            if result.get("success"):
                print(f"  [OK] Patch uploaded (fid={result.get('fid')})")
                if result.get("comment_id"):
                    print(f"       Comment posted (cid={result.get('comment_id')})")
                return True
            else:
                print(f"  [ERROR] {result.get('error')}")
                print(f"  Patch is still available locally:\n    {patch_path}")
                return False

        else:
            # No credentials — guide manual upload
            issue_url = (
                f"https://www.drupal.org/node/{issue_id}#comment-form"
                if issue_id else "the issue page"
            )
            print("  Drupal.org credentials not configured.")
            print("  To upload manually:")
            print(f"    1. Open  {issue_url}")
            print(f"    2. Scroll to the comment form")
            print(f"    3. Click 'Attach file' and select:\n       {patch_path}")
            print(f"    4. Submit the comment")
            print()
            print("  To configure credentials for automatic upload:")
            print("    python scripts/setup.py --force")
            return False

    @staticmethod
    def push_with_confirmation(
        env_path: str,
        suggested_commit_msg: str = "",
    ) -> bool:
        """
        Show a full picture of pending changes, ask for a commit message (if
        there are uncommitted changes), then require an explicit 'y' before
        anything is pushed.  Pressing Enter or typing 'n' always cancels.

        Nothing is ever sent to the remote without a deliberate human 'y'.

        Returns True if the push completed successfully, False otherwise.
        """
        import sys

        W = 65
        sep = "=" * W

        branch = _get_current_branch(env_path) or "unknown"
        remote_name = GitWorkspaceManager.find_issue_remote(env_path) or "origin"
        remote_url = GitWorkspaceManager._git(
            ["remote", "get-url", remote_name], env_path
        ).stdout.strip()

        # What's uncommitted
        status = GitWorkspaceManager._git(["status", "--short"], env_path)
        uncommitted = [l for l in status.stdout.splitlines() if l.strip()]

        # Diff summary of ALL changes (staged + unstaged vs HEAD)
        diff_stat = GitWorkspaceManager._git(
            ["diff", "HEAD", "--stat"], env_path
        ).stdout.strip()

        # Commits already staged (HEAD vs remote tracking)
        log_result = GitWorkspaceManager._git(
            ["log", "--oneline", "-10", "HEAD"], env_path
        )
        recent_commits = [l for l in log_result.stdout.splitlines() if l.strip()]

        # ---- Display -------------------------------------------------------
        print()
        print(sep)
        print("  Review before pushing")
        print(sep)
        print(f"  Branch : {branch}")
        print(f"  Remote : {remote_name}  →  {remote_url}")
        print()

        if uncommitted:
            print(f"  Uncommitted changes ({len(uncommitted)} files):")
            for line in uncommitted:
                print(f"    {line}")
            print()

        if diff_stat:
            print("  Diff summary:")
            for line in diff_stat.splitlines():
                print(f"    {line}")
            print()

        if recent_commits:
            print("  Recent commits on this branch:")
            for line in recent_commits[:5]:
                print(f"    {line}")
            print()

        print(sep)

        # ---- Coding-standards gate (before commit, so autofixes ride along)
        print()
        print("  Running coding-standards gate (phpcs + autofix)…")
        cs_clean = GitWorkspaceManager.run_coding_standards_gate(
            env_path, GitWorkspaceManager._find_ddev_root(env_path)
        )
        if not cs_clean:
            try:
                answer = input(
                    "  PHPCS violations remain — the drupal.org pipeline WILL "
                    "fail. Push anyway? [y/N]: "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  Cancelled.")
                return False
            if answer not in ("y", "yes"):
                print("  Push cancelled — fix the violations above and retry.")
                return False
        # Refresh uncommitted state: phpcbf may have modified files.
        status = GitWorkspaceManager._git(["status", "--short"], env_path)
        uncommitted = [l for l in status.stdout.splitlines() if l.strip()]

        # ---- Commit step (only when there are uncommitted changes) ---------
        commit_msg = ""
        if uncommitted:
            default_msg = suggested_commit_msg or f"Issue work on branch {branch}"
            print(f"  A commit is needed before pushing.")
            print(f"  Suggested message: {default_msg}")
            print()
            try:
                typed = input(
                    "  Commit message (Enter to use suggestion, 'n' to cancel): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Cancelled.")
                return False

            if typed.lower() == "n":
                print("  Push cancelled — no changes sent.")
                return False
            commit_msg = typed or default_msg

            # Stage and commit
            add = GitWorkspaceManager._git(["add", "-A"], env_path)
            if add.returncode != 0:
                print(f"  [ERROR] git add failed: {add.stderr.strip()}")
                return False
            commit = GitWorkspaceManager._git(["commit", "-m", commit_msg], env_path)
            if commit.returncode != 0:
                print(f"  [ERROR] git commit failed: {commit.stderr.strip()}")
                return False
            print(f"  [OK] Committed: {commit_msg}")
            print()

        # ---- Final push confirmation ----------------------------------------
        push_cmd = f"git push {remote_name} HEAD:{branch}"
        print(f"  Command that will run:")
        print(f"    {push_cmd}")
        print()
        print("  This will send your changes to the remote repository.")
        print("  There is no undo once pushed.")
        print()

        try:
            answer = input("  Push now? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Push cancelled.")
            return False

        if answer not in ("y", "yes"):
            print("  Push cancelled — changes remain local.")
            print(f"  When ready, run manually:  cd {env_path} && {push_cmd}")
            return False

        # ---- Execute push --------------------------------------------------
        print(f"\n  Pushing to {remote_name}…")
        push_result = GitWorkspaceManager._git(
            ["push", remote_name, f"HEAD:{branch}"], env_path
        )
        if push_result.returncode == 0:
            print(f"  [OK] Pushed successfully → {remote_url}")
            print(f"\n  Open a Merge Request at:")
            print(f"    https://git.drupalcode.org/issue/{remote_url.split('/issue/')[-1].replace('.git','')}/merge_requests/new")
            return True
        else:
            print(f"  [ERROR] Push failed:\n{push_result.stderr.strip()}")
            print(f"  Retry manually:  cd {env_path} && {push_cmd}")
            return False

    @staticmethod
    def get_push_command(env_path: str) -> str:
        """
        Return the git push command the user should run to open a PR.
        Prefers the Drupal.org issue-fork remote when available, using the
        same command form as the issue page's instructions.
        """
        branch = _get_current_branch(env_path) or "issue-work"
        issue_remote = GitWorkspaceManager.find_issue_remote(env_path)
        if issue_remote:
            fork_url = GitWorkspaceManager._git(
                ["remote", "get-url", issue_remote], env_path
            ).stdout.strip()
            return (
                f"git push --set-upstream {issue_remote} HEAD  # fork: {fork_url}"
            )
        remote_url = GitWorkspaceManager._git(
            ["remote", "get-url", "origin"], env_path
        ).stdout.strip()
        return f"git push origin {branch}  # remote: {remote_url}"


def _get_current_branch(env_path: str) -> Optional[str]:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=env_path, capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else None
