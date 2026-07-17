"""
IssuePreviewer — lightweight first look at a Drupal.org issue.

Fetches metadata, patches list, detected MRs, and an LLM-generated
discussion summary without provisioning any environment or downloading
patch files.
"""

import html
import re
from datetime import datetime

from services.drupal_api_client import DrupalAPIClient
from services.drupal_comment_client import DrupalCommentClient
from services.drupal_patch_client import DrupalPatchClient
from services.gitlab_mr_client import GitlabMrClient


class IssuePreviewer:

    @staticmethod
    def fetch_preview(issue_url: str, gitlab_token: str = "") -> dict:
        api = DrupalAPIClient()
        comment_client = DrupalCommentClient()
        patch_client = DrupalPatchClient()
        mr_client = GitlabMrClient(token=gitlab_token)

        # --- Metadata ---
        meta = api.get_issue_metadata(issue_url)
        raw = api.fetch_issue_data(meta["issue_id"])  # cache hit

        created_ts = raw.get("created")
        changed_ts = raw.get("changed")
        created_str = (
            datetime.fromtimestamp(int(created_ts)).strftime("%Y-%m-%d")
            if created_ts else ""
        )
        updated_str = (
            datetime.fromtimestamp(int(changed_ts)).strftime("%Y-%m-%d")
            if changed_ts else ""
        )
        total_comments = len(meta.get("comment_ids", []))

        # --- Patch list (metadata only, no download) ---
        patches = []
        for fid in meta.get("patch_file_ids", []):
            try:
                fm = patch_client.get_patch_metadata(fid)
                patches.append({
                    "id": fid,
                    "filename": fm.get("filename") or fm.get("name", f"patch-{fid}"),
                    "size": int(fm.get("size") or fm.get("filesize") or 0),
                    "url": fm.get("url", ""),
                })
            except Exception:
                patches.append({"id": fid, "filename": f"patch-{fid}", "size": 0, "url": ""})

        # --- Comments — fetch recent + sample for MR detection ---
        comment_ids = meta.get("comment_ids", [])
        recent_comments = []
        comment_bodies = []
        if comment_ids:
            n = len(comment_ids)
            mid = n // 2
            sample = list(dict.fromkeys(
                comment_ids[:3]
                + comment_ids[max(0, mid - 2):mid + 2]
                + comment_ids[-5:]
            ))
            all_fetched = comment_client.get_multiple_comments(sample)
            comment_bodies = [c["body_html"] for c in all_fetched if c.get("body_html")]

            # Build plain-text recent comments (last 3)
            last_ids = comment_ids[-3:]
            last_fetched = [c for c in all_fetched if c.get("comment_id") in last_ids]
            # If some weren't in the sample, fetch them separately
            fetched_ids = {c.get("comment_id") for c in all_fetched}
            missing = [i for i in last_ids if i not in fetched_ids]
            if missing:
                last_fetched += comment_client.get_multiple_comments(missing)
            last_fetched.sort(key=lambda c: last_ids.index(c["comment_id"])
                              if c.get("comment_id") in last_ids else 999)
            for c in last_fetched[-3:]:
                raw_body = c.get("body_html", "")
                text = re.sub(r"<[^>]+>", " ", raw_body)
                text = html.unescape(text).strip()
                text = re.sub(r"\s+", " ", text)
                if text:
                    ts = c.get("created")
                    date = (datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
                            if ts else "")
                    recent_comments.append({"date": date, "text": text[:600]})

        # --- MR detection ---
        # Goes through the shared detector (same one analyze_issue uses) so
        # preview and analyze always agree for the same issue — it owns its
        # own comment window rather than reusing the smaller sample above,
        # which was too narrow to reliably catch MR mentions in long threads.
        unique_mrs = mr_client.detect_mrs_for_issue(meta, comment_client)

        # Enrich MR entries with GitLab metadata when token is available
        if gitlab_token:
            for mr in unique_mrs:
                details = mr_client.get_mr_details(mr["project"], mr["mr_iid"]) or {}
                mr.update({
                    "title": details.get("title", ""),
                    "state": details.get("state", ""),
                    "target_branch": details.get("target_branch", ""),
                })

        return {
            "issue_id": meta["issue_id"],
            "issue_url": meta.get("issue_url", issue_url),
            "title": meta["title"],
            "status": meta["status"],
            "priority": meta["priority"],
            "category": meta["category"],
            "component": meta["component"],
            "version": meta["version"],
            "project": meta.get("project_name", "drupal"),
            "created": created_str,
            "updated": updated_str,
            "total_comments": total_comments,
            "patches": patches,
            "detected_mrs": unique_mrs,
            "recent_comments": recent_comments,
        }

    @staticmethod
    def format_analysis_summary(plan: dict) -> str:
        """Human-readable summary of a completed env_plan.json analysis."""
        W = 65
        sep = "-" * W
        ep = plan.get("environment_plan", {})
        la = plan.get("llm_analysis", {})
        lines = [
            "",
            sep,
            "  Analysis complete",
            sep,
            f"  Issue       : {plan.get('issue_title', '(unknown)')}",
            f"  Branch      : {ep.get('checkout_ref', '?')}   PHP: {ep.get('php_version', '?')}",
            f"  Project     : {ep.get('project_name', 'drupal')}  ({'contrib' if ep.get('is_contrib') else 'core'})",
            "",
        ]

        # Modules
        contrib = ep.get("contrib_modules", [])
        required = ep.get("required_modules", [])
        if contrib:
            lines.append(f"  Contrib modules to install : {', '.join(contrib)}")
        if required:
            lines.append(f"  All required modules       : {', '.join(required)}")
        lines.append("")

        # Patches
        latest = ep.get("latest_patch_id")
        if latest:
            lines.append(f"  Latest patch ID : {latest}")
        else:
            lines.append("  Patches         : none uploaded")

        # MRs
        mrs = plan.get("detected_mrs", [])
        if mrs:
            lines.append(f"  Detected MRs    : {len(mrs)}")
            for mr in mrs:
                title = mr.get("title") or mr.get("url", "")
                lines.append(f"    !{mr['mr_iid']} [{mr.get('state','?')}] {title}")
        lines.append("")

        # LLM analysis
        root_cause = la.get("root_cause", "").strip()
        if root_cause:
            lines.append(f"  Root cause   : {root_cause}")
        subsystems = plan.get("detected_subsystems", [])
        if subsystems:
            lines.append(f"  Subsystems   : {', '.join(subsystems)}")
        strategies = plan.get("suggested_fix_strategies", [])
        if strategies:
            lines.append(f"  Fix approach : {strategies[0]}")
        risk = la.get("risk_level", "")
        conf = la.get("confidence", "")
        if risk:
            lines.append(f"  Risk level   : {risk}   confidence: {conf}")
        lines.append("")

        # Reproduction steps
        steps = plan.get("reproduction_steps", [])
        if steps:
            lines.append("  Reproduction steps:")
            for i, step in enumerate(steps[:5], 1):
                lines.append(f"    {i}. {step[:120]}")
            if len(steps) > 5:
                lines.append(f"    … and {len(steps) - 5} more")
        lines.append(sep)

        return "\n".join(lines)

    @staticmethod
    def format_report(preview: dict) -> str:
        W = 65
        sep = "=" * W
        lines = [
            sep,
            f"  Issue #{preview['issue_id']}  —  {preview['project'].upper()}",
            sep,
            f"  Title     : {preview['title']}",
            f"  Status    : {preview['status']}",
            f"  Priority  : {preview['priority']}",
            f"  Category  : {preview['category']}",
            f"  Component : {preview['component']}",
            f"  Version   : {preview['version']}",
            f"  Created   : {preview['created']}    Updated: {preview['updated']}",
            f"  Comments  : {preview['total_comments']}",
            f"  URL       : {preview['issue_url']}",
            "",
        ]

        patches = preview.get("patches", [])
        lines.append(f"  Patches ({len(patches)} uploaded):")
        if patches:
            for p in patches:
                size_kb = p["size"] // 1024 if p.get("size") else 0
                lines.append(f"    [{p['id']}]  {p['filename']}  ({size_kb} KB)")
        else:
            lines.append("    None uploaded")
        lines.append("")

        mrs = preview.get("detected_mrs", [])
        lines.append(f"  Merge Requests ({len(mrs)} detected):")
        if mrs:
            for mr in mrs:
                title = mr.get("title") or "(title not fetched — provide GitLab token)"
                state = mr.get("state") or "unknown"
                branch = mr.get("target_branch") or ""
                target = f" → {branch}" if branch else ""
                lines.append(f"    !{mr['mr_iid']}  [{state}]  {title}{target}")
                lines.append(f"          {mr['url']}")
        else:
            lines.append("    None detected")
        lines.append("")

        lines.append(sep)

        # Output recent comments as a separate block for Claude to interpret
        recent = preview.get("recent_comments", [])
        if recent:
            lines.append("")
            lines.append("RECENT_COMMENTS:")
            for c in recent:
                date = c.get("date", "")
                lines.append(f"[{date}] {c['text']}")

        return "\n".join(lines)
