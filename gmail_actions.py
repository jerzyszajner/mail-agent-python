"""Gmail label operations for batch email processing."""

from __future__ import annotations

import sys
from typing import Any

from googleapiclient.errors import HttpError


def archive(service: Any, msg_id: str) -> tuple[bool, str | None]:
    """Remove INBOX only; leave UNREAD so you still see the thread as new outside Inbox."""
    return _modify_labels(service, msg_id, remove=["INBOX"])


def report_spam(service: Any, msg_id: str) -> tuple[bool, str | None]:
    """Move to spam; leave UNREAD so Spam still shows as new mail."""
    return _modify_labels(service, msg_id, add=["SPAM"], remove=["INBOX"])


def _modify_labels(
    service: Any,
    msg_id: str,
    *,
    add: list[str] | None = None,
    remove: list[str] | None = None,
) -> tuple[bool, str | None]:
    body: dict[str, list[str]] = {}
    if add:
        body["addLabelIds"] = add
    if remove:
        body["removeLabelIds"] = remove
    try:
        service.users().messages().modify(
            userId="me", id=msg_id, body=body
        ).execute()
        return True, None
    except HttpError as exc:
        status = exc.resp.status if exc.resp else "?"
        error = f"Gmail API modify error (HTTP {status}): {exc}"
        print(error, file=sys.stderr)
        return False, error
