import re
from typing import Dict, List
from services.text_normalizer import TextNormalizer


class ContribModuleDetector:
    """
    Detect contrib module dependencies from issue metadata.

    Priority order:
    1. Explicit `drupal.org/project/NAME` links in the issue body.
    2. `require drupal/NAME` / `composer require drupal/NAME` patterns.
    3. Keyword matching against an extended known-module list.

    This avoids the old approach of a 7-item hardcoded list that missed
    the vast majority of real contrib modules.
    """

    # Extended baseline list — covers the most common contrib modules that
    # appear in Drupal.org issues.  New entries should be added here as they
    # are encountered in production usage.
    KNOWN_MODULES = [
        # Media & content
        "paragraphs", "entity_reference_revisions", "media_library_theme_reset",
        # Field helpers
        "field_group", "field_formatter_class", "computed_field",
        # Layout
        "layout_paragraphs", "layout_builder_restrictions", "ds",
        # Views & display
        "views_bulk_operations", "views_infinite_scroll", "better_exposed_filters",
        "ajax_views",
        # Forms & input
        "webform", "conditional_fields", "chosen",
        # SEO & paths
        "pathauto", "redirect", "metatag", "simple_sitemap",
        # Utility
        "token", "ctools", "entity", "entity_browser",
        # Media
        "media", "inline_entity_form",
        # Commerce
        "commerce", "commerce_cart", "commerce_checkout",
        # Search
        "search_api", "search_api_solr", "facets",
        # Auth
        "login_emailusername", "tfa",
        # Translation
        "tmgmt", "lingotek",
        # Migrations
        "migrate_plus", "migrate_tools", "migrate_source_csv",
        # Dev & config
        "config_split", "environment_indicator", "features",
        # UI
        "gin", "adminimal_theme", "bootstrap", "radix",
        # Misc
        "rules", "flag", "votingapi", "rate", "node_access_rebuild",
    ]

    # Drupal core modules — never treat these as contrib.
    CORE_MODULES = {
        "node", "user", "block", "views", "field", "file", "image", "menu_link_content",
        "taxonomy", "comment", "contact", "forum", "aggregator", "ban", "book",
        "color", "config", "content_translation", "contextual", "datetime",
        "datetime_range", "dblog", "editor", "entity_reference", "filter",
        "help", "history", "inline_form_errors", "language", "layout_builder",
        "layout_discovery", "link", "locale", "media", "migrate", "migrate_drupal",
        "minimal", "module_filter", "options", "path", "path_alias", "quickedit",
        "rdf", "responsive_image", "rest", "search", "serialization", "shortcut",
        "standard", "statistics", "syslog", "system", "telephone", "text",
        "toolbar", "tour", "tracker", "update", "views_ui", "workspaces",
    }


    @staticmethod
    def detect(metadata: Dict) -> List[str]:
        """
        Return a deduplicated list of detected contrib module machine names.
        """
        combined_text = TextNormalizer.flatten([
            metadata.get("title"),
            metadata.get("component"),
            metadata.get("problem_description_html"),
            metadata.get("version"),
            metadata.get("tags"),
        ]).lower()

        found: set = set()

        blocked = ContribModuleDetector.CORE_MODULES

        # 1. Explicit drupal.org/project/NAME links (most reliable signal)
        for match in re.finditer(
            r"drupal\.org/project/([a-z0-9_]+)", combined_text
        ):
            name = match.group(1)
            if name not in blocked:
                found.add(name)

        # 2. Composer require patterns
        for match in re.finditer(
            r"(?:composer\s+require\s+)?drupal/([a-z0-9_]+)", combined_text
        ):
            name = match.group(1)
            if name not in blocked:
                found.add(name)

        # 3. Known-module keyword matching (word-boundary aware)
        for module in ContribModuleDetector.KNOWN_MODULES:
            if re.search(r"\b" + re.escape(module) + r"\b", combined_text):
                found.add(module)

        return sorted(found)
