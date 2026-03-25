"""Batch INBOX analysis: fetch unread threads, classify with Gemini, apply Gmail actions."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from analysis import analyze_email_block, compose_suggested_reply
from drafts import create_reply_draft
from gmail_actions import archive, mark_as_read, report_spam
from gmail_client import decode_full_message_body, get_header

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
MAX_EMAIL_BODY_LEN = 32_000
DEFAULT_MAX_RESULTS = 10

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


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


def _is_from_me(from_header: str, my_email: str) -> bool:
    if not my_email:
        return False
    return my_email.lower() in from_header.lower()


def _extract_email(from_header: str) -> str:
    m = _EMAIL_RE.search(from_header)
    return m.group(0) if m else from_header


def _fetch_unread_threads(service, max_results: int) -> tuple[list[dict], bool]:
    """Fetch unread INBOX threads (full format), deduplicated by threadId."""
    try:
        listed = (
            service.users()
            .messages()
            .list(userId="me", labelIds=["INBOX"], q="is:unread", maxResults=max_results)
            .execute()
        )
        entries = listed.get("messages") or []
        if not entries:
            return [], False

        seen: set[str] = set()
        unique_thread_ids: list[str] = []
        for entry in entries:
            tid = entry.get("threadId", "")
            if tid and tid not in seen:
                seen.add(tid)
                unique_thread_ids.append(tid)

        threads: list[dict] = []
        for tid in unique_thread_ids:
            thread = (
                service.users()
                .threads()
                .get(userId="me", id=tid, format="full")
                .execute()
            )
            threads.append(thread)
        return threads, False
    except HttpError as exc:
        status = exc.resp.status if exc.resp else "?"
        print(f"Gmail API error (HTTP {status}): {exc}", file=sys.stderr)
        return [], True


def _thread_to_email_text(
    messages: list[dict], my_email: str
) -> tuple[str, str, dict, list[str]]:
    """Build conversation context from all messages in a thread.

    Returns (conversation_block, last_external_body, reply_target_msg, thread_message_header_ids).
    """
    messages_sorted = sorted(messages, key=lambda m: int(m.get("internalDate", "0")))

    parts: list[str] = []
    reply_target = messages_sorted[-1]
    last_external_body = ""
    thread_message_header_ids: list[str] = []

    for msg in messages_sorted:
        headers = (msg.get("payload") or {}).get("headers") or []
        from_addr = get_header(headers, "From")
        date = get_header(headers, "Date")
        message_id = get_header(headers, "Message-ID")

        if message_id:
            thread_message_header_ids.append(message_id)

        body = decode_full_message_body(msg)
        if len(body) > MAX_EMAIL_BODY_LEN:
            body = body[:MAX_EMAIL_BODY_LEN]

        is_me = _is_from_me(from_addr, my_email)
        role = "[ME]" if is_me else "[SENDER]"

        parts.append(
            f"--- {role} ---\n"
            f"From: {from_addr}\n"
            f"Date: {date}\n\n"
            f"Body:\n{body}"
        )

        if not is_me:
            reply_target = msg
            last_external_body = body

    conversation_block = "\n\n".join(parts)
    return conversation_block, last_external_body, reply_target, thread_message_header_ids


def _mark_thread_read(service, messages: list[dict]) -> None:
    """Mark all UNREAD messages in a thread as read."""
    for msg in messages:
        labels = msg.get("labelIds") or []
        if "UNREAD" in labels:
            mark_as_read(service, msg["id"])


def _dispatch_action(
    service,
    msg: dict,
    action: str,
    category: str,
    *,
    create_draft: bool,
    apply: bool,
    suggested_reply: str,
    thread_message_ids: list[str] | None = None,
) -> str:
    """Execute the appropriate Gmail operation and return a result description."""
    if category == "spam":
        if apply:
            ok, _ = report_spam(service, msg["id"])
            return "moved to spam" if ok else "spam action failed"
        return "would move to spam"

    if action == "ignore":
        if apply:
            ok, _ = archive(service, msg["id"])
            return "archived" if ok else "archive failed"
        return "would archive"

    if action == "mark_read":
        if apply:
            ok, _ = mark_as_read(service, msg["id"])
            return "marked as read" if ok else "mark_read failed"
        return "would mark as read"

    if action == "reply":
        if create_draft:
            draft_id, had_error = create_reply_draft(
                service, msg, suggested_reply,
                thread_message_ids=thread_message_ids,
            )
            if had_error:
                return "draft failed"
            return f"draft created ({draft_id})"
        return "analysis only"

    if action == "forward":
        if apply:
            ok, _ = mark_as_read(service, msg["id"])
            return "marked as read (forward manually)" if ok else "mark_read failed"
        return "would mark as read (forward manually)"

    return "analysis only"


def _analyze_single(
    service,
    thread: dict,
    my_email: str,
    *,
    create_draft: bool,
    apply: bool,
    reply_name: str,
) -> dict[str, Any]:
    """Analyze one thread and return a result dict for the summary."""
    messages = thread.get("messages") or []
    if not messages:
        return {
            "from": "",
            "subject": "",
            "category": None,
            "urgency": None,
            "action": None,
            "suggested_reply": "",
            "result": "empty thread",
        }

    conversation_block, last_body, reply_target, thread_msg_ids = _thread_to_email_text(
        messages, my_email
    )

    target_headers = (reply_target.get("payload") or {}).get("headers") or []
    sender = get_header(target_headers, "From")
    subject = get_header(target_headers, "Subject")

    if not last_body.strip():
        print(f"Note: no body for thread {thread.get('id')} (attachments only).", file=sys.stderr)

    result = analyze_email_block(conversation_block, source_body=last_body)

    if result.error:
        if result.suspicious and apply:
            _mark_thread_read(service, messages)
            result_desc = "blocked (suspicious) — marked as read"
        elif result.suspicious:
            result_desc = "blocked (suspicious)"
        else:
            result_desc = "analysis failed"
        print(f"Analysis failed for '{subject}': {result.error}", file=sys.stderr)
        return {
            "from": sender,
            "subject": subject,
            "category": None,
            "urgency": None,
            "action": None,
            "suggested_reply": "",
            "result": result_desc,
        }

    parsed = result.parsed
    category = str(parsed.get("category") or "")
    action = str(parsed.get("action") or "")

    suggested_reply = ""
    if action == "reply" and not result.suspicious:
        suggested_reply = compose_suggested_reply(parsed, reply_name)

    effective_draft = create_draft and not result.suspicious and action == "reply"

    action_result = _dispatch_action(
        service,
        reply_target,
        action,
        category,
        create_draft=effective_draft,
        apply=apply,
        suggested_reply=suggested_reply,
        thread_message_ids=thread_msg_ids,
    )

    if apply:
        _mark_thread_read(service, messages)

    return {
        "from": sender,
        "subject": subject,
        "category": parsed.get("category"),
        "urgency": parsed.get("urgency"),
        "action": parsed.get("action"),
        "suggested_reply": suggested_reply,
        "result": action_result,
    }


def analyze_inbox(
    max_results: int = DEFAULT_MAX_RESULTS,
    create_draft: bool = False,
    apply: bool = False,
) -> int:
    try:
        service = get_gmail_service()
    except FileNotFoundError:
        print("Missing credentials.json - add Desktop OAuth client JSON from Google Cloud.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Failed to authenticate with Gmail: {exc}", file=sys.stderr)
        return 1

    my_email = ""
    try:
        profile = service.users().getProfile(userId="me").execute()
        my_email = profile.get("emailAddress", "")
    except HttpError:
        print("Warning: could not fetch user profile; thread role detection may be inaccurate.", file=sys.stderr)

    threads, had_error = _fetch_unread_threads(service, max_results)
    if not threads:
        if had_error:
            return 1
        print("No unread messages in INBOX.")
        return 0

    reply_name = os.environ.get("REPLY_NAME") or ""
    results: list[dict[str, Any]] = []

    for i, thread in enumerate(threads, start=1):
        msgs = thread.get("messages") or []
        last_msg = sorted(msgs, key=lambda m: int(m.get("internalDate", "0")))[-1] if msgs else {}
        last_headers = (last_msg.get("payload") or {}).get("headers") or []
        subject = get_header(last_headers, "Subject")
        msg_count = len(msgs)
        print(f"[{i}/{len(threads)}] Analyzing thread ({msg_count} msgs): {subject}", file=sys.stderr)

        entry = _analyze_single(
            service,
            thread,
            my_email,
            create_draft=create_draft,
            apply=apply,
            reply_name=reply_name,
        )
        results.append(entry)
        print(f"  -> {entry['category']} / {entry['action']} -> {entry['result']}", file=sys.stderr)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze unread Gmail messages with Gemini.")
    parser.add_argument(
        "--max",
        type=int,
        default=DEFAULT_MAX_RESULTS,
        help=f"Maximum number of unread messages to process (default: {DEFAULT_MAX_RESULTS}).",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Create Gmail draft replies for messages classified as 'reply'.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute Gmail actions: move spam, archive ignored, mark read. Without this flag the run is analysis-only.",
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

    return analyze_inbox(
        max_results=args.max,
        create_draft=args.draft,
        apply=args.apply,
    )


if __name__ == "__main__":
    raise SystemExit(main())
