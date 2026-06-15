"""Unit tests for LlmAnalyzer — uses mocked LlmClient."""
import json
import pytest
import sys, os
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from classifiers.llm_analyzer import LlmAnalyzer

_VALID_RESPONSE = json.dumps({
    "subsystems": ["Form API", "Entity API"],
    "root_cause": "Fails to reject comma-separated input when #tags is FALSE.",
    "root_cause_signals": ["Form state or validation issue"],
    "fix_strategies": ["Add a check in validateEntityAutocomplete for multi-value input."],
    "risk_level": "low",
    "confidence": "high",
})


class TestAnalyze:
    def test_returns_structured_result_on_valid_llm_response(self):
        with patch("classifiers.llm_analyzer.LlmClient.generate", return_value=_VALID_RESPONSE):
            result = LlmAnalyzer.analyze("Test issue", "Problem.", [], [], [], [])
        assert result["subsystems"] == ["Form API", "Entity API"]
        assert result["confidence"] == "high"
        assert result["risk_level"] == "low"

    def test_fallback_on_empty_llm_response(self):
        with patch("classifiers.llm_analyzer.LlmClient.generate", return_value=""):
            result = LlmAnalyzer.analyze(
                "Test", "Problem.", [], [], ["Views"], ["Filter bug"]
            )
        # Should fall back to preliminary data
        assert result["subsystems"] == ["Views"]
        assert result["root_cause_signals"] == ["Filter bug"]
        assert result["confidence"] == "low"

    def test_fallback_on_invalid_json(self):
        with patch("classifiers.llm_analyzer.LlmClient.generate", return_value="not json"):
            result = LlmAnalyzer.analyze("Test", "", [], [], [], [])
        assert result["confidence"] == "low"

    def test_strips_markdown_fences(self):
        fenced = f"```json\n{_VALID_RESPONSE}\n```"
        with patch("classifiers.llm_analyzer.LlmClient.generate", return_value=fenced):
            result = LlmAnalyzer.analyze("Test", "", [], [], [], [])
        assert result["subsystems"] == ["Form API", "Entity API"]

    def test_partial_json_falls_back(self):
        # Missing required key "fix_strategies"
        partial = json.dumps({"subsystems": ["Views"], "root_cause": "x",
                              "root_cause_signals": ["y"]})
        with patch("classifiers.llm_analyzer.LlmClient.generate", return_value=partial):
            result = LlmAnalyzer.analyze("Test", "", [], [], ["Views"], [])
        assert result["confidence"] == "low"


class TestParseJson:
    def test_valid_json_parsed(self):
        data = LlmAnalyzer._parse_json(_VALID_RESPONSE)
        assert data["risk_level"] == "low"

    def test_json_embedded_in_text(self):
        wrapped = f"Here is the analysis:\n{_VALID_RESPONSE}\nDone."
        data = LlmAnalyzer._parse_json(wrapped)
        assert data["confidence"] == "high"

    def test_empty_string_returns_empty(self):
        assert LlmAnalyzer._parse_json("") == {}

    def test_missing_required_key_returns_empty(self):
        incomplete = json.dumps({"subsystems": ["Views"]})
        assert LlmAnalyzer._parse_json(incomplete) == {}
