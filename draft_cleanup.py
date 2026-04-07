"""Track agent-created Gmail drafts and remove them once a newer SENT exists in the thread."""

from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any

from googleapiclient.errors import HttpError

PENDING_DRAFTS_FILE = "agent_pending_drafts.json"
_pending_drafts_lock = threading.Lock()


def _load_pending() -> list[dict[str, Any]]:
    if not os.path.isfile(PENDING_DRAFTS_FILE):
        return []
    try:
        with open(PENDING_DRAFTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict) and x.get("draft_id") and x.get("thread_id")]


def _save_pending(rows: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        did = str(row.get("draft_id", ""))
        if not did or did in seen:
            continue
        seen.add(did)
        unique.append(row)
    try:
        with open(PENDING_DRAFTS_FILE, "w", encoding="utf-8") as f:
            json.dump(unique, f, indent=2)
    except OSError as exc:
        print(f"Could not save {PENDING_DRAFTS_FILE}: {exc}", file=sys.stderr)


def register_agent_draft(service: Any, draft_id: str | None, thread_id: str | None) -> None:
    """Record a draft created by this app for later cleanup. No-op if IDs missing or API fails."""
    if not draft_id or not thread_id:
        return
    with _pending_drafts_lock:
        rows = _load_pending()
        if any(str(r.get("draft_id")) == draft_id for r in rows):
            return
        try:
            dg = (
                service.users()
                .drafts()
                .get(userId="me", id=draft_id, format="metadata")
                .execute()
            )
        except HttpError:
            return
        msg = dg.get("message") or {}
        ms = int(msg.get("internalDate") or 0)
        if ms <= 0:
            return
        rows.append(
            {"draft_id": draft_id, "thread_id": thread_id, "draft_internal_ms": ms}
        )
        _save_pending(rows)


def thread_has_sent_newer_than(service: Any, thread_id: str, draft_ref_ms: int) -> bool:
    """True if the thread contains a SENT message strictly newer than draft_ref_ms."""
    try:
        th = (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format="metadata")
            .execute()
        )
    except HttpError:
        return False
    for m in th.get("messages") or []:
        if "SENT" not in (m.get("labelIds") or []):
            continue
        if int(m.get("internalDate") or 0) > draft_ref_ms:
            return True
    return False


def cleanup_sent_agent_drafts(service: Any) -> int:
    """
    Delete pending agent drafts when the thread already has a newer SENT message
    (e.g. user sent from Apple Mail). Removes entries for missing drafts (404).
    Returns how many drafts were deleted.
    """
    with _pending_drafts_lock:
        pending = _load_pending()
        if not pending:
            return 0
        kept: list[dict[str, Any]] = []
        deleted = 0
        for row in pending:
            draft_id = str(row["draft_id"])
            thread_id = str(row["thread_id"])
            draft_ms = int(row.get("draft_internal_ms") or 0)
            try:
                dg = (
                    service.users()
                    .drafts()
                    .get(userId="me", id=draft_id, format="metadata")
                    .execute()
                )
            except HttpError as exc:
                if getattr(exc.resp, "status", None) == 404:
                    continue
                kept.append(row)
                continue
            msg = dg.get("message") or {}
            cur_ms = int(msg.get("internalDate") or 0)
            draft_ref_ms = max(draft_ms, cur_ms)
            if thread_has_sent_newer_than(service, thread_id, draft_ref_ms):
                try:
                    service.users().drafts().delete(userId="me", id=draft_id).execute()
                    deleted += 1
                except HttpError as exc:
                    if getattr(exc.resp, "status", None) != 404:
                        kept.append(row)
            else:
                kept.append(row)
        _save_pending(kept)
        return deleted
