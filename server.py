from services.drupal_api_client import DrupalAPIClient
from services.drupal_patch_client import DrupalPatchClient
from services.patch_analyzer import PatchAnalyzer
from services.reasoning_context_builder import ReasoningContextBuilder
from services.multi_patch_analyzer import MultiPatchAnalyzer
from services.drupal_comment_client import DrupalCommentClient
from classifiers.patch_status_classifier import PatchStatusClassifier

from classifiers.subsystem_detector import SubsystemDetector
from classifiers.root_cause_detector import RootCauseDetector
from classifiers.fix_strategy_generator import FixStrategyGenerator
from classifiers.comment_signal_detector import CommentSignalDetector


class IssueForgeServer:
    """
    Main orchestration engine for analyzing Drupal issues.
    """

    def __init__(self):
        self.api_client = DrupalAPIClient()
        self.patch_client = DrupalPatchClient()
        self.comment_client = DrupalCommentClient()

    def analyze_issue(self, issue_url: str):

        # Step 1: fetch metadata
        metadata = self.api_client.get_issue_metadata(issue_url)

        patch_ids = metadata.get("patch_file_ids", [])

        # Step 2: initialize empty patch analysis
        patch_analysis = {"modified_files": [], "modified_functions": []}

        # Step 3: analyze best patch if available
        if patch_ids:
            patch_analyzer = MultiPatchAnalyzer()

            patch_results = patch_analyzer.analyze_all_patches(patch_ids)

            patch_analysis = patch_analyzer.select_best_patch(patch_results)

        modified_files = patch_analysis["modified_files"]
        modified_functions = patch_analysis["modified_functions"]

        # Step 4: detect subsystem
        subsystem_result = SubsystemDetector.detect_from_paths(modified_files)

        detected_subsystems = subsystem_result["detected_subsystems"]

        # Step 5: detect root-cause signals
        root_cause_result = RootCauseDetector.detect(
            modified_functions, detected_subsystems
        )

        root_signals = root_cause_result["root_cause_signals"]

        # Step 6: generate fix strategies
        strategy_result = FixStrategyGenerator.generate(
            root_signals, modified_functions
        )

        # Step 7: extract comment intelligence
        comment_ids = metadata.get("comment_ids", [])

        comment_bodies = []

        if comment_ids:

            sample_ids = (
                comment_ids[:3]
                + comment_ids[len(comment_ids) // 2 : len(comment_ids) // 2 + 3]
                + comment_ids[-3:]
            )

        comments = self.comment_client.get_multiple_comments(sample_ids)

        comment_bodies = [c["body_html"] for c in comments if c.get("body_html")]

        comment_signal_result = CommentSignalDetector.detect(comment_bodies)

        # Step 8: classify patch lifecycle status
        patch_status = PatchStatusClassifier.classify(
            comment_signal_result.get("comment_signals", [])
        )

        # Step 9: build reasoning payload
        context = ReasoningContextBuilder.build(
            metadata,
            patch_analysis,
            subsystem_result,
            root_cause_result,
            strategy_result,
            comment_signal_result,
            patch_status,
        )

        return context
