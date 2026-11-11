"""
Read-only client for issues that live as GitLab work items on
git.drupalcode.org (projects whose queues moved off drupal.org, e.g. ai,
ai_agents). Returns the same metadata/comment shapes DrupalAPIClient and
DrupalCommentClient return, so the rest of the pipeline doesn't care where
an issue came from. GET requests only.
"""

import logging
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from config import GITLAB_API_BASE, DRUPAL_API_RETRIES
from services.credential_manager import get_credentials

logger = logging.getLogger("IssueForge.GitlabIssueClient")

_WORK_ITEM_URL = re.compile(
    r"git\.drupalcode\.org/project/([a-z0-9_\-]+)/-/(?:work_items|issues)/(\d+)",
    re.IGNORECASE,
)

# Comment IDs for GitLab notes: "gl:<project>:<iid>:<note_id>"
COMMENT_PREFIX = "gl:"

_STATE_MAP = {
    "active": "Active",
    "accepted": "Active",
    "inprogress": "Active",
    "blocked": "Postponed",
    "needswork": "Needs work",
    "needsreview": "Needs review",
    "rtbc": "Reviewed & tested by the community",
    "fixed": "Fixed",
    "postponed": "Postponed",
    "closed": "Closed",
}
_CATEGORY_MAP = {
    "bug": "Bug report",
    "task": "Task",
    "feature": "Feature request",
    "support": "Support request",
    "plan": "Plan",
    "meta": "Plan",
}

# Module-level so DrupalCommentClient instances share what the API client fetched.
_notes_cache: Dict[Tuple[str, str], List[dict]] = {}


def parse_url(url: str) -> Optional[Tuple[str, str]]:
    """(project, iid) for a git.drupalcode.org work item/issue URL, else None."""
    m = _WORK_ITEM_URL.search(url or "")
    return (m.group(1).lower(), m.group(2)) if m else None


def _get(path: str, params: Optional[dict] = None) -> Optional[requests.Response]:
    headers = {"User-Agent": "IssueForge/1.0"}
    token = get_credentials().get("gitlab_token", "")
    if token:
        headers["PRIVATE-TOKEN"] = token
    backoff = 1
    for attempt in range(DRUPAL_API_RETRIES):
        try:
            resp = requests.get(f"{GITLAB_API_BASE}{path}", params=params,
                                headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 404:
                return None
            if resp.status_code in (429, 500, 502, 503):
                time.sleep(backoff)
                backoff *= 2
                continue
            logger.warning("GitLab API HTTP %d for %s", resp.status_code, path)
            return None
        except requests.RequestException as e:
            logger.warning("GitLab request error for %s: %s", path, e)
            if attempt < DRUPAL_API_RETRIES - 1:
                time.sleep(backoff)
                backoff *= 2
    return None


def _project_path(project: str) -> str:
    return quote(f"project/{project}", safe="")


def _unix(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _label_value(labels: List[str], scope: str) -> Optional[str]:
    for label in labels:
        if label.lower().startswith(scope + "::"):
            return label.split("::", 1)[1].strip()
    return None


def _version(labels: List[str], project: str) -> str:
    """Version label like "v1.3.x-dev" -> "1.3.x-dev"; else the default branch."""
    versions = [l[1:] for l in labels if re.match(r"^v\d", l)]
    dev = [v for v in versions if v.endswith("-dev")]
    if dev or versions:
        return (dev or versions)[0]
    resp = _get(f"/projects/{_project_path(project)}")
    branch = resp.json().get("default_branch") if resp else None
    return f"{branch}-dev" if branch else "main"


def issue_exists(project: str, iid: str) -> bool:
    return _get(f"/projects/{_project_path(project)}/issues/{iid}") is not None


def fetch_notes(project: str, iid: str) -> List[dict]:
    """All human (non-system) notes, oldest first. Needs the GitLab token."""
    key = (project, str(iid))
    if key in _notes_cache:
        return _notes_cache[key]
    notes, page = [], 1
    while page:
        resp = _get(
            f"/projects/{_project_path(project)}/issues/{iid}/notes",
            {"per_page": 100, "page": page, "sort": "asc", "order_by": "created_at"},
        )
        if resp is None:
            if page == 1:
                logger.warning("Could not read comments for %s#%s (GitLab token missing?)", project, iid)
            break
        notes += [n for n in resp.json() if not n.get("system")]
        page = int(resp.headers.get("x-next-page") or 0)
    _notes_cache[key] = notes
    return notes


def get_comment(comment_id: str) -> Optional[dict]:
    """Same shape as DrupalCommentClient.get_comment(), for a "gl:" id."""
    try:
        _, project, iid, note_id = comment_id.split(":", 3)
    except ValueError:
        return None
    for note in fetch_notes(project, iid):
        if str(note["id"]) == note_id:
            author = note.get("author") or {}
            return {
                "comment_id": comment_id,
                "author_id": author.get("id", ""),
                "author_name": author.get("username", ""),
                "created": _unix(note.get("created_at")),
                "body_html": note.get("body", ""),
            }
    return None


def get_issue(project: str, iid: str) -> Tuple[dict, dict]:
    """
    Returns (metadata, raw). metadata matches DrupalAPIClient.parse_issue_metadata()
    plus project_name/source/related_mr_urls; raw carries the created/changed
    unix timestamps the previewer reads.
    """
    path = f"/projects/{_project_path(project)}/issues/{iid}"
    resp = _get(path)
    if resp is None:
        raise ValueError(f"GitLab issue not found: project/{project} #{iid}")
    issue = resp.json()
    labels = issue.get("labels") or []

    state = _label_value(labels, "state")
    status = _STATE_MAP.get((state or "").replace(" ", "").lower(), state)
    if issue.get("state") == "closed" and status not in ("Fixed", "Closed"):
        status = "Closed"
    status = status or "Active"
    category = _label_value(labels, "category")
    priority = _label_value(labels, "priority")

    notes = fetch_notes(project, iid)
    mrs_resp = _get(f"{path}/related_merge_requests")
    mr_urls = [m.get("web_url", "") for m in (mrs_resp.json() if mrs_resp else [])]

    metadata = {
        "title": issue.get("title"),
        "status": status,
        "component": _label_value(labels, "component"),
        "version": _version(labels, project),
        "priority": priority.capitalize() if priority else None,
        "category": _CATEGORY_MAP.get((category or "").lower(), category),
        "problem_description_html": issue.get("description") or "",
        "patch_file_ids": [],  # GitLab work items take MRs, not drupal.org patch files
        "comment_ids": [f"{COMMENT_PREFIX}{project}:{iid}:{n['id']}" for n in notes],
        "issue_id": str(issue.get("iid", iid)),
        "issue_url": issue.get("web_url"),
        "project_name": project,
        "source": "gitlab",
        "related_mr_urls": [u for u in mr_urls if u],
    }
    raw = {
        "created": _unix(issue.get("created_at")),
        "changed": _unix(issue.get("updated_at")),
    }
    return metadata, raw
