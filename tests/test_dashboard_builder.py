"""Unit tests for DashboardBuilder."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.dashboard_builder import DashboardBuilder


class TestBuild:
    def test_injects_data_and_writes_beside_template(self, tmp_path):
        template = tmp_path / "template.html"
        template.write_text(
            '<html><body><link rel="stylesheet" href="dashboard.css">'
            "<!--DASHBOARD_DATA_SCRIPT-->"
            '<script src="dashboard.js"></script></body></html>'
        )
        output = tmp_path / "dashboard.html"
        ledger = {"issues": [{"issue_id": "1", "title": "A bug"}], "generated_at": "2026-07-17"}

        result_path = DashboardBuilder.build(ledger, str(template), str(output))

        assert result_path == str(output)
        html = output.read_text()
        assert "window.DASHBOARD_DATA" in html
        assert '"issue_id": "1"' in html
        assert 'href="dashboard.css"' in html  # sibling asset link untouched
        assert 'src="dashboard.js"' in html

    def test_missing_placeholder_raises(self, tmp_path):
        template = tmp_path / "template.html"
        template.write_text("<html><body>no placeholder here</body></html>")
        try:
            DashboardBuilder.build({"issues": []}, str(template), str(tmp_path / "out.html"))
            assert False, "expected ValueError"
        except ValueError as e:
            assert "placeholder" in str(e)

    def test_escapes_closing_script_tag_in_data(self, tmp_path):
        # Regression coverage: an issue title containing "</script>" (from
        # Drupal.org, external input) must not be able to prematurely close
        # the injected script block and corrupt the page.
        template = tmp_path / "template.html"
        template.write_text("<!--DASHBOARD_DATA_SCRIPT--><script src=\"dashboard.js\"></script>")
        output = tmp_path / "dashboard.html"
        malicious_title = "Bug</script><script>alert(1)</script>"
        ledger = {"issues": [{"issue_id": "1", "title": malicious_title}], "generated_at": None}

        DashboardBuilder.build(ledger, str(template), str(output))
        html = output.read_text()

        # The literal, unescaped closing tag must not appear inside our
        # injected data block.
        first_script_start = html.index("window.DASHBOARD_DATA")
        first_script_end = html.index("</script>", first_script_start)
        injected_segment = html[first_script_start:first_script_end]
        assert "</script>" not in injected_segment
        assert "<\\/script>" in injected_segment
