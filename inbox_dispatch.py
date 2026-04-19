"""Apply Gmail label actions and drafts after classification."""

from __future__ import annotations

from typing import Any

from account_notifier import sender_is_account_notifier
from drafts import create_reply_draft
from gmail_actions import archive, important_archive, report_spam
from gmail_client import get_header
from inbox_thread import extract_email


def archive_thread_inbox_messages(service: Any, messages: list[dict]) -> None:
    """Remove INBOX from each message that still has it (keeps UNREAD)."""
    for msg in messages:
        if "INBOX" in (msg.get("labelIds") or []):
            archive(service, msg["id"])


def sync_thread_out_of_inbox(
    service: Any,
    thread_messages: list[dict],
    *,
    category: str,
    trusted_sender: bool,
) -> bool:
    """Remove INBOX from every message that still has it (per-message spam / important rules)."""
    all_ok = True
    for tm in thread_messages:
        if "INBOX" not in (tm.get("labelIds") or []):
            continue
        hdrs = (tm.get("payload") or {}).get("headers") or []
        from_addr = get_header(hdrs, "From")
        addr = extract_email(from_addr).lower()
        notifier = sender_is_account_notifier(addr)
        mid = tm["id"]

        if category == "spam":
            if trusted_sender:
                ok, _ = important_archive(service, mid) if notifier else archive(service, mid)
            elif notifier:
                ok, _ = important_archive(service, mid)
            else:
                ok, _ = report_spam(service, mid)
        else:
            ok, _ = important_archive(service, mid) if notifier else archive(service, mid)
        if not ok:
            all_ok = False
    return all_ok


def dispatch_thread_action(
    service: Any,
    msg: dict,
    action: str,
    category: str,
    *,
    create_draft: bool,
    apply: bool,
    suggested_reply: str,
    thread_message_ids: list[str] | None = None,
    trusted_sender: bool = False,
    sender_email: str = "",
    thread_messages: list[dict] | None = None,
) -> str:
    """Execute the appropriate Gmail operation and return a result description."""
    account_notifier = sender_is_account_notifier(sender_email)
    tmsgs = thread_messages if thread_messages is not None else [msg]

    def _sync() -> bool:
        return sync_thread_out_of_inbox(
            service, tmsgs, category=category, trusted_sender=trusted_sender
        )

    if category == "spam":
        if trusted_sender:
            parts: list[str] = []
            did_sync = False
            if create_draft and suggested_reply.strip():
                draft_id, had_error = create_reply_draft(
                    service,
                    msg,
                    suggested_reply,
                    thread_message_ids=thread_message_ids,
                )
                if had_error:
                    parts.append("draft failed")
                else:
                    parts.append(f"draft created ({draft_id})")
                    ok = _sync()
                    tail = (
                        "archived as important (trusted sender; not spam)"
                        if account_notifier
                        else "archived (trusted sender; not reported as spam)"
                    )
                    parts.append(tail if ok else "archive failed")
                    did_sync = True
            if apply and not did_sync:
                ok = _sync()
                parts.append(
                    (
                        "archived as important (trusted sender; not spam)"
                        if account_notifier
                        else "archived (trusted sender; not reported as spam)"
                    )
                    if ok
                    else "archive failed"
                )
            if parts:
                return " | ".join(parts)
            return (
                "would archive as important (trusted sender; not spam)"
                if account_notifier
                else "would archive (trusted sender; not spam)"
            )
        if account_notifier:
            if apply:
                ok = _sync()
                return (
                    "marked important (account notifier; not spam)"
                    if ok
                    else "important action failed"
                )
            return "would mark important (account notifier; not spam)"
        if apply:
            ok = _sync()
            return "moved to spam" if ok else "spam action failed"
        return "would move to spam"

    if action == "ignore":
        if apply:
            ok = _sync()
            if not ok:
                return "archive failed"
            return "archived as important" if account_notifier else "archived"
        return "would archive as important" if account_notifier else "would archive"

    if action == "mark_read":
        # Optional thanks draft for trusted FYI (see analyze_single_thread); same archive behavior as reply.
        if create_draft and suggested_reply.strip():
            draft_id, had_error = create_reply_draft(
                service,
                msg,
                suggested_reply,
                thread_message_ids=thread_message_ids,
            )
            if had_error:
                return "draft failed"
            ok = _sync()
            if ok:
                tail = (
                    "archived as important (unread)"
                    if account_notifier
                    else "archived (unread)"
                )
                return f"draft created ({draft_id}) | {tail}"
            return f"draft created ({draft_id}) | archive failed"
        # Archive out of Inbox but keep UNREAD — user reads on their own; avoids re-fetch loops.
        if apply:
            ok = _sync()
            if not ok:
                return "archive failed"
            return (
                "archived as important (unread)"
                if account_notifier
                else "archived (unread)"
            )
        return (
            "would archive as important (unread)"
            if account_notifier
            else "would archive (unread)"
        )

    if action == "reply":
        if create_draft:
            draft_id, had_error = create_reply_draft(
                service, msg, suggested_reply,
                thread_message_ids=thread_message_ids,
            )
            if had_error:
                return "draft failed"
            ok = _sync()
            if ok:
                tail = (
                    "archived as important (unread)"
                    if account_notifier
                    else "archived (unread)"
                )
                return f"draft created ({draft_id}) | {tail}"
            return f"draft created ({draft_id}) | archive failed"
        return "analysis only"

    if action == "forward":
        if apply:
            ok = _sync()
            if not ok:
                return "archive failed"
            return (
                "archived as important (unread; forward manually)"
                if account_notifier
                else "archived (unread; forward manually)"
            )
        return (
            "would archive as important (unread; forward manually)"
            if account_notifier
            else "would archive (unread; forward manually)"
        )

    return "analysis only"
