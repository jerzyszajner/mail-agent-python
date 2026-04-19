"""Apply Gmail label actions and drafts after classification."""

from __future__ import annotations

from collections.abc import Callable
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


def _unread_tail(account_notifier: bool) -> str:
    return (
        "archived as important (unread)"
        if account_notifier
        else "archived (unread)"
    )


def _would_unread_tail(account_notifier: bool) -> str:
    return (
        "would archive as important (unread)"
        if account_notifier
        else "would archive (unread)"
    )


def _create_draft_and_sync_unread(
    service: Any,
    msg: dict,
    suggested_reply: str,
    thread_message_ids: list[str] | None,
    sync: Callable[[], bool],
    account_notifier: bool,
) -> str:
    """Shared path: reply draft or trusted FYI draft, then remove thread from Inbox (keep UNREAD)."""
    draft_id, had_error = create_reply_draft(
        service,
        msg,
        suggested_reply,
        thread_message_ids=thread_message_ids,
    )
    if had_error:
        return "draft failed"
    ok = sync()
    tail = _unread_tail(account_notifier)
    if ok:
        return f"draft created ({draft_id}) | {tail}"
    return f"draft created ({draft_id}) | archive failed"


def _dispatch_spam(
    *,
    trusted_sender: bool,
    account_notifier: bool,
    create_draft: bool,
    apply: bool,
    suggested_reply: str,
    service: Any,
    msg: dict,
    thread_message_ids: list[str] | None,
    sync: Callable[[], bool],
) -> str:
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
                ok = sync()
                tail = (
                    "archived as important (trusted sender; not spam)"
                    if account_notifier
                    else "archived (trusted sender; not reported as spam)"
                )
                parts.append(tail if ok else "archive failed")
                did_sync = True
        if apply and not did_sync:
            ok = sync()
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
            ok = sync()
            return (
                "marked important (account notifier; not spam)"
                if ok
                else "important action failed"
            )
        return "would mark important (account notifier; not spam)"
    if apply:
        ok = sync()
        return "moved to spam" if ok else "spam action failed"
    return "would move to spam"


def _dispatch_ignore(*, apply: bool, sync: Callable[[], bool], account_notifier: bool) -> str:
    if apply:
        ok = sync()
        if not ok:
            return "archive failed"
        return "archived as important" if account_notifier else "archived"
    return "would archive as important" if account_notifier else "would archive"


def _dispatch_mark_read(
    *,
    create_draft: bool,
    apply: bool,
    suggested_reply: str,
    service: Any,
    msg: dict,
    thread_message_ids: list[str] | None,
    sync: Callable[[], bool],
    account_notifier: bool,
) -> str:
    # Optional thanks draft for trusted FYI (see analyze_single_thread); same archive behavior as reply.
    if create_draft and suggested_reply.strip():
        return _create_draft_and_sync_unread(
            service, msg, suggested_reply, thread_message_ids, sync, account_notifier
        )
    # Archive out of Inbox but keep UNREAD — user reads on their own; avoids re-fetch loops.
    if apply:
        ok = sync()
        if not ok:
            return "archive failed"
        return _unread_tail(account_notifier)
    return _would_unread_tail(account_notifier)


def _dispatch_reply(
    *,
    create_draft: bool,
    suggested_reply: str,
    service: Any,
    msg: dict,
    thread_message_ids: list[str] | None,
    sync: Callable[[], bool],
    account_notifier: bool,
) -> str:
    if create_draft:
        return _create_draft_and_sync_unread(
            service, msg, suggested_reply, thread_message_ids, sync, account_notifier
        )
    return "analysis only"


def _dispatch_forward(*, apply: bool, sync: Callable[[], bool], account_notifier: bool) -> str:
    if apply:
        ok = sync()
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

    def sync() -> bool:
        return sync_thread_out_of_inbox(
            service, tmsgs, category=category, trusted_sender=trusted_sender
        )

    if category == "spam":
        return _dispatch_spam(
            trusted_sender=trusted_sender,
            account_notifier=account_notifier,
            create_draft=create_draft,
            apply=apply,
            suggested_reply=suggested_reply,
            service=service,
            msg=msg,
            thread_message_ids=thread_message_ids,
            sync=sync,
        )

    if action == "ignore":
        return _dispatch_ignore(apply=apply, sync=sync, account_notifier=account_notifier)

    if action == "mark_read":
        return _dispatch_mark_read(
            create_draft=create_draft,
            apply=apply,
            suggested_reply=suggested_reply,
            service=service,
            msg=msg,
            thread_message_ids=thread_message_ids,
            sync=sync,
            account_notifier=account_notifier,
        )

    if action == "reply":
        return _dispatch_reply(
            create_draft=create_draft,
            suggested_reply=suggested_reply,
            service=service,
            msg=msg,
            thread_message_ids=thread_message_ids,
            sync=sync,
            account_notifier=account_notifier,
        )

    if action == "forward":
        return _dispatch_forward(apply=apply, sync=sync, account_notifier=account_notifier)

    return "analysis only"
