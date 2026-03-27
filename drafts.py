"""Helpers for creating Gmail reply drafts."""

from __future__ import annotations

import base64
import sys
from email.message import EmailMessage
from typing import Any

from googleapiclient.errors import HttpError

from draft_cleanup import register_agent_draft
from gmail_client import get_header


def _reply_subject(subject: str) -> str:
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}" if subject else "Re:"


def _build_reply_raw_message(
    msg: dict[str, Any],
    reply_text: str,
    thread_message_ids: list[str] | None = None,
) -> str:
    headers = (msg.get("payload") or {}).get("headers") or []
    to_addr = get_header(headers, "Reply-To") or get_header(headers, "From")
    subject = _reply_subject(get_header(headers, "Subject"))
    message_id = get_header(headers, "Message-ID")

    mail = EmailMessage()
    if to_addr:
        mail["To"] = to_addr
    mail["Subject"] = subject
    if message_id:
        mail["In-Reply-To"] = message_id
        mail["References"] = " ".join(thread_message_ids) if thread_message_ids else message_id
    mail.set_content(reply_text or "")
    return base64.urlsafe_b64encode(mail.as_bytes()).decode()


def create_reply_draft(
    service,
    msg: dict[str, Any],
    reply_text: str,
    thread_message_ids: list[str] | None = None,
) -> tuple[str | None, bool]:
    """Create a Gmail reply draft; returns (draft_id, had_error)."""
    try:
        raw = _build_reply_raw_message(msg, reply_text, thread_message_ids)
        body = {
            "message": {
                "threadId": msg.get("threadId"),
                "raw": raw,
            }
        }
        created = service.users().drafts().create(userId="me", body=body).execute()
        draft_id = created.get("id")
        register_agent_draft(service, draft_id, msg.get("threadId"))
        return draft_id, False
    except HttpError as exc:
        status = exc.resp.status if exc.resp else "?"
        print(f"Gmail API draft error (HTTP {status}): {exc}", file=sys.stderr)
        return None, True
