"""Text helpers for reply composition and anti-echo checks."""

from __future__ import annotations

import base64
import binascii
import codecs
import difflib
import re
import unicodedata
from typing import Any

ECHO_SIMILARITY_THRESHOLD = 0.78
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
BASE64_TOKEN_RE = re.compile(r"\b[A-Za-z0-9+/]{16,}={0,2}")

_CONFUSABLES: dict[str, str] = {
    "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0441": "c",
    "\u0440": "p", "\u0443": "y", "\u0445": "x", "\u0456": "i",
    "\u0458": "j", "\u04bb": "h", "\u0455": "s", "\u0432": "b",
    "\u043d": "h", "\u043c": "m", "\u0442": "t",
    "\u0410": "A", "\u0412": "B", "\u0415": "E", "\u041a": "K",
    "\u041c": "M", "\u041d": "H", "\u041e": "O", "\u0420": "P",
    "\u0421": "C", "\u0422": "T", "\u0425": "X", "\u0423": "Y",
    "\u2170": "i", "\u2171": "ii", "\u2160": "I", "\u2161": "II",
    "\uff41": "a", "\uff42": "b", "\uff43": "c", "\uff44": "d",
    "\uff45": "e", "\uff46": "f", "\uff47": "g", "\uff48": "h",
    "\uff49": "i", "\uff4a": "j", "\uff4b": "k", "\uff4c": "l",
    "\uff4d": "m", "\uff4e": "n", "\uff4f": "o", "\uff50": "p",
    "\uff51": "q", "\uff52": "r", "\uff53": "s", "\uff54": "t",
    "\uff55": "u", "\uff56": "v", "\uff57": "w", "\uff58": "x",
    "\uff59": "y", "\uff5a": "z",
}
SPLIT_INSTRUCTION_MARKERS = (
    "ignorepreviousinstructions",
    "systeminstruction",
    "developermode",
    "revealyoursystemprompt",
    "returnjson",
    "classifyas",
    "suggestaction",
)
TYPOGLYCEMIA_KEYWORDS = ("ignore", "override", "reveal", "system", "instruction", "developer")
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"system\s+instruction", re.IGNORECASE),
    re.compile(r"developer\s+mode", re.IGNORECASE),
    re.compile(r"reveal\s+(your\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"output\s+(exactly|the\s+following)\b", re.IGNORECASE),
    re.compile(r"return\s+json", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"(reminder|note|instruction)\s+to\s+ai\b", re.IGNORECASE),
    re.compile(r"if\s+you\s+are\s+an?\s+ai\b", re.IGNORECASE),
    re.compile(r"classif(y|ication)\s+as\b", re.IGNORECASE),
    re.compile(r"suggest\s+action\b", re.IGNORECASE),
    re.compile(r"mark\s+as\s+(urgent|high|low|spam|normal)\b", re.IGNORECASE),
    re.compile(r"\baction\s*:\s*(reply|forward|ignore|mark_read)\b", re.IGNORECASE),
]


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


def detect_prompt_injection_signals(text: str) -> bool:
    """Return True if input contains obvious prompt-injection commands."""
    if not text or not text.strip():
        return False
    normalized = _normalize_for_detection(text)
    if any(pattern.search(normalized) for pattern in INJECTION_PATTERNS):
        return True
    if _contains_split_instruction(normalized):
        return True
    if _contains_encoded_instruction(_strip_invisible(text)):
        return True
    if _contains_rot13_instruction(normalized):
        return True
    if _contains_typoglycemia_instruction(normalized):
        return True
    return False


def looks_like_injection_output(parsed: dict[str, Any]) -> bool:
    """Check if model output still carries meta-instruction payloads."""
    text_parts: list[str] = []
    for key in ("greeting", "closing_phrase"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            text_parts.append(value)
    for paragraph in parsed.get("body_paragraphs") or []:
        if isinstance(paragraph, str) and paragraph.strip():
            text_parts.append(paragraph)
    return detect_prompt_injection_signals("\n".join(text_parts))


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


def _strip_invisible(text: str) -> str:
    """NFKC + confusables + zero-width removal, preserving case for base64."""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(_CONFUSABLES.get(ch, ch) for ch in normalized)
    normalized = ZERO_WIDTH_RE.sub("", normalized)
    return normalized


def _normalize_for_detection(text: str) -> str:
    lowered = _strip_invisible(text).lower()
    lowered = lowered.replace("\r\n", "\n").replace("\r", "\n")
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def _contains_split_instruction(text: str) -> bool:
    compact = re.sub(r"[^a-z0-9]+", "", text)
    return any(marker in compact for marker in SPLIT_INSTRUCTION_MARKERS)


def _contains_encoded_instruction(text: str) -> bool:
    for token in BASE64_TOKEN_RE.findall(text):
        try:
            decoded = base64.b64decode(token, validate=True).decode("utf-8", errors="ignore")
        except (binascii.Error, ValueError):
            continue
        normalized_decoded = _normalize_for_detection(decoded)
        if any(pattern.search(normalized_decoded) for pattern in INJECTION_PATTERNS):
            return True
        if _contains_split_instruction(normalized_decoded):
            return True
    return False


_COMMON_ENGLISH = frozenset(
    "the be to of and a in that have i it for not on with he as you do at this but his by from they"
    " we say her she or an will my one all would there their what so up out if about who get which go me"
    " when make can like time no just him know take people into year your good some could them see other"
    " than then now look only come its over think also back after use two how our work first well way even"
    " new want because any these give day most us".split()
)


def _text_has_common_english(text: str) -> bool:
    words = re.findall(r"[a-z]{2,}", text)
    if not words:
        return False
    hits = sum(1 for w in words if w in _COMMON_ENGLISH)
    return hits / len(words) >= 0.2


def _contains_rot13_instruction(text: str) -> bool:
    if _text_has_common_english(text):
        return False
    decoded = codecs.decode(text, "rot_13")
    if any(pattern.search(decoded) for pattern in INJECTION_PATTERNS):
        return True
    compact_decoded = re.sub(r"[^a-z0-9]+", "", decoded)
    return any(marker in compact_decoded for marker in SPLIT_INSTRUCTION_MARKERS)


def _contains_typoglycemia_instruction(text: str) -> bool:
    words = re.findall(r"[a-z]{5,}", text)
    for word in words:
        for keyword in TYPOGLYCEMIA_KEYWORDS:
            if _is_typoglycemia_variant(word, keyword):
                return True
    return False


def _is_typoglycemia_variant(word: str, target: str) -> bool:
    if word == target:
        return False
    if len(word) != len(target) or len(word) < 5:
        return False
    if word[0] != target[0] or word[-1] != target[-1]:
        return False
    return sorted(word[1:-1]) == sorted(target[1:-1])
