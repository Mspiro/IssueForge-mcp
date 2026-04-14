from typing import Dict

from services.issue_description_parser import IssueDescriptionParser


class ReasoningContextBuilder:
    """
    Build a unified reasoning payload from issue metadata,
    parsed description, patch analysis, subsystem detection,
    root-cause signals, fix strategies, and comment signals.
    """

    @staticmethod
    def build(
        metadata: Dict,
        patch_analysis: Dict,
        subsystem_result: Dict,
        root_cause_result: Dict,
        strategy_result: Dict,
        comment_signal_result: Dict,
        patch_status: Dict,
    ) -> Dict:

        description_sections = IssueDescriptionParser.extract_sections(
            metadata.get("problem_description_html", "")
        )

        return {
            "issue_title": metadata.get("title"),
            "component": metadata.get("component"),
            "version": metadata.get("version"),
            "problem_summary": description_sections.get("problem"),
            "expected_behavior": description_sections.get("expected"),
            "actual_behavior": description_sections.get("actual"),
            "proposed_resolution": description_sections.get("proposed_resolution"),
            "modified_files": patch_analysis.get("modified_files"),
            "modified_functions": patch_analysis.get("modified_functions"),
            "detected_subsystems": subsystem_result.get("detected_subsystems"),
            "root_cause_signals": root_cause_result.get("root_cause_signals"),
            "suggested_fix_strategies": strategy_result.get("fix_strategies"),
            "comment_signals": comment_signal_result.get("comment_signals"),
            "patch_status": patch_status,
        }
