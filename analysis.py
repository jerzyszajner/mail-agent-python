"""Gemini email analysis helpers and schema validation."""

from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

MODEL_NAME = "gemini-2.5-flash"
ANALYZE_PROMPT = (
    "Analyze this email and return classification plus suggested reply. "
    "Return JSON only. "
    "Write suggested_reply in the same language as the email content. "
    "If the message language is mixed or unclear, use the dominant language from Subject and Body. "
    "Use natural punctuation and spacing in suggested_reply: always put a space after commas and sentence-ending periods."
)

EMAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["urgent", "normal", "spam"]},
        "urgency": {"type": "string", "enum": ["high", "medium", "low"]},
        "action": {"type": "string", "enum": ["reply", "forward", "ignore", "mark_read"]},
        "suggested_reply": {"type": "string"},
    },
    "required": ["category", "urgency", "action", "suggested_reply"],
}


def validate_model_json(parsed: Any) -> tuple[bool, str]:
    """Validate AI JSON against the fixed app contract."""
    if not isinstance(parsed, dict):
        return False, "Expected JSON object."
    required = ["category", "urgency", "action", "suggested_reply"]
    missing = [k for k in required if k not in parsed]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"
    if parsed["category"] not in {"urgent", "normal", "spam"}:
        return False, "Invalid value for category."
    if parsed["urgency"] not in {"high", "medium", "low"}:
        return False, "Invalid value for urgency."
    if parsed["action"] not in {"reply", "forward", "ignore", "mark_read"}:
        return False, "Invalid value for action."
    if not isinstance(parsed["suggested_reply"], str):
        return False, "Field suggested_reply must be a string."
    return True, ""


def analyze_email_block(email_block: str) -> tuple[dict[str, Any] | None, str | None]:
    """
    Analyze email text with Gemini.

    Returns (parsed_json, error_message). On success error_message is None.
    """
    try:
        client = genai.Client()
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=f"{ANALYZE_PROMPT}\n\n{email_block}",
            config=types.GenerateContentConfig(
                temperature=0.4,
                max_output_tokens=2000,
                response_mime_type="application/json",
                response_json_schema=EMAIL_SCHEMA,
            ),
        )
    except Exception as exc:
        return None, f"Gemini API error: {exc}"

    raw = response.text or ""
    if not raw.strip():
        return None, "Model returned empty response."

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"Model did not return valid JSON: {exc}\n{raw}"

    ok, reason = validate_model_json(parsed)
    if not ok:
        return None, f"Model JSON does not match expected schema: {reason}\n{raw}"

    return parsed, None
