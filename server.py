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


class IssueForgeServer:
    """
    Main orchestration engine for analyzing Drupal issues.
    """

    def __init__(self):
        self.api_client = DrupalAPIClient()
        self.comment_client = DrupalCommentClient()

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

            patch_results = patch_analyzer.analyze_all_patches(
                patch_ids
            )

            patch_analysis = patch_analyzer.select_best_patch(
                patch_results
            )

        valid_patch_ids = [res["patch_id"] for res in patch_results]

        modified_files = patch_analysis["modified_files"]
        modified_functions = patch_analysis["modified_functions"]

        # Step 4: detect subsystem
        subsystem_result = SubsystemDetector.detect_from_paths(
            modified_files
        )

        detected_subsystems = subsystem_result["detected_subsystems"]

        # Step 5: detect root-cause signals
        root_cause_result = RootCauseDetector.detect(
            modified_functions,
            detected_subsystems
        )

        root_signals = root_cause_result["root_cause_signals"]

        # Step 6: generate fix strategies
        strategy_result = FixStrategyGenerator.generate(
            root_signals,
            modified_functions
        )

        # Step 7: extract comment intelligence
        comment_ids = metadata.get("comment_ids", [])

        comment_bodies = []

        if comment_ids:

            sample_ids = (
                comment_ids[:3]
                + comment_ids[len(comment_ids)//2:
                              len(comment_ids)//2 + 3]
                + comment_ids[-3:]
            )

            comments = self.comment_client.get_multiple_comments(
                sample_ids
            )

            comment_bodies = [
                c["body_html"]
                for c in comments
                if c.get("body_html")
            ]

        comment_signal_result = CommentSignalDetector.detect(
            comment_bodies
        )

        # Step 8: classify patch lifecycle status
        patch_status = PatchStatusClassifier.classify(
            comment_signal_result.get("comment_signals", [])
        )

        # Step 9: generate patch edit plan
        patch_plan = PatchPlanGenerator.build_plan(
            modified_files,
            modified_functions,
            detected_subsystems,
            root_signals
        )

        diff_skeleton = DiffSkeletonGenerator.generate(
            patch_plan
        )

        # Step 10: environment planning
        env_plan = EnvironmentPlanner.plan(
            metadata,
            modified_files,
            valid_patch_ids
        )

        ddev_script = DdevScriptGenerator.generate(
            env_plan
        )

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

        # Step 13: dynamic LLM reproduction script generation
        from services.reproduction_generator_llm import ReproductionGeneratorLlm
        reproduction_script = ReproductionGeneratorLlm.generate_script(
            issue_title=context.get("issue_title", ""),
            problem_summary=context.get("problem_summary", ""),
            reproduction_steps=reproduction_steps,
            detected_subsystems=context.get("detected_subsystems", []),
            modified_files=context.get("modified_files", []),
        )

        if not reproduction_script:
            # Fallback to simple echo script
            reproduction_script = ReproductionScriptGenerator.generate(
                reproduction_steps
            )

        # Check patch branch compatibility
        patch_filename = patch_analysis.get("filename")
        checkout_ref = env_plan.get("checkout_ref", "11.x")
        compatibility_result = PatchBranchDetector.check_compatibility(
            patch_filename,
            modified_files,
            checkout_ref
        )

        # Step 14: attach extended automation outputs
        context["patch_plan"] = patch_plan
        context["diff_skeleton"] = diff_skeleton
        context["environment_plan"] = env_plan
        context["ddev_script"] = ddev_script
        context["patch_apply_script"] = patch_apply_script
        context["patch_compatibility"] = compatibility_result

        # NEW: attach reproduction pipeline outputs
        context["reproduction_steps"] = reproduction_steps
        context["reproduction_script"] = reproduction_script

        return context