"""Gemini analysis JSON schema and validation helpers."""

from __future__ import annotations

import re
from typing import Any

MAX_GREETING_LEN = 160
MAX_PARAGRAPH_LEN = 1000
MAX_CLOSING_LEN = 120

VALID_CATEGORIES = {"urgent", "normal", "spam"}
VALID_URGENCIES = {"high", "medium", "low"}
VALID_ACTIONS = {"reply", "forward", "ignore", "mark_read"}
REQUIRED_FIELDS = ("category", "urgency", "action", "greeting", "body_paragraphs", "closing_phrase")

PLACEHOLDER_RE = re.compile(r"\[[A-Z][^\]]{1,30}\]|[［【][^\]］】]{1,30}[］】]")

EMAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": sorted(VALID_CATEGORIES)},
        "urgency": {"type": "string", "enum": sorted(VALID_URGENCIES)},
        "action": {"type": "string", "enum": sorted(VALID_ACTIONS)},
        "greeting": {"type": "string", "minLength": 1, "maxLength": MAX_GREETING_LEN},
        "body_paragraphs": {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": {"type": "string", "minLength": 1, "maxLength": MAX_PARAGRAPH_LEN},
        },
        "closing_phrase": {"type": "string", "minLength": 1, "maxLength": MAX_CLOSING_LEN},
    },
    "additionalProperties": False,
    "required": list(REQUIRED_FIELDS),
}


def validate_model_json(parsed: Any) -> tuple[bool, str]:
    """Validate AI JSON against the fixed app contract."""
    if not isinstance(parsed, dict):
        return False, "Expected JSON object."
    missing = [k for k in REQUIRED_FIELDS if k not in parsed]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"
    unknown = sorted(set(parsed.keys()) - set(REQUIRED_FIELDS))
    if unknown:
        return False, f"Unknown fields are not allowed: {', '.join(unknown)}"
    if parsed["category"] not in VALID_CATEGORIES:
        return False, "Invalid value for category."
    if parsed["urgency"] not in VALID_URGENCIES:
        return False, "Invalid value for urgency."
    if parsed["action"] not in VALID_ACTIONS:
        return False, "Invalid value for action."
    if not isinstance(parsed["greeting"], str):
        return False, "Field greeting must be a string."
    if not isinstance(parsed["body_paragraphs"], list):
        return False, "Field body_paragraphs must be an array of strings."
    if len(parsed["body_paragraphs"]) < 2 or len(parsed["body_paragraphs"]) > 3:
        return False, "Field body_paragraphs must have 2 to 3 paragraphs."
    for idx, paragraph in enumerate(parsed["body_paragraphs"], start=1):
        if not isinstance(paragraph, str) or not paragraph.strip():
            return False, f"Paragraph {idx} in body_paragraphs must be a non-empty string."
    if not isinstance(parsed["closing_phrase"], str):
        return False, "Field closing_phrase must be a string."
    if not parsed["greeting"].strip():
        return False, "Field greeting cannot be empty."
    if not parsed["closing_phrase"].strip():
        return False, "Field closing_phrase cannot be empty."
    if len(parsed["greeting"]) > MAX_GREETING_LEN:
        return False, f"Field greeting must be <= {MAX_GREETING_LEN} characters."
    if len(parsed["closing_phrase"]) > MAX_CLOSING_LEN:
        return False, f"Field closing_phrase must be <= {MAX_CLOSING_LEN} characters."
    for idx, paragraph in enumerate(parsed["body_paragraphs"], start=1):
        if len(paragraph) > MAX_PARAGRAPH_LEN:
            return False, f"Paragraph {idx} in body_paragraphs must be <= {MAX_PARAGRAPH_LEN} characters."
    if PLACEHOLDER_RE.search(parsed["greeting"]):
        return False, "Field greeting contains placeholder-like brackets."
    if any(PLACEHOLDER_RE.search(p) for p in parsed["body_paragraphs"]):
        return False, "Field body_paragraphs contains placeholder-like brackets."
    if PLACEHOLDER_RE.search(parsed["closing_phrase"]):
        return False, "Field closing_phrase contains placeholder-like brackets."
    return True, ""
