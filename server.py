from services.drupal_api_client import DrupalAPIClient
from services.reasoning_context_builder import ReasoningContextBuilder
from services.multi_patch_analyzer import MultiPatchAnalyzer
from services.drupal_comment_client import DrupalCommentClient
from services.environment_planner import EnvironmentPlanner
from services.ddev_script_generator import DdevScriptGenerator
from services.patch_apply_script_generator import PatchApplyScriptGenerator
from services.issue_description_parser import IssueDescriptionParser
from services.reproduction_script_generator import ReproductionScriptGenerator
from services.patch_branch_detector import PatchBranchDetector

from classifiers.diff_skeleton_generator import DiffSkeletonGenerator
from classifiers.subsystem_detector import SubsystemDetector
from classifiers.root_cause_detector import RootCauseDetector
from classifiers.fix_strategy_generator import FixStrategyGenerator
from classifiers.comment_signal_detector import CommentSignalDetector
from classifiers.patch_status_classifier import PatchStatusClassifier
from classifiers.patch_plan_generator import PatchPlanGenerator
from services.gitlab_mr_client import GitlabMrClient


class IssueForgeServer:
    """
    Main orchestration engine for analyzing Drupal issues.
    """

    def __init__(self, gitlab_token: str = ""):
        self.api_client = DrupalAPIClient()
        self.comment_client = DrupalCommentClient()
        self.mr_client = GitlabMrClient(token=gitlab_token)

    def analyze_issue(self, issue_url: str):

        # Step 1: fetch metadata
        metadata = self.api_client.get_issue_metadata(issue_url)

        patch_ids = metadata.get("patch_file_ids", [])

        # Step 2: initialize empty patch analysis
        patch_analysis = {
            "modified_files": [],
            "modified_functions": [],
            "filename": None,
        }

        # Step 3: analyze best patch if available
        patch_results = []
        if patch_ids:
            patch_analyzer = MultiPatchAnalyzer()
            patch_results = patch_analyzer.analyze_all_patches(patch_ids)
            patch_analysis = patch_analyzer.select_best_patch(patch_results)

        valid_patch_ids = [res["patch_id"] for res in patch_results]

        modified_files = patch_analysis["modified_files"]
        modified_functions = patch_analysis["modified_functions"]

        # Step 4: fast heuristic subsystem detection (file paths)
        subsystem_result = SubsystemDetector.detect_from_paths(modified_files)
        detected_subsystems = subsystem_result["detected_subsystems"]

        # Step 5: fast heuristic root-cause signals
        root_cause_result = RootCauseDetector.detect(
            modified_functions, detected_subsystems
        )
        root_signals = root_cause_result["root_cause_signals"]

        # Step 6: heuristic fix strategies
        # generate() expects (root_cause_signals, modified_functions) — passing
        # (detected_subsystems, root_signals) here meant neither list could ever
        # match STRATEGY_RULES (keyed by root-cause phrases) or
        # FUNCTION_STRATEGIES (keyed by function names), so fix_strategies was
        # unconditionally empty for every issue.
        strategy_result = FixStrategyGenerator.generate(
            root_signals, modified_functions
        )
        final_subsystems = detected_subsystems
        final_root_signals = root_signals
        final_fix_strategies = strategy_result.get("fix_strategies", [])

        # Step 7: extract comment intelligence.
        #
        # Scan up to ~30 comments: fetching costs network requests, not
        # tokens — only the ranked evidence that survives the byte budget is
        # ever emitted. A narrow 9-comment sample misses error reports that
        # sit mid-thread on long issues (e.g. comment #47 of 155).
        comment_ids = metadata.get("comment_ids", [])
        comment_bodies = []
        if comment_ids:
            if len(comment_ids) <= 30:
                sample_ids = list(comment_ids)
            else:
                first = comment_ids[:5]
                last = comment_ids[-10:]
                middle_pool = comment_ids[5:-10]
                step = max(1, len(middle_pool) // 15)
                middle = middle_pool[::step][:15]
                sample_ids = first + middle + last
            comments = self.comment_client.get_multiple_comments(sample_ids)
            comment_bodies = [
                c["body_html"] for c in comments if c.get("body_html")
            ]

        comment_signal_result = CommentSignalDetector.detect(
            comment_bodies, current_issue_id=metadata.get("issue_id")
        )

        # Step 7b: detect MRs — goes through the shared detector so preview
        # and analyze always agree on the same issue (see GitlabMrClient.
        # detect_mrs_for_issue for why this can't reuse the small sample
        # above: it scans its own, larger, recency-based comment window).
        unique_mrs = self.mr_client.detect_mrs_for_issue(metadata, self.comment_client)
        detected_mrs = unique_mrs

        # Step 8: classify patch lifecycle status
        patch_status = PatchStatusClassifier.classify(
            comment_signal_result.get("comment_signals", [])
        )

        # Step 9: generate patch edit plan
        patch_plan = PatchPlanGenerator.build_plan(
            modified_files,
            modified_functions,
            final_subsystems,
            final_root_signals,
        )

        diff_skeleton = DiffSkeletonGenerator.generate(patch_plan)

        # Step 10: environment planning
        env_plan = EnvironmentPlanner.plan(metadata, modified_files, valid_patch_ids)

        ddev_script = DdevScriptGenerator.generate(env_plan)

        patch_apply_script = None
        if env_plan.get("patch_available"):
            patch_apply_script = PatchApplyScriptGenerator.generate(
                env_plan.get("latest_patch_id")
            )

        # Step 11: extract reproduction steps
        description_sections = IssueDescriptionParser.extract_sections(
            metadata.get("problem_description_html", "")
        )
        reproduction_steps = description_sections.get("steps", [])

        # Step 12: build reasoning payload
        context = ReasoningContextBuilder.build(
            metadata,
            patch_analysis,
            subsystem_result,
            root_cause_result,
            strategy_result,
            comment_signal_result,
            patch_status,
        )

        # Step 13: heuristic reproduction script from parsed steps
        reproduction_script = ReproductionScriptGenerator.generate(
            reproduction_steps
        )

        # Check patch branch compatibility
        patch_filename = patch_analysis.get("filename")
        checkout_ref = env_plan.get("checkout_ref", "11.x")
        compatibility_result = PatchBranchDetector.check_compatibility(
            patch_filename, modified_files, checkout_ref
        )

        # Step 14: attach extended automation outputs
        context["patch_plan"] = patch_plan
        context["diff_skeleton"] = diff_skeleton
        context["environment_plan"] = env_plan
        context["ddev_script"] = ddev_script
        context["patch_apply_script"] = patch_apply_script
        context["patch_compatibility"] = compatibility_result
        context["reproduction_steps"] = reproduction_steps
        context["reproduction_script"] = reproduction_script
        context["detected_mrs"] = detected_mrs

        # Evidence bundle — the primary input for root-cause reasoning by
        # the model driving the skill. The heuristic classifiers above are
        # keyword lookups and are surfaced only as hints.
        best_patch_id = patch_analysis.get("patch_id")
        diff_text = ""
        if best_patch_id:
            import os
            diff_path = f"temp_patch_{best_patch_id}.diff"
            if os.path.exists(diff_path):
                try:
                    with open(diff_path, errors="ignore") as f:
                        diff_text = f.read()
                except OSError:
                    pass
        from services.evidence_extractor import EvidenceExtractor
        context["evidence"] = EvidenceExtractor.build(
            metadata, comment_bodies, diff_text
        )

        # Keyword-lookup output — hints only, never conclusions. Kept under
        # the legacy "llm_analysis" key too so skill snapshots installed
        # before the rename keep working.
        context["heuristic_hints"] = {
            # RootCauseDetector.detect() returns "root_cause_signals" (a
            # list), never a "root_cause" key — reading .get("root_cause")
            # here always silently returned "" regardless of what was
            # actually detected. Join the real signals into a readable
            # summary instead.
            "root_cause": "; ".join(final_root_signals),
            # FixStrategyGenerator.generate() never returns a "risk_level" key
            # (only "fix_strategies" and "confidence"); the real risk_level is
            # computed by PatchPlanGenerator.build_plan() above, so read it
            # from there instead of an always-missing key that silently fell
            # back to a hardcoded "medium" regardless of the actual patch.
            "risk_level": patch_plan.get("risk_level", "medium"),
            "confidence": root_cause_result.get("confidence", "medium"),
        }
        context["llm_analysis"] = context["heuristic_hints"]

        return context
