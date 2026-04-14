from typing import List, Dict


class SubsystemDetector:
    """
    Detect Drupal subsystem from modified file paths.
    """

    SUBSYSTEM_RULES = {
        "views": "Views",
        "entity": "Entity API",
        "routing": "Routing",
        "plugin": "Plugin system",
        "render": "Render pipeline",
        "cache": "Cache API",
        "form": "Form API",
        "config": "Config API",
        "field": "Field API",
        "theme": "Theme layer",
        "migrate": "Migration system",
    }

    @staticmethod
    def detect_from_paths(file_paths: List[str]) -> Dict:
        detected = set()

        for path in file_paths:
            lower_path = path.lower()

            for keyword, subsystem in SubsystemDetector.SUBSYSTEM_RULES.items():
                if keyword in lower_path:
                    detected.add(subsystem)

        return {
            "detected_subsystems": list(detected),
            "confidence": "high" if detected else "low"
        }