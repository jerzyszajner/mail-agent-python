"""Compatibility re-exports for tests; prefer injection_detection and reply_text in new code."""

from __future__ import annotations

from .injection_detection import (
    BASE64_TOKEN_RE,
    INJECTION_PATTERNS,
    SPLIT_INSTRUCTION_MARKERS,
    TYPOGLYCEMIA_KEYWORDS,
    ZERO_WIDTH_RE,
    detect_prompt_injection_signals,
    looks_like_injection_output,
    _contains_encoded_instruction,
    _contains_rot13_instruction,
    _contains_split_instruction,
    _contains_typoglycemia_instruction,
    _normalize_for_detection,
)
from .reply_text import (
    ECHO_SIMILARITY_THRESHOLD,
    compose_suggested_reply,
    _extract_source_body,
    _looks_like_echo,
    _normalize_for_similarity,
    _normalize_reply_text,
)

__all__ = [
    "BASE64_TOKEN_RE",
    "ECHO_SIMILARITY_THRESHOLD",
    "INJECTION_PATTERNS",
    "SPLIT_INSTRUCTION_MARKERS",
    "TYPOGLYCEMIA_KEYWORDS",
    "ZERO_WIDTH_RE",
    "compose_suggested_reply",
    "detect_prompt_injection_signals",
    "looks_like_injection_output",
    "_contains_encoded_instruction",
    "_contains_rot13_instruction",
    "_contains_split_instruction",
    "_contains_typoglycemia_instruction",
    "_extract_source_body",
    "_looks_like_echo",
    "_normalize_for_detection",
    "_normalize_for_similarity",
    "_normalize_reply_text",
]
