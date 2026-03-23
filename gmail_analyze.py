"""Newest INBOX message -> plain text -> Gemini JSON (fixed classification schema)."""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys

from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from analysis import analyze_email_block
from drafts import create_reply_draft
from gmail_client import decode_full_message_body

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


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

    parsed, error = analyze_email_block(email_block)
    if error:
        print(error, file=sys.stderr)
        return 1

    print(json.dumps(parsed, ensure_ascii=False, indent=2))

    if create_draft:
        draft_id, draft_error = create_reply_draft(service, msg, parsed.get("suggested_reply", ""))
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

    return analyze_latest(create_draft=args.draft)


if __name__ == "__main__":
    raise SystemExit(main())
