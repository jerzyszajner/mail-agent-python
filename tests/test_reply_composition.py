"""Tests for reply composition and anti-echo (reply_text.py; re-exported via analysis_text).

Covers: compose_suggested_reply, _normalize_reply_text, _looks_like_echo.
"""

from __future__ import annotations

import unittest

from analysis_text import (
    _looks_like_echo,
    _normalize_reply_text,
    compose_suggested_reply,
)


class ComposeReplyTests(unittest.TestCase):
    def _parsed(self, **overrides) -> dict:
        base = {
            "category": "normal",
            "urgency": "medium",
            "action": "reply",
            "greeting": "Cześć",
            "body_paragraphs": [
                "Dziękuję za wiadomość.",
                "Odpowiem w ciągu 24h.",
            ],
            "closing_phrase": "Pozdrawiam",
        }
        base.update(overrides)
        return base

    def test_basic_reply_with_name(self) -> None:
        reply = compose_suggested_reply(self._parsed(), "Jan Kowalski")
        assert "Cześć," in reply
        assert "Dziękuję za wiadomość." in reply
        assert "Odpowiem w ciągu 24h." in reply
        assert "Pozdrawiam" in reply
        assert reply.endswith("Jan Kowalski")

    def test_reply_without_name(self) -> None:
        reply = compose_suggested_reply(self._parsed(), "")
        assert reply.endswith("Pozdrawiam")
        assert "Jan" not in reply

    def test_greeting_comma_appended(self) -> None:
        reply = compose_suggested_reply(self._parsed(greeting="Hello"), "")
        assert reply.startswith("Hello,")

    def test_greeting_with_existing_comma(self) -> None:
        reply = compose_suggested_reply(self._parsed(greeting="Hello,"), "")
        assert reply.startswith("Hello,")
        assert not reply.startswith("Hello,,")

    def test_greeting_with_exclamation(self) -> None:
        reply = compose_suggested_reply(self._parsed(greeting="Hi!"), "")
        assert reply.startswith("Hi!")
        assert not reply.startswith("Hi!,")

    def test_three_paragraphs(self) -> None:
        parsed = self._parsed(body_paragraphs=["A.", "B.", "C."])
        reply = compose_suggested_reply(parsed, "")
        assert "A." in reply
        assert "B." in reply
        assert "C." in reply

    def test_empty_fields_handled(self) -> None:
        parsed = self._parsed(greeting="", body_paragraphs=[], closing_phrase="")
        reply = compose_suggested_reply(parsed, "")
        assert isinstance(reply, str)


class NormalizeReplyTextTests(unittest.TestCase):
    def test_empty_string(self) -> None:
        assert _normalize_reply_text("") == ""

    def test_collapses_spaces(self) -> None:
        assert _normalize_reply_text("hello   world") == "hello world"

    def test_collapses_tabs(self) -> None:
        assert _normalize_reply_text("hello\t\tworld") == "hello world"

    def test_space_after_comma(self) -> None:
        assert _normalize_reply_text("hello,world") == "hello, world"

    def test_space_after_sentence_end(self) -> None:
        result = _normalize_reply_text("First sentence.Second sentence")
        assert "First sentence. Second sentence" == result

    def test_preserves_single_newline(self) -> None:
        result = _normalize_reply_text("line1\nline2")
        assert "line1\nline2" == result

    def test_collapses_triple_newlines(self) -> None:
        result = _normalize_reply_text("a\n\n\n\nb")
        assert "a\n\nb" == result

    def test_strips_line_whitespace(self) -> None:
        result = _normalize_reply_text("  hello  \n  world  ")
        assert "hello\nworld" == result

    def test_crlf_normalized(self) -> None:
        result = _normalize_reply_text("hello\r\nworld")
        assert "hello\nworld" == result

    def test_unicode_letters_after_period(self) -> None:
        result = _normalize_reply_text("OK.Cześć")
        assert "OK. Cześć" == result


class LooksLikeEchoTests(unittest.TestCase):
    def test_identical_content_detected(self) -> None:
        source = "Please send me the quarterly report by Friday. I need the revenue breakdown and expense summary."
        parsed = {
            "greeting": "Hi,",
            "body_paragraphs": [
                "Please send me the quarterly report by Friday.",
                "I need the revenue breakdown and expense summary.",
            ],
            "closing_phrase": "Thanks",
        }
        assert _looks_like_echo(parsed, source) is True

    def test_different_content_passes(self) -> None:
        source = "Can we meet tomorrow at 3pm?"
        parsed = {
            "greeting": "Hello,",
            "body_paragraphs": [
                "Thank you for reaching out.",
                "I would be happy to schedule a meeting.",
            ],
            "closing_phrase": "Best regards",
        }
        assert _looks_like_echo(parsed, source) is False

    def test_empty_source_returns_false(self) -> None:
        parsed = {
            "greeting": "Hi,",
            "body_paragraphs": ["Some text.", "More text."],
            "closing_phrase": "Bye",
        }
        assert _looks_like_echo(parsed, "") is False

    def test_empty_reply_returns_false(self) -> None:
        parsed = {
            "greeting": "",
            "body_paragraphs": [],
            "closing_phrase": "",
        }
        assert _looks_like_echo(parsed, "Some source text here.") is False

    def test_partial_overlap_below_threshold(self) -> None:
        source = "I need the quarterly financial report for Q4 2025 including all revenue streams."
        parsed = {
            "greeting": "Dear colleague,",
            "body_paragraphs": [
                "I have received your request for the quarterly report.",
                "I will prepare the Q4 2025 financial data and send it by end of week.",
            ],
            "closing_phrase": "Kind regards",
        }
        assert _looks_like_echo(parsed, source) is False

    def test_near_verbatim_copy_detected(self) -> None:
        source = "We need to schedule a team meeting for next Monday to discuss the project timeline and resource allocation."
        parsed = {
            "greeting": "Hi team,",
            "body_paragraphs": [
                "We need to schedule a team meeting for next Monday.",
                "We should discuss the project timeline and resource allocation.",
            ],
            "closing_phrase": "Thanks",
        }
        assert _looks_like_echo(parsed, source) is True


if __name__ == "__main__":
    unittest.main()
