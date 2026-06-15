"""
LLM-powered issue analyzer.

Replaces the three independent regex classifiers (SubsystemDetector,
RootCauseDetector, FixStrategyGenerator) with a single structured LLM call
that considers the full issue context together.

The regex classifiers are still used as a fast first-pass.  If their
confidence is high (≥ 2 subsystems found from file paths) we skip the LLM
call to save tokens.  Otherwise we use the LLM to fill the gaps.
"""

import json
import logging
import re
from typing import Dict, List

from services.llm_client import LlmClient

logger = logging.getLogger("IssueForge.LlmAnalyzer")

_ANALYSIS_SYSTEM_PROMPT = """You are a Drupal core and contrib expert.
Given information about a Drupal issue (title, description, modified files,
modified functions, and any preliminary signals), return a JSON object with
EXACTLY these keys:

{
  "subsystems": ["list of affected Drupal subsystems"],
  "root_cause": "one-sentence root cause description",
  "root_cause_signals": ["2-5 concise signal strings"],
  "fix_strategies": ["2-4 specific, actionable fix strategies"],
  "risk_level": "low|medium|high",
  "confidence": "low|medium|high"
}

Drupal subsystem vocabulary (use these exact names):
Form API, Entity API, Field API, Views, Render pipeline, Cache API,
Routing, Plugin system, Config API, Theme layer, Migration system,
Layout Builder, Media API, REST API, Queue API, Batch API, File API,
Menu system, Token API, State API, Language/Translation.

Rules:
- Return ONLY valid JSON — no markdown, no explanation outside the JSON.
- root_cause must be one sentence starting with a verb (e.g. "Fails to ...", "Ignores ...").
- fix_strategies must be specific — reference actual PHP classes or methods where possible.
- risk_level is "high" if the fix touches core caches, routing, or security.
"""


class LlmAnalyzer:
    """
    Single-call LLM analysis combining subsystem, root cause, and fix strategy.
    Falls back to the rule-based classifiers if the LLM fails or is unavailable.
    """

    @staticmethod
    def analyze(
        issue_title: str,
        problem_summary: str,
        modified_files: List[str],
        modified_functions: List[str],
        preliminary_subsystems: List[str],
        preliminary_root_cause_signals: List[str],
    ) -> Dict:
        """
        Returns a dict with keys:
          subsystems, root_cause, root_cause_signals, fix_strategies,
          risk_level, confidence.
        """
        user_prompt = f"""Analyze this Drupal issue:

**Title**: {issue_title}

**Problem**: {problem_summary or "Not provided."}

**Modified files** (from patch):
{chr(10).join(f"- {f}" for f in modified_files) or "- None"}

**Modified functions** (from patch):
{chr(10).join(f"- {f}" for f in modified_functions) or "- None"}

**Preliminary subsystems** (from file-path heuristics):
{chr(10).join(f"- {s}" for s in preliminary_subsystems) or "- None detected"}

**Preliminary root-cause signals** (from heuristics):
{chr(10).join(f"- {s}" for s in preliminary_root_cause_signals) or "- None detected"}

Return the JSON analysis object.
"""

        raw = LlmClient.generate(user_prompt, system=_ANALYSIS_SYSTEM_PROMPT)
        if not raw:
            logger.warning("LLM analyzer returned empty — falling back to heuristics.")
            return LlmAnalyzer._fallback(
                preliminary_subsystems, preliminary_root_cause_signals
            )

        result = LlmAnalyzer._parse_json(raw)
        if not result:
            logger.warning(
                "LLM analyzer returned unparseable JSON — falling back to heuristics."
            )
            return LlmAnalyzer._fallback(
                preliminary_subsystems, preliminary_root_cause_signals
            )

        logger.info(
            "LLM analysis complete. Confidence=%s, Risk=%s, Subsystems=%s",
            result.get("confidence"),
            result.get("risk_level"),
            result.get("subsystems"),
        )
        return result

    @staticmethod
    def _parse_json(raw: str) -> Dict:
        """Extract and validate the JSON block from the LLM response."""
        # Strip markdown fences if present
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

        # Find first { ... } block
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {}

        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

        required = {"subsystems", "root_cause", "root_cause_signals", "fix_strategies"}
        if not required.issubset(data.keys()):
            return {}

        return data

    @staticmethod
    def _fallback(
        preliminary_subsystems: List[str],
        preliminary_root_cause_signals: List[str],
    ) -> Dict:
        return {
            "subsystems": preliminary_subsystems,
            "root_cause": "Unable to determine root cause automatically.",
            "root_cause_signals": preliminary_root_cause_signals,
            "fix_strategies": [],
            "risk_level": "medium",
            "confidence": "low",
        }
