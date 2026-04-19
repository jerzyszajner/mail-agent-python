"""Single-thread analysis: Gemini classification, trusted ACK drafts, Gmail dispatch."""

from __future__ import annotations

import sys
from typing import Any

from .analysis import (
    analyze_email_block,
    compose_suggested_reply,
    generate_trusted_acknowledgment_reply,
)
from .gmail_client import get_header
from .inbox_dispatch import archive_thread_inbox_messages, dispatch_thread_action
from .inbox_thread import extract_email, thread_to_email_text


def analyze_single_thread(
    service: Any,
    thread: dict,
    my_email: str,
    *,
    create_draft: bool,
    apply: bool,
    reply_name: str,
    trusted_senders: frozenset[str],
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

    conversation_block, last_body, reply_target, thread_msg_ids = thread_to_email_text(
        messages, my_email
    )

    target_headers = (reply_target.get("payload") or {}).get("headers") or []
    sender = get_header(target_headers, "From")
    subject = get_header(target_headers, "Subject")
    sender_email = extract_email(sender).lower()
    trusted_sender = bool(trusted_senders and sender_email in trusted_senders)

    if not last_body.strip():
        print(f"Note: no body for thread {thread.get('id')} (attachments only).", file=sys.stderr)

    result = analyze_email_block(conversation_block, source_body=last_body)

    if result.error:
        if result.suspicious and apply:
            archive_thread_inbox_messages(service, messages)
            result_desc = "blocked (suspicious) — archived (unread)"
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
    # Trusted thanks/FYI drafts only if main analysis did not flag injection (no parsed path then).
    trusted_thanks = (
        trusted_sender
        and category == "spam"
        and action == "ignore"
        and not result.suspicious
    )
    trusted_fyi_ack = (
        trusted_sender
        and category == "normal"
        and action == "mark_read"
        and not result.suspicious
    )
    if action == "reply" and not result.suspicious:
        suggested_reply = compose_suggested_reply(parsed, reply_name)
    elif (trusted_thanks or trusted_fyi_ack) and create_draft:
        thanks_text, thanks_err = generate_trusted_acknowledgment_reply(
            conversation_block, reply_name
        )
        if thanks_text:
            suggested_reply = thanks_text
        elif thanks_err:
            print(
                f"Trusted-sender draft skipped: {thanks_err}",
                file=sys.stderr,
            )

    effective_draft = create_draft and not result.suspicious and (
        action == "reply" or trusted_thanks or trusted_fyi_ack
    )

    action_result = dispatch_thread_action(
        service,
        reply_target,
        action,
        category,
        create_draft=effective_draft,
        apply=apply,
        suggested_reply=suggested_reply,
        thread_message_ids=thread_msg_ids,
        trusted_sender=trusted_sender,
        sender_email=sender_email,
        thread_messages=messages,
    )

    return {
        "from": sender,
        "subject": subject,
        "category": parsed.get("category"),
        "urgency": parsed.get("urgency"),
        "action": parsed.get("action"),
        "suggested_reply": suggested_reply,
        "result": action_result,
    }
