"""Compose suggested replies and compare model output to sender text (anti-echo)."""

from __future__ import annotations

import difflib
import re
from typing import Any

ECHO_SIMILARITY_THRESHOLD = 0.78


def compose_suggested_reply(parsed: dict[str, Any], reply_name: str) -> str:
    """Compose final reply text with deterministic sender name."""
    greeting = _normalize_reply_text((parsed.get("greeting") or "").strip())
    body_paragraphs = parsed.get("body_paragraphs") or []
    body = "\n\n".join(
        _normalize_reply_text((paragraph or "").strip())
        for paragraph in body_paragraphs
        if (paragraph or "").strip()
    )
    closing = _normalize_reply_text((parsed.get("closing_phrase") or "").strip())
    name = (reply_name or "").strip()
    if greeting and not greeting.endswith((",", "!", "?", ":")):
        greeting = f"{greeting},"
    if name:
        return f"{greeting}\n\n{body}\n\n{closing}\n{name}"
    return f"{greeting}\n\n{body}\n\n{closing}"


def _extract_source_body(email_block: str) -> str:
    _, _, body = email_block.partition("Body:\n")
    return body.strip()


def _looks_like_echo(parsed: dict[str, Any], source_body: str) -> bool:
    if not source_body:
        return False
    sections: list[str] = []
    greeting = parsed.get("greeting")
    if isinstance(greeting, str) and greeting.strip():
        sections.append(greeting.strip())
    body_paragraphs = parsed.get("body_paragraphs") or []
    sections.extend(p.strip() for p in body_paragraphs if isinstance(p, str) and p.strip())
    closing = parsed.get("closing_phrase")
    if isinstance(closing, str) and closing.strip():
        sections.append(closing.strip())
    reply_text = " ".join(sections).strip()
    if not reply_text:
        return False
    a = _normalize_for_similarity(reply_text)
    b = _normalize_for_similarity(source_body)
    if not a or not b:
        return False
    # High similarity usually means model echoed sender content.
    return difflib.SequenceMatcher(None, a, b).ratio() >= ECHO_SIMILARITY_THRESHOLD


def _normalize_reply_text(text: str) -> str:
    """
    Normalize spacing for model output text.

    Keeps line breaks, but fixes missing spaces after punctuation.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"([,;:!?])(?=\S)", r"\1 ", text)
    # Insert space between sentence end and next word when model omits it.
    text = re.sub(r"(?<=[.!?])(?=[A-Za-zÀ-ÖØ-öø-ÿĀ-ž])", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _normalize_for_similarity(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"\s+", " ", lowered)
    lowered = re.sub(r"[^a-z0-9\u00c0-\u024f\u0100-\u017f ]+", "", lowered)
    return lowered.strip()
