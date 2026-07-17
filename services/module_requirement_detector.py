from typing import Dict, List

from services.contrib_module_detector import ContribModuleDetector


class ModuleRequirementDetector:
    """
    Aggregate module requirements from multiple detectors.
    """

    @staticmethod
    def is_contrib(module_name: str) -> bool:
        core_modules = {
            "action", "block", "block_content", "book", "breakpoint", "ckeditor", "ckeditor5",
            "color", "comment", "config", "config_translation", "contact", "content_moderation",
            "content_translation", "contextual", "datetime", "datetime_range", "dblog",
            "dynamic_page_cache", "editor", "entity_reference", "field", "field_layout",
            "field_ui", "file", "filter", "forum", "hal", "help", "help_topics", "image",
            "inline_form_errors", "jsonapi", "language", "layout_builder", "layout_discovery",
            "link", "locale", "media", "media_library", "menu_link_content", "menu_ui", "migrate",
            "migrate_drupal", "migrate_drupal_multilingual", "migrate_drupal_ui", "mysql", "node",
            "options", "page_cache", "path", "path_alias", "pg_sql", "quickedit", "rdf",
            "responsive_image", "rest", "search", "serialization", "settings_tray", "shortcut",
            "sqlite", "standard", "statistics", "syslog", "system", "taxonomy", "telephone",
            "text", "toolbar", "tour", "tracker", "update", "user", "views", "views_ui", "workflows"
        }
        return module_name.lower() not in core_modules

    @staticmethod
    def detect(metadata: Dict) -> List[str]:
        # Note: TestModuleDetector identifies mentions of testing
        # frameworks (PHPUnit, SimpleTest, etc.) for informational purposes
        # only. Those are never real, composer-requireable Drupal contrib
        # projects, so they must not be merged into the installable module
        # list — doing so would produce a bogus `composer require
        # drupal/phpunit` for any issue that simply discusses test results
        # in prose (which is most core issues).
        return sorted(ContribModuleDetector.detect(metadata))