"""Newest INBOX message -> plain text -> Gemini JSON (fixed classification schema)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from analysis import AnalysisResult, analyze_email_block, compose_suggested_reply
from drafts import create_reply_draft
from gmail_client import decode_full_message_body, get_header

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]
BLOCKED_AUTO_DRAFT_ACTIONS = {"forward", "ignore"}
MAX_EMAIL_BODY_LEN = 32_000


def _load_cached_credentials() -> Credentials | None:
    if not os.path.exists("token.json"):
        return None
    try:
        with open("token.json") as f:
            data = json.load(f)
        return Credentials.from_authorized_user_info(data, SCOPES)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        try:
            os.remove("token.json")
        except OSError:
            pass
        return None


def _save_credentials(creds: Credentials) -> None:
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }
    fd = os.open("token.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)


def get_gmail_service() -> Any:
    creds = _load_cached_credentials()

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
        except RefreshError:
            creds = None
            try:
                os.remove("token.json")
            except OSError:
                pass

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        _save_credentials(creds)

    return build("gmail", "v1", credentials=creds)


def message_to_email_text(msg: dict) -> tuple[str, str]:
    """Return (prompt block, decoded body) so callers decode the payload once."""
    headers = (msg.get("payload") or {}).get("headers") or []
    body = decode_full_message_body(msg)
    if len(body) > MAX_EMAIL_BODY_LEN:
        body = body[:MAX_EMAIL_BODY_LEN]
    block = (
        f"From: {get_header(headers, 'From')}\n"
        f"Subject: {get_header(headers, 'Subject')}\n"
        f"Date: {get_header(headers, 'Date')}\n\n"
        f"Body:\n{body}"
    )
    return block, body


def _fetch_latest_inbox_message(service) -> tuple[dict | None, bool]:
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


def _draft_block_reason(action: str, suspicious_input: bool) -> str | None:
    if suspicious_input:
        return "manual review required for suspicious content"
    if action in BLOCKED_AUTO_DRAFT_ACTIONS:
        return f"manual review required for action '{action}'"
    return None


def analyze_latest(create_draft: bool = False) -> int:
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

    result = analyze_email_block(email_block, source_body=body)
    if result.error:
        print(result.error, file=sys.stderr)
        if create_draft and result.suspicious:
            print("Draft blocked: manual review required for suspicious content.", file=sys.stderr)
        return 1

    reply_name = os.environ.get("REPLY_NAME") or ""
    suggested_reply = compose_suggested_reply(result.parsed, reply_name)
    output = {
        "category": result.parsed.get("category"),
        "urgency": result.parsed.get("urgency"),
        "action": result.parsed.get("action"),
        "suggested_reply": suggested_reply,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))

    if create_draft:
        block_reason = _draft_block_reason(str(result.parsed.get("action") or ""), suspicious_input=result.suspicious)
        if block_reason:
            print(f"Draft blocked: {block_reason}.", file=sys.stderr)
            return 0
        draft_id, draft_error = create_reply_draft(service, msg, suggested_reply)
        if draft_error:
            return 1
        print(f"Draft created: {draft_id}", file=sys.stderr)

    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze newest Gmail message with Gemini.")
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Create a Gmail draft reply from suggested_reply (does not send).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
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

    if not (os.environ.get("REPLY_NAME") or "").strip():
        print("Warning: REPLY_NAME is empty; drafts will be created without sender name.", file=sys.stderr)

    return analyze_latest(create_draft=args.draft)


if __name__ == "__main__":
    raise SystemExit(main())
