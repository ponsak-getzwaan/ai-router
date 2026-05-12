"""Unit tests for the fast-path intent classifier.

Covers keyword matching, confidence thresholds, path tagging, and
the rule ordering when multiple patterns fire.
"""

from __future__ import annotations

from classifier.config import ClassifierConfig
from classifier.fast_path import classify_fast
from shared.models import ClassifierPath, IntentDomain


class TestCodeAssistance:
    def test_code_keyword_returns_code_assistance(self):
        result = classify_fast("debug this python function", threshold=0.0)
        assert result is not None
        assert result.intent == "code_assistance"

    def test_debug_keyword_maps_to_code_domain(self):
        result = classify_fast("I have a traceback error", threshold=0.0)
        assert result is not None
        assert result.domain == IntentDomain.CODE_ASSISTANCE

    def test_code_result_uses_fast_path(self):
        result = classify_fast("refactor this script", threshold=0.0)
        assert result is not None
        assert result.path == ClassifierPath.FAST


class TestSimpleTransactional:
    def test_transactional_keyword_returns_simple_transactional(self):
        result = classify_fast("what is the price of X", threshold=0.0)
        assert result is not None
        assert result.intent == "simple_transactional"

    def test_what_are_maps_to_transactional(self):
        result = classify_fast("what are the opening hours", threshold=0.0)
        assert result is not None
        assert result.domain == IntentDomain.SIMPLE_TRANSACTIONAL

    def test_cost_of_keyword_maps_to_transactional(self):
        result = classify_fast("cost of the subscription", threshold=0.0)
        assert result is not None
        assert result.intent == "simple_transactional"


class TestGeneralQA:
    def test_qa_keyword_returns_general_qa(self):
        result = classify_fast("explain how photosynthesis works", threshold=0.0)
        assert result is not None
        assert result.intent == "general_qa"

    def test_tell_me_maps_to_general_qa(self):
        result = classify_fast("tell me about the solar system", threshold=0.0)
        assert result is not None
        assert result.domain == IntentDomain.GENERAL_QA

    def test_can_you_maps_to_general_qa(self):
        result = classify_fast("can you summarise this text", threshold=0.0)
        assert result is not None
        assert result.intent == "general_qa"


class TestNoMatch:
    def test_no_keyword_returns_none(self):
        result = classify_fast("hello world", threshold=0.0)
        assert result is None

    def test_greeting_returns_none(self):
        result = classify_fast("hi there", threshold=0.0)
        assert result is None


class TestThreshold:
    def test_below_threshold_returns_none(self):
        # All rules have confidence <= 0.85, so threshold of 0.99 forces None
        result = classify_fast("debug this python function", threshold=0.99)
        assert result is None

    def test_at_threshold_returns_result(self):
        # code_assistance has confidence=0.85; threshold=0.85 should pass
        result = classify_fast("debug this python function", threshold=0.85)
        assert result is not None

    def test_default_config_threshold_applied(self):
        config = ClassifierConfig()
        # code_assistance confidence is 0.85, default threshold is 0.82 → should hit
        result = classify_fast("write a python script", threshold=config.fast_path_threshold)
        assert result is not None
        assert result.intent == "code_assistance"

    def test_general_qa_confidence_below_code_threshold(self):
        # general_qa has confidence=0.75; threshold=0.80 → miss
        result = classify_fast("explain gravity", threshold=0.80)
        assert result is None


class TestResultProperties:
    def test_resolved_message_equals_input(self):
        msg = "debug this python function"
        result = classify_fast(msg, threshold=0.0)
        assert result is not None
        assert result.resolved_message == msg

    def test_escalate_false_for_confident_code_result(self):
        # code_assistance confidence=0.85 >= 0.6 → escalate=False
        result = classify_fast("debug this python code", threshold=0.0)
        assert result is not None
        assert result.escalate is False

    def test_escalate_false_for_confident_transactional_result(self):
        # simple_transactional confidence=0.80 >= 0.6 → escalate=False
        result = classify_fast("what is the price", threshold=0.0)
        assert result is not None
        assert result.escalate is False


class TestRulePriority:
    def test_code_beats_qa_when_both_present(self):
        # "explain how to debug python code" hits both qa (explain) and code (debug, python, code)
        # code_assistance confidence=0.85 > general_qa confidence=0.75 → code wins
        result = classify_fast("explain how to debug python code", threshold=0.0)
        assert result is not None
        assert result.intent == "code_assistance"

    def test_best_confidence_wins_multi_match(self):
        # code (0.85) beats transactional (0.80) and qa (0.75)
        result = classify_fast("what is the best python script", threshold=0.0)
        assert result is not None
        # "python" hits code, "what is" hits transactional → code wins at 0.85
        assert result.intent == "code_assistance"
