"""Newest INBOX message -> plain text -> Gemini JSON (fixed classification schema)."""

from __future__ import annotations

import json
import os
import pickle
import sys
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.genai import types
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from gmail_client import decode_full_message_body

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
MODEL_NAME = "gemini-2.5-flash"
ANALYZE_PROMPT = (
    "Analyze this email and return classification plus suggested reply. "
    "Return JSON only. "
    "Write suggested_reply in the same language as the email content. "
    "If the message language is mixed or unclear, use the dominant language from Subject and Body."
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


def get_gmail_service():
    creds = None
    if os.path.exists("token.json"):
        try:
            with open("token.json", "rb") as token:
                creds = pickle.load(token)
        except (pickle.UnpicklingError, EOFError, AttributeError, ValueError):
            # Corrupted token cache should not block OAuth re-auth.
            creds = None
            try:
                os.remove("token.json")
            except OSError:
                pass

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            creds = None
            try:
                os.remove("token.json")
            except OSError:
                pass

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open("token.json", "wb") as token:
            pickle.dump(creds, token)

    return build("gmail", "v1", credentials=creds)


def _header(headers: list[dict], name: str) -> str:
    name_l = name.lower()
    for h in headers:
        if (h.get("name") or "").lower() == name_l:
            return h.get("value") or ""
    return ""


def message_to_email_text(msg: dict) -> tuple[str, str]:
    """Return (prompt block, decoded body) so callers decode the payload once."""
    headers = (msg.get("payload") or {}).get("headers") or []
    body = decode_full_message_body(msg)
    block = (
        f"From: {_header(headers, 'From')}\n"
        f"Subject: {_header(headers, 'Subject')}\n"
        f"Date: {_header(headers, 'Date')}\n\n"
        f"Body:\n{body}"
    )
    return block, body


def _validate_model_json(parsed: Any) -> tuple[bool, str]:
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


def _fetch_latest_inbox_message(service) -> tuple[dict[str, Any] | None, bool]:
    try:
        listed = (
            service.users()
            .messages()
            .list(userId="me", labelIds=["INBOX"], maxResults=1)
            .execute()
        )
        ids = listed.get("messages") or []
        if not ids:
            return None, False
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=ids[0]["id"], format="full")
            .execute()
        )
        return msg, False
    except HttpError as exc:
        status = exc.resp.status if exc.resp else "?"
        print(f"Gmail API error (HTTP {status}): {exc}", file=sys.stderr)
        return None, True


def analyze_latest() -> int:
    try:
        service = get_gmail_service()
    except FileNotFoundError:
        print("Missing credentials.json - add Desktop OAuth client JSON from Google Cloud.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Failed to authenticate with Gmail: {exc}", file=sys.stderr)
        return 1

    msg, had_error = _fetch_latest_inbox_message(service)
    if msg is None:
        if had_error:
            return 1
        print("No messages in INBOX.")
        return 0

    email_block, body = message_to_email_text(msg)
    if not body.strip():
        print("Note: no plain/html body decoded (e.g. attachments only).", file=sys.stderr)

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
        print(f"Gemini API error: {exc}", file=sys.stderr)
        return 1

    raw = response.text or ""
    if not raw.strip():
        print("Model returned empty response.", file=sys.stderr)
        return 1

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print("Model did not return valid JSON:", exc, file=sys.stderr)
        print(raw, file=sys.stderr)
        return 1

    ok, reason = _validate_model_json(parsed)
    if not ok:
        print(f"Model JSON does not match expected schema: {reason}", file=sys.stderr)
        print(raw, file=sys.stderr)
        return 1

    print(json.dumps(parsed, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    load_dotenv()

    if not (os.environ.get("GEMINI_API_KEY") or "").strip():
        print(
            "Missing GEMINI_API_KEY - set it in .env (see .env.example).",
            file=sys.stderr,
        )
        return 1

    if not os.path.exists("credentials.json"):
        print("Missing credentials.json - add Desktop OAuth client JSON from Google Cloud.", file=sys.stderr)
        return 1

    return analyze_latest()


if __name__ == "__main__":
    raise SystemExit(main())
