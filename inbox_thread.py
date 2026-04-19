"""Fetch Gmail threads and build conversation text for analysis."""

from __future__ import annotations

import re
import sys
from typing import Any

from googleapiclient.errors import HttpError

from gmail_client import decode_full_message_body, get_header

MAX_EMAIL_BODY_LEN = 32_000

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def extract_email(from_header: str) -> str:
    m = _EMAIL_RE.search(from_header)
    return m.group(0) if m else from_header


def _is_from_me(from_header: str, my_email: str) -> bool:
    if not my_email:
        return False
    return my_email.lower() in from_header.lower()


def thread_to_email_text(
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


def fetch_unread_threads(service: Any, max_results: int) -> tuple[list[dict], bool]:
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
