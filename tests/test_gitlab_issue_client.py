"""GitLab work-item issues and routing between drupal.org and GitLab. No network."""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services import gitlab_issue_client as gl
from services.drupal_api_client import DrupalAPIClient
from services.drupal_comment_client import DrupalCommentClient
from services.gitlab_mr_client import GitlabMrClient
from services.credit_tracker import _NODE_ID_PATTERN

_ISSUE = {
    "iid": 3586849,
    "title": "AiCKEditor module uninstall failed",
    "state": "opened",
    "labels": ["Novice", "category::bug", "priority::normal", "state::needsWork", "v1.3.x-dev"],
    "description": "Steps to reproduce",
    "created_at": "2026-11-06T09:02:29.724Z",
    "updated_at": "2026-11-06T10:23:13.054Z",
    "web_url": "https://git.drupalcode.org/project/ai/-/work_items/3586849",
}
_NOTES = [
    {"id": 1, "system": True, "body": "set status", "author": {"username": "bot"},
     "created_at": "2026-11-06T09:02:29Z"},
    {"id": 2, "system": False, "body": "Confirmed on 1.x", "author": {"id": 7, "username": "jane"},
     "created_at": "2026-11-06T10:00:00Z"},
]
_MRS = [{"web_url": "https://git.drupalcode.org/project/ai/-/merge_requests/2173"}]


def _resp(payload, headers=None):
    r = MagicMock()
    r.json.return_value = payload
    r.headers = headers or {}
    return r


def _fake_get(path, params=None):
    if path.endswith("/notes"):
        return _resp(_NOTES)
    if path.endswith("/related_merge_requests"):
        return _resp(_MRS)
    if path.endswith("/issues/3586849"):
        return _resp(_ISSUE)
    if path == "/projects/project%2Fai":
        return _resp({"default_branch": "1.x"})
    return None


@pytest.fixture(autouse=True)
def _gitlab(monkeypatch):
    gl._notes_cache.clear()
    monkeypatch.setattr(gl, "_get", MagicMock(side_effect=_fake_get))


class TestParseUrl:
    @pytest.mark.parametrize("url", [
        "https://git.drupalcode.org/project/ai/-/work_items/3586849",
        "https://git.drupalcode.org/project/ai/-/issues/3586849",
    ])
    def test_work_item_urls(self, url):
        assert gl.parse_url(url) == ("ai", "3586849")

    def test_drupal_org_url_is_not_gitlab(self):
        assert gl.parse_url("https://www.drupal.org/project/ai/issues/3586849") is None


class TestGetIssue:
    def test_maps_labels_to_drupal_fields(self):
        meta, raw = gl.get_issue("ai", "3586849")
        assert meta["status"] == "Needs work"
        assert meta["category"] == "Bug report"
        assert meta["priority"] == "Normal"
        assert meta["version"] == "1.3.x-dev"
        assert meta["project_name"] == "ai"
        assert meta["source"] == "gitlab"
        assert meta["patch_file_ids"] == []
        assert meta["related_mr_urls"] == [_MRS[0]["web_url"]]
        assert raw["created"] == 1793955749  # 2026-11-06T09:02:29Z

    def test_system_notes_are_skipped(self):
        meta, _ = gl.get_issue("ai", "3586849")
        assert meta["comment_ids"] == ["gl:ai:3586849:2"]

    def test_no_version_label_uses_default_branch(self, monkeypatch):
        monkeypatch.setitem(_ISSUE, "labels", ["state::accepted"])
        meta, _ = gl.get_issue("ai", "3586849")
        assert meta["version"] == "1.x-dev"
        assert meta["status"] == "Active"

    def test_missing_issue_raises(self):
        with pytest.raises(ValueError):
            gl.get_issue("ai", "1")


class TestCommentClient:
    def test_gitlab_comment_shape(self):
        c = DrupalCommentClient().get_comment("gl:ai:3586849:2")
        assert c["comment_id"] == "gl:ai:3586849:2"
        assert c["author_name"] == "jane"
        assert c["body_html"] == "Confirmed on 1.x"
        assert isinstance(c["created"], int)


class TestRouting:
    def _client(self, node_json):
        api = DrupalAPIClient()
        api.safe_request = MagicMock(return_value=node_json)
        return api

    def test_gitlab_url_goes_to_gitlab(self):
        api = self._client({})
        meta = api.get_issue_metadata(_ISSUE["web_url"])
        assert meta["source"] == "gitlab"
        api.safe_request.assert_not_called()
        assert api.fetch_issue_data("3586849")["changed"] is not None

    def test_moved_issue_follows_new_url(self):
        api = self._client({"new_url": _ISSUE["web_url"]})
        meta = api.get_issue_metadata("https://www.drupal.org/project/ai/issues/3586849")
        assert meta["source"] == "gitlab"

    def test_colliding_non_issue_node_uses_url_project(self):
        api = self._client({"type": "project_release", "title": "fullcalendar 4.0.x-dev"})
        meta = api.get_issue_metadata("https://www.drupal.org/project/ai/issues/3586849")
        assert meta["title"] == _ISSUE["title"]

    def test_colliding_non_issue_node_without_project_errors(self):
        api = self._client({"type": "project_release"})
        with pytest.raises(ValueError, match="not a drupal.org issue"):
            api.get_issue_metadata("https://www.drupal.org/node/3586849")

    def test_drupal_org_issue_unchanged(self):
        node = {"type": "project_issue", "nid": "3587797", "title": "Core issue",
                "field_issue_status": "8", "field_project": {"machine_name": "drupal"},
                "url": "https://www.drupal.org/project/drupal/issues/3587797"}
        api = self._client(node)
        meta = api.get_issue_metadata("https://www.drupal.org/project/drupal/issues/3587797")
        assert meta["source"] == "drupal.org"
        assert meta["status"] == "Needs work"
        assert meta["project_name"] == "drupal"
        gl._get.assert_not_called()

    def test_node_url_takes_project_from_node(self):
        node = {"type": "project_issue", "nid": "3636958", "title": "Webform issue",
                "field_project": {"machine_name": "webform"}}
        meta = self._client(node).get_issue_metadata("https://www.drupal.org/node/3636958")
        assert meta["project_name"] == "webform"


class TestMrAndCredit:
    def test_related_mrs_are_detected(self):
        meta = {"problem_description_html": "", "comment_ids": [],
                "related_mr_urls": [_MRS[0]["web_url"]]}
        mrs = GitlabMrClient().detect_mrs_for_issue(meta, MagicMock())
        assert [(m["project"], m["mr_iid"]) for m in mrs] == [("ai", "2173")]

    @pytest.mark.parametrize("uri,nid", [
        ("https://www.drupal.org/node/3284429", "3284429"),
        ("https://git.drupalcode.org/project/ai/-/work_items/3543368", "3543368"),
    ])
    def test_credit_record_links(self, uri, nid):
        assert _NODE_ID_PATTERN.search(uri).group(1) == nid
