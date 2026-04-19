"""Tests for email analysis JSON schema validation (analysis_schema.py).

Covers: required fields, enum constraints, text length limits,
placeholder brackets, and type enforcement.
"""

from __future__ import annotations

import unittest

from mail_agent.analysis_schema import MAX_CLOSING_LEN, MAX_GREETING_LEN, MAX_PARAGRAPH_LEN, validate_model_json


def _valid_parsed() -> dict:
    return {
        "category": "normal",
        "urgency": "medium",
        "action": "reply",
        "greeting": "Hello,",
        "body_paragraphs": [
            "Thank you for your message regarding the project.",
            "I would be happy to discuss the details at a meeting.",
        ],
        "closing_phrase": "Best regards",
    }


class ValidOutputTests(unittest.TestCase):
    def test_valid_output_passes(self) -> None:
        ok, reason = validate_model_json(_valid_parsed())
        assert ok is True
        assert reason == ""

    def test_three_paragraphs_valid(self) -> None:
        parsed = _valid_parsed()
        parsed["body_paragraphs"].append("Trzeci akapit.")
        ok, _ = validate_model_json(parsed)
        assert ok is True


class MissingFieldTests(unittest.TestCase):
    def test_missing_category(self) -> None:
        parsed = _valid_parsed()
        del parsed["category"]
        ok, reason = validate_model_json(parsed)
        assert ok is False
        assert "category" in reason

    def test_missing_greeting(self) -> None:
        parsed = _valid_parsed()
        del parsed["greeting"]
        ok, reason = validate_model_json(parsed)
        assert ok is False
        assert "greeting" in reason

    def test_missing_body_paragraphs(self) -> None:
        parsed = _valid_parsed()
        del parsed["body_paragraphs"]
        ok, reason = validate_model_json(parsed)
        assert ok is False
        assert "body_paragraphs" in reason


class EnumConstraintTests(unittest.TestCase):
    def test_invalid_category(self) -> None:
        parsed = _valid_parsed()
        parsed["category"] = "critical"
        ok, _ = validate_model_json(parsed)
        assert ok is False

    def test_invalid_urgency(self) -> None:
        parsed = _valid_parsed()
        parsed["urgency"] = "extreme"
        ok, _ = validate_model_json(parsed)
        assert ok is False

    def test_invalid_action(self) -> None:
        parsed = _valid_parsed()
        parsed["action"] = "delete"
        ok, _ = validate_model_json(parsed)
        assert ok is False

    def test_all_valid_categories(self) -> None:
        for cat in ("urgent", "normal", "spam"):
            parsed = _valid_parsed()
            parsed["category"] = cat
            ok, _ = validate_model_json(parsed)
            assert ok is True, f"category={cat} should be valid"

    def test_all_valid_actions(self) -> None:
        for action in ("reply", "forward", "ignore", "mark_read"):
            parsed = _valid_parsed()
            parsed["action"] = action
            ok, _ = validate_model_json(parsed)
            assert ok is True, f"action={action} should be valid"


class TextLimitTests(unittest.TestCase):
    def test_greeting_too_long(self) -> None:
        parsed = _valid_parsed()
        parsed["greeting"] = "A" * (MAX_GREETING_LEN + 1)
        ok, _ = validate_model_json(parsed)
        assert ok is False

    def test_greeting_at_limit(self) -> None:
        parsed = _valid_parsed()
        parsed["greeting"] = "A" * MAX_GREETING_LEN
        ok, _ = validate_model_json(parsed)
        assert ok is True

    def test_closing_too_long(self) -> None:
        parsed = _valid_parsed()
        parsed["closing_phrase"] = "B" * (MAX_CLOSING_LEN + 1)
        ok, _ = validate_model_json(parsed)
        assert ok is False

    def test_paragraph_too_long(self) -> None:
        parsed = _valid_parsed()
        parsed["body_paragraphs"][0] = "C" * (MAX_PARAGRAPH_LEN + 1)
        ok, _ = validate_model_json(parsed)
        assert ok is False

    def test_empty_greeting_rejected(self) -> None:
        parsed = _valid_parsed()
        parsed["greeting"] = "   "
        ok, _ = validate_model_json(parsed)
        assert ok is False

    def test_empty_closing_rejected(self) -> None:
        parsed = _valid_parsed()
        parsed["closing_phrase"] = ""
        ok, _ = validate_model_json(parsed)
        assert ok is False


class ParagraphCountTests(unittest.TestCase):
    def test_one_paragraph_rejected(self) -> None:
        parsed = _valid_parsed()
        parsed["body_paragraphs"] = ["Only one."]
        ok, _ = validate_model_json(parsed)
        assert ok is False

    def test_four_paragraphs_rejected(self) -> None:
        parsed = _valid_parsed()
        parsed["body_paragraphs"] = ["One.", "Two.", "Three.", "Four."]
        ok, _ = validate_model_json(parsed)
        assert ok is False

    def test_empty_paragraph_rejected(self) -> None:
        parsed = _valid_parsed()
        parsed["body_paragraphs"] = ["Valid.", "   "]
        ok, _ = validate_model_json(parsed)
        assert ok is False


class PlaceholderBracketTests(unittest.TestCase):
    def test_bracket_in_greeting(self) -> None:
        parsed = _valid_parsed()
        parsed["greeting"] = "Dear [Your Name]"
        ok, _ = validate_model_json(parsed)
        assert ok is False

    def test_bracket_in_body(self) -> None:
        parsed = _valid_parsed()
        parsed["body_paragraphs"][0] = "Please confirm by [Date/Time]."
        ok, _ = validate_model_json(parsed)
        assert ok is False

    def test_bracket_in_closing(self) -> None:
        parsed = _valid_parsed()
        parsed["closing_phrase"] = "Best, [Name]"
        ok, _ = validate_model_json(parsed)
        assert ok is False

    def test_lowercase_bracket_allowed(self) -> None:
        parsed = _valid_parsed()
        parsed["body_paragraphs"][0] = "See version [2.0] for details."
        ok, _ = validate_model_json(parsed)
        assert ok is True

    def test_short_reference_allowed(self) -> None:
        parsed = _valid_parsed()
        parsed["body_paragraphs"][0] = "Refer to item [a] in the list."
        ok, _ = validate_model_json(parsed)
        assert ok is True


class UnknownFieldTests(unittest.TestCase):
    def test_extra_field_rejected(self) -> None:
        parsed = _valid_parsed()
        parsed["extra_field"] = "should not be here"
        ok, reason = validate_model_json(parsed)
        assert ok is False
        assert "Unknown" in reason

    def test_not_dict_rejected(self) -> None:
        ok, _ = validate_model_json([1, 2, 3])
        assert ok is False

    def test_none_rejected(self) -> None:
        ok, _ = validate_model_json(None)
        assert ok is False


if __name__ == "__main__":
    unittest.main()
