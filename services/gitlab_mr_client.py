"""
GitLab MR client for Drupal.org (git.drupalcode.org).

MR detection strategy (in priority order):
1. Scan issue comments for git.drupalcode.org MR URLs — most reliable because
   contributors always post the MR link in the issue comment thread.
2. Call the GitLab API to fetch MR metadata (title, status, source branch,
   description) when a token is available.
3. Download the MR diff as a unified patch (`.patch` endpoint — works without
   a token for public projects).

Drupal.org API v7 does NOT expose MR data, so comment scanning is the
primary detection mechanism.
"""

import logging
import os
import re
import requests
import time
from typing import Dict, List, Optional

from config import GITLAB_API_BASE, GITLAB_HOST, DRUPAL_API_RETRIES, MR_DETECTION_MAX_COMMENTS

logger = logging.getLogger("IssueForge.GitlabMrClient")

# Regex for MR URLs: https://git.drupalcode.org/project/drupal/-/merge_requests/123
_MR_URL_PATTERN = re.compile(
    r"https://git\.drupalcode\.org/project/([a-z0-9_\-]+)/-/merge_requests/(\d+)",
    re.IGNORECASE,
)


class GitlabMrClient:
    """
    Detects and downloads Merge Requests associated with a Drupal.org issue.
    """

    def __init__(self, token: str = ""):
        self.token = token.strip()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "IssueForge/1.0"})
        if self.token:
            self.session.headers["PRIVATE-TOKEN"] = self.token

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect_mr_urls_from_comments(self, comment_bodies: List[str]) -> List[Dict]:
        """
        Scan comment HTML for MR URLs.
        Returns a list of dicts: {project, mr_iid, url}.
        """
        seen = set()
        results = []
        for body in comment_bodies:
            for match in _MR_URL_PATTERN.finditer(body):
                project = match.group(1)
                mr_iid = match.group(2)
                key = (project, mr_iid)
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "project": project,
                        "mr_iid": mr_iid,
                        "url": match.group(0),
                    })
        logger.info("Detected %d unique MR(s) from comments.", len(results))
        return results

    def detect_mr_urls_from_issue_body(self, issue_html: str) -> List[Dict]:
        """Scan the issue description itself for MR URLs."""
        return self.detect_mr_urls_from_comments([issue_html or ""])

    def detect_mrs_for_issue(self, metadata: Dict, comment_client) -> List[Dict]:
        """
        Detect MRs for an issue, given its full metadata dict.

        This is the single source of truth for *which* comments get scanned
        — callers (preview, analyze) must go through this rather than each
        picking their own comment sample, or the same issue can silently
        yield different MR results depending on which entry point ran.

        Scans the most recent MR_DETECTION_MAX_COMMENTS comments (recency,
        not a scattered first/middle/last sample) — MRs are typically
        created and linked as a thread progresses, so recent comments are
        where a reference is most likely to land. For long threads this
        still can't guarantee finding a link buried early in an old thread,
        but it is deterministic and identical across every caller.
        """
        issue_html = metadata.get("problem_description_html", "")
        comment_ids = metadata.get("comment_ids", [])
        recent_ids = comment_ids[-MR_DETECTION_MAX_COMMENTS:]

        comment_bodies = []
        if recent_ids:
            comments = comment_client.get_multiple_comments(recent_ids)
            comment_bodies = [c["body_html"] for c in comments if c.get("body_html")]

        raw = self.detect_mr_urls_from_issue_body(issue_html)
        raw += self.detect_mr_urls_from_comments(comment_bodies)

        seen = set()
        unique = []
        for mr in raw:
            key = (mr["project"], mr["mr_iid"])
            if key not in seen:
                seen.add(key)
                unique.append(mr)
        return unique

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def get_mr_details(self, project: str, mr_iid: str) -> Optional[Dict]:
        """
        Fetch MR metadata from the GitLab API.
        Returns None if the request fails or no token is provided.
        """
        encoded = requests.utils.quote(f"project/{project}", safe="")
        url = f"{GITLAB_API_BASE}/projects/{encoded}/merge_requests/{mr_iid}"
        try:
            resp = self._safe_get(url)
            if resp is None:
                return None
            data = resp.json()
            return {
                "id": data.get("iid"),
                "title": data.get("title"),
                "state": data.get("state"),           # opened / merged / closed
                "source_branch": data.get("source_branch"),
                "target_branch": data.get("target_branch"),
                "description": data.get("description", ""),
                "author": data.get("author", {}).get("name"),
                "web_url": data.get("web_url"),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "project": project,
                "mr_iid": mr_iid,
                # The MR's pipelines run in the SOURCE project's context
                # (the issue fork), not the target project this MR is
                # opened against — e.g. an MR targeting "project/drupal"
                # commonly has its source branch and pipelines on
                # "issue/drupal-<id>", a different GitLab project entirely.
                # Use this numeric ID (not the naming convention) to look up
                # pipeline status, since forks don't reliably follow any
                # one naming pattern.
                "source_project_id": data.get("source_project_id"),
            }
        except Exception as e:
            logger.warning("Could not fetch MR details for %s!%s: %s", project, mr_iid, e)
            return None

    def get_latest_pipeline_status(self, project_id, ref: str) -> Optional[Dict]:
        """
        Fetch the most recent CI pipeline status for a branch/ref.

        project_id: the exact GitLab project identifier to query — either
        a numeric project ID (preferred; e.g. get_mr_details()'s
        "source_project_id") or an already-namespaced path like
        "project/drupal" or "issue/drupal-2727281". This is taken as-is and
        URL-encoded whole — it does NOT get a "project/" prefix added,
        since MR pipelines commonly run under the source fork's project
        (e.g. "issue/<project>-<issue_id>"), which is a different
        namespace convention than the target project.

        Returns {"status": "success"/"failed"/"running"/..., "web_url": ...,
        "sha": ...} for the newest pipeline, or None if the request fails or
        no pipeline exists for that ref.
        """
        if not project_id:
            return None
        encoded = requests.utils.quote(str(project_id), safe="")
        url = (
            f"{GITLAB_API_BASE}/projects/{encoded}/pipelines"
            f"?ref={requests.utils.quote(ref, safe='')}&per_page=1"
        )
        try:
            resp = self._safe_get(url)
            if resp is None:
                return None
            data = resp.json()
            if not data:
                return None
            latest = data[0]
            return {
                "status": latest.get("status"),
                "web_url": latest.get("web_url"),
                "sha": latest.get("sha"),
            }
        except Exception as e:
            logger.warning(
                "Could not fetch pipeline status for %s@%s: %s", project_id, ref, e
            )
            return None

    # ------------------------------------------------------------------
    # Diff download
    # ------------------------------------------------------------------

    def download_mr_diff(
        self, project: str, mr_iid: str, output_path: str
    ) -> Optional[str]:
        """
        Download the MR as a unified patch file.

        Uses the GitLab `.patch` endpoint — available without a token for
        public projects.  The resulting file is compatible with `git apply`.

        Returns the output_path on success, None on failure.
        """
        patch_url = (
            f"https://{GITLAB_HOST}/project/{project}/-/merge_requests/{mr_iid}.patch"
        )
        logger.info("Downloading MR diff from %s", patch_url)
        try:
            resp = self.session.get(patch_url, timeout=60, allow_redirects=True)
            if resp.status_code == 200 and resp.content:
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                logger.info("Saved MR diff to %s (%d bytes)", output_path, len(resp.content))
                return output_path
            logger.warning(
                "Failed to download MR diff: HTTP %d for %s", resp.status_code, patch_url
            )
        except Exception as e:
            logger.error("Error downloading MR diff: %s", e)
        return None

    # ------------------------------------------------------------------
    # Combined: detect + enrich + download
    # ------------------------------------------------------------------

    def fetch_all_mrs(
        self,
        comment_bodies: List[str],
        issue_html: str,
        env_path: str,
    ) -> List[Dict]:
        """
        Full pipeline: detect → enrich metadata → download diffs.

        Returns a list of MR dicts with an added 'diff_path' key pointing to
        the downloaded patch file (or None if download failed).
        """
        raw = self.detect_mr_urls_from_issue_body(issue_html)
        raw += self.detect_mr_urls_from_comments(comment_bodies)

        # Deduplicate preserving order
        seen = set()
        unique = []
        for item in raw:
            key = (item["project"], item["mr_iid"])
            if key not in seen:
                seen.add(key)
                unique.append(item)

        enriched = []
        for mr in unique:
            details = self.get_mr_details(mr["project"], mr["mr_iid"])
            result = details or mr  # fall back to detection-only dict if API fails

            # Download diff
            diff_filename = f"mr_{mr['project']}_{mr['mr_iid']}.patch"
            diff_path = os.path.join(env_path, diff_filename)
            downloaded = self.download_mr_diff(mr["project"], mr["mr_iid"], diff_path)
            result["diff_path"] = downloaded
            result["diff_filename"] = diff_filename if downloaded else None

            enriched.append(result)
            logger.info(
                "MR %s!%s — state=%s diff_downloaded=%s",
                mr["project"], mr["mr_iid"],
                result.get("state", "unknown"),
                downloaded is not None,
            )

        return enriched

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _safe_get(self, url: str) -> Optional[requests.Response]:
        backoff = 1
        for attempt in range(DRUPAL_API_RETRIES):
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp
                if resp.status_code == 429:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                if resp.status_code == 401:
                    logger.warning("GitLab API 401 — token missing or invalid for %s", url)
                    return None
                logger.warning("GitLab API HTTP %d for %s", resp.status_code, url)
                return None
            except Exception as e:
                logger.error("Request error for %s: %s", url, e)
                if attempt < DRUPAL_API_RETRIES - 1:
                    time.sleep(backoff)
                    backoff *= 2
        return None
