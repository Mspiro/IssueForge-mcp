"""
Dashboard builder — assembles dashboard/dashboard.html from
dashboard/template.html + the current ledger data.

dashboard.css and dashboard.js stay real, separate, linked files (a local
file:// page loads sibling <link>/<script src> files fine); only the ledger
DATA is injected inline, since file:// pages generally can't fetch() a
sibling JSON file due to browser CORS restrictions on that scheme.
"""

import json
import os

from services.dashboard_ledger import DASHBOARD_DIR

TEMPLATE_PATH = os.path.join(DASHBOARD_DIR, "template.html")
OUTPUT_PATH = os.path.join(DASHBOARD_DIR, "dashboard.html")

_PLACEHOLDER = "<!--DASHBOARD_DATA_SCRIPT-->"


class DashboardBuilder:

    @staticmethod
    def build(ledger_data: dict, template_path: str = TEMPLATE_PATH,
              output_path: str = OUTPUT_PATH) -> str:
        """
        Render dashboard.html into the same folder as template.html/
        dashboard.css/dashboard.js, so its relative asset links resolve.
        Returns the output path.
        """
        with open(template_path) as f:
            template = f.read()

        if _PLACEHOLDER not in template:
            raise ValueError(
                f"template.html is missing the {_PLACEHOLDER} placeholder"
            )

        data_json = json.dumps(ledger_data, indent=None)
        # Escape "</" so a value containing e.g. an issue title with
        # "</script>" in it can't prematurely close this script block and
        # corrupt the page (Drupal.org issue titles are external input).
        data_json = data_json.replace("</", "<\\/")
        script_tag = f'<script>window.DASHBOARD_DATA = {data_json};</script>'
        html = template.replace(_PLACEHOLDER, script_tag)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write(html)
        return output_path
