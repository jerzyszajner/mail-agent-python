"""Helpers for creating Gmail reply drafts."""

from __future__ import annotations

import base64
import sys
from email.message import EmailMessage
from typing import Any

from googleapiclient.errors import HttpError


def _header(headers: list[dict], name: str) -> str:
    name_l = name.lower()
    for h in headers:
        if (h.get("name") or "").lower() == name_l:
            return h.get("value") or ""
    return ""


def _reply_subject(subject: str) -> str:
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}" if subject else "Re:"


def _build_reply_raw_message(msg: dict[str, Any], reply_text: str) -> str:
    headers = (msg.get("payload") or {}).get("headers") or []
    to_addr = _header(headers, "Reply-To") or _header(headers, "From")
    subject = _reply_subject(_header(headers, "Subject"))
    message_id = _header(headers, "Message-ID")

    mail = EmailMessage()
    if to_addr:
        mail["To"] = to_addr
    mail["Subject"] = subject
    if message_id:
        mail["In-Reply-To"] = message_id
        mail["References"] = message_id
    mail.set_content(reply_text or "")
    return base64.urlsafe_b64encode(mail.as_bytes()).decode()


def create_reply_draft(service, msg: dict[str, Any], reply_text: str) -> tuple[str | None, bool]:
    """Create a Gmail reply draft; returns (draft_id, had_error)."""
    try:
        raw = _build_reply_raw_message(msg, reply_text)
        body = {
            "message": {
                "threadId": msg.get("threadId"),
                "raw": raw,
            }
        }
        created = service.users().drafts().create(userId="me", body=body).execute()
        return created.get("id"), False
    except HttpError as exc:
        status = exc.resp.status if exc.resp else "?"
        print(f"Gmail API draft error (HTTP {status}): {exc}", file=sys.stderr)
        return None, True
