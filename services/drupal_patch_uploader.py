"""
DrupalPatchUploader — generate a unified diff and upload it to a Drupal.org issue.

Upload path (when DRUPAL_ORG_USERNAME + DRUPAL_ORG_PASSWORD are configured):
  1. POST /api-d7/file.json  — upload the .patch file, get back a fid
  2. POST /api-d7/comment.json — attach fid to a new comment on the issue node

Fallback (no credentials):
  Saves the .patch file locally and prints the manual upload URL.
"""

import logging
import os
import subprocess
import base64

import requests

logger = logging.getLogger("IssueForge.DrupalPatchUploader")

BASE_URL = "https://www.drupal.org/api-d7"


class DrupalPatchUploader:

    @staticmethod
    def generate_patch(env_path: str, output_path: str) -> bool:
        """
        Write a unified diff of all changes vs HEAD to output_path.
        Tries staged+unstaged first, then only staged, then only unstaged.
        Returns True if the file was written with non-empty content.
        """
        for args in (
            ["git", "diff", "HEAD"],           # unstaged after last commit
            ["git", "diff", "--cached"],        # staged only
            ["git", "diff"],                    # working tree vs index
        ):
            result = subprocess.run(
                args, cwd=env_path, capture_output=True, text=True, timeout=30
            )
            if result.stdout.strip():
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(result.stdout)
                logger.info("Patch written to %s (%d bytes)", output_path, len(result.stdout))
                return True

        logger.warning("No diff found — nothing to patch.")
        return False

    @staticmethod
    def validate_credentials(username: str, password: str) -> tuple:
        """
        Try a lightweight authenticated call to verify Drupal.org credentials.
        Returns (True, message) or (False, reason).
        """
        try:
            auth = base64.b64encode(f"{username}:{password}".encode()).decode()
            resp = requests.get(
                f"{BASE_URL}/user.json?name={username}",
                headers={"Authorization": f"Basic {auth}"},
                timeout=10,
            )
            if resp.status_code == 200:
                items = resp.json().get("list", [])
                if items:
                    uid = items[0].get("uid", "?")
                    return True, f"Authenticated as {username} (uid {uid})"
                return True, f"Authenticated as {username}"
            if resp.status_code == 401:
                return False, "Invalid username or password (401)."
            return False, f"Drupal.org API returned {resp.status_code}."
        except Exception as e:
            return False, f"Could not reach Drupal.org: {e}"

    @staticmethod
    def upload_to_issue(
        patch_path: str,
        issue_id: str,
        username: str,
        password: str,
        comment_text: str = "Patch uploaded via IssueForge.",
    ) -> dict:
        """
        Upload the patch file to Drupal.org and attach it to the issue via a comment.

        Returns a dict with keys: success, fid, comment_id (on success)
                                   or success=False, error (on failure).
        """
        if not username or not password:
            return {"success": False, "error": "Drupal.org credentials not configured."}

        auth = base64.b64encode(f"{username}:{password}".encode()).decode()
        auth_header = {"Authorization": f"Basic {auth}"}
        patch_filename = os.path.basename(patch_path)

        # Step 1 — Upload the file
        try:
            with open(patch_path, "rb") as f:
                content = f.read()

            upload_resp = requests.post(
                f"{BASE_URL}/file.json",
                data=content,
                headers={
                    **auth_header,
                    "Content-Type": "application/octet-stream",
                    "Content-Disposition": f'attachment; filename="{patch_filename}"',
                },
                timeout=30,
            )
        except Exception as e:
            return {"success": False, "error": f"File upload request failed: {e}"}

        if upload_resp.status_code not in (200, 201):
            return {
                "success": False,
                "error": f"File upload failed ({upload_resp.status_code}): {upload_resp.text[:300]}",
            }

        fid = upload_resp.json().get("fid")
        if not fid:
            return {"success": False, "error": "Upload succeeded but no fid returned."}

        logger.info("Patch uploaded — fid=%s filename=%s", fid, patch_filename)

        # Step 2 — Attach to the issue via a comment
        try:
            comment_resp = requests.post(
                f"{BASE_URL}/comment.json",
                json={
                    "nid": {"id": str(issue_id)},
                    "comment_body": {"value": comment_text, "format": "plain_text"},
                    "field_issue_files": [{"fid": str(fid)}],
                },
                headers={**auth_header, "Content-Type": "application/json"},
                timeout=30,
            )
        except Exception as e:
            return {
                "success": False,
                "fid": fid,
                "error": f"File uploaded (fid={fid}) but comment request failed: {e}",
            }

        if comment_resp.status_code in (200, 201):
            cid = comment_resp.json().get("id") or comment_resp.json().get("cid")
            logger.info("Comment posted — cid=%s", cid)
            return {"success": True, "fid": fid, "comment_id": cid}

        return {
            "success": False,
            "fid": fid,
            "error": (
                f"File uploaded (fid={fid}) but comment failed "
                f"({comment_resp.status_code}): {comment_resp.text[:300]}"
            ),
        }
