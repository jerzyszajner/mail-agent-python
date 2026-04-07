"""Batch INBOX analysis: fetch unread threads, classify with Gemini, apply Gmail actions."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from datetime import datetime
import re
import sys
from typing import Any

import httplib2
import requests
from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from account_notifier import sender_is_account_notifier
from analysis import (
    analyze_email_block,
    compose_suggested_reply,
    generate_trusted_acknowledgment_reply,
)
from draft_cleanup import cleanup_sent_agent_drafts
from drafts import create_reply_draft
from gmail_actions import archive, important_archive, report_spam
from gmail_client import decode_full_message_body, get_header

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
MAX_EMAIL_BODY_LEN = 32_000
DEFAULT_MAX_RESULTS = 10
DEFAULT_MAX_WORKERS = 5

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
TRUSTED_SENDERS_FILE = "trusted_senders.txt"


def _load_trusted_senders(path: str = TRUSTED_SENDERS_FILE) -> frozenset[str]:
    """One email per line; # starts comment. Missing file → empty set."""
    if not os.path.isfile(path):
        return frozenset()
    out: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if line:
                out.add(line.lower())
    return frozenset(out)


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


def _http_timeout_seconds() -> float:
    raw = os.environ.get("GMAIL_HTTP_TIMEOUT", "120")
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 120.0


def _google_auth_request() -> Request:
    """google.auth refresh/OAuth HTTP with a finite timeout (avoids launchd hangs)."""
    timeout = _http_timeout_seconds()
    session = requests.Session()
    orig = session.request

    def request(method: str, url: str, **kwargs: Any):
        kwargs.setdefault("timeout", timeout)
        return orig(method, url, **kwargs)

    session.request = request  # type: ignore[method-assign]
    return Request(session=session)


def _get_credentials() -> Credentials:
    """Load, refresh, or interactively obtain OAuth credentials. Writes token.json on change."""
    creds = _load_cached_credentials()
    auth_req = _google_auth_request()

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(auth_req)
            _save_credentials(creds)
        except RefreshError:
            creds = None
            try:
                os.remove("token.json")
            except OSError:
                pass
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(
                f"Gmail token refresh failed ({type(exc).__name__}: {exc}). "
                "Check network; token.json was not removed."
            ) from exc

    if not creds or not creds.valid:
        if not sys.stdin.isatty():
            raise RuntimeError(
                "Gmail login required but there is no interactive terminal; "
                "run gmail_analyze.py once from Terminal, then restart the agent."
            )
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        _save_credentials(creds)

    return creds


def _build_service(creds: Credentials) -> Any:
    """Build a Gmail API service from credentials. Safe to call per-thread."""
    t = _http_timeout_seconds()
    authed_http = AuthorizedHttp(creds, http=httplib2.Http(timeout=t))
    return build("gmail", "v1", http=authed_http, cache_discovery=False)


def get_gmail_service() -> Any:
    return _build_service(_get_credentials())


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


def _archive_thread_inbox_messages(service, messages: list[dict]) -> None:
    """Remove INBOX from each message that still has it (keeps UNREAD)."""
    for msg in messages:
        if "INBOX" in (msg.get("labelIds") or []):
            archive(service, msg["id"])


def _sync_thread_out_of_inbox(
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
        addr = _extract_email(from_addr).lower()
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
    trusted_sender: bool = False,
    sender_email: str = "",
    thread_messages: list[dict] | None = None,
) -> str:
    """Execute the appropriate Gmail operation and return a result description."""
    account_notifier = sender_is_account_notifier(sender_email)
    tmsgs = thread_messages if thread_messages is not None else [msg]

    def _sync() -> bool:
        return _sync_thread_out_of_inbox(
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


def _analyze_single(
    service,
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

    conversation_block, last_body, reply_target, thread_msg_ids = _thread_to_email_text(
        messages, my_email
    )

    target_headers = (reply_target.get("payload") or {}).get("headers") or []
    sender = get_header(target_headers, "From")
    subject = get_header(target_headers, "Subject")
    sender_email = _extract_email(sender).lower()
    trusted_sender = bool(trusted_senders and sender_email in trusted_senders)

    if not last_body.strip():
        print(f"Note: no body for thread {thread.get('id')} (attachments only).", file=sys.stderr)

    result = analyze_email_block(conversation_block, source_body=last_body)

    if result.error:
        if result.suspicious and apply:
            _archive_thread_inbox_messages(service, messages)
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
    trusted_thanks = (
        trusted_sender
        and category == "spam"
        and action == "ignore"
        and not result.suspicious
    )
    if action == "reply" and not result.suspicious:
        suggested_reply = compose_suggested_reply(parsed, reply_name)
    elif trusted_thanks and create_draft:
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
        action == "reply" or trusted_thanks
    )

    action_result = _dispatch_action(
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


def analyze_inbox(
    max_results: int = DEFAULT_MAX_RESULTS,
    create_draft: bool = False,
    apply: bool = False,
    trusted_senders: frozenset[str] | None = None,
) -> int:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    banner = f"=== gmail_analyze run started {stamp} ==="
    print(banner, file=sys.stderr)
    print(banner, flush=True)

    try:
        creds = _get_credentials()
        service = _build_service(creds)
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

    n_cleaned = cleanup_sent_agent_drafts(service)
    if n_cleaned:
        print(
            f"Draft cleanup: removed {n_cleaned} agent draft(s) after detecting send in thread.",
            file=sys.stderr,
        )

    threads, had_error = _fetch_unread_threads(service, max_results)
    if not threads:
        if had_error:
            return 1
        print("No unread messages in INBOX.", flush=True)
        return 0

    reply_name = os.environ.get("REPLY_NAME") or ""
    trusted = trusted_senders if trusted_senders is not None else _load_trusted_senders()
    max_workers = int(os.environ.get("GMAIL_MAX_WORKERS", DEFAULT_MAX_WORKERS))
    total = len(threads)

    def _worker(args: tuple[int, dict]) -> dict[str, Any]:
        i, thread = args
        subject = ""
        thread_service = None
        try:
            msgs = thread.get("messages") or []
            last_msg = sorted(msgs, key=lambda m: int(m.get("internalDate", "0")))[-1] if msgs else {}
            last_headers = (last_msg.get("payload") or {}).get("headers") or []
            subject = get_header(last_headers, "Subject")
            msg_count = len(msgs)
            print(f"[{i}/{total}] Analyzing thread ({msg_count} msgs): {subject}", file=sys.stderr)
            thread_service = _build_service(creds)
            entry = _analyze_single(
                thread_service,
                thread,
                my_email,
                create_draft=create_draft,
                apply=apply,
                reply_name=reply_name,
                trusted_senders=trusted,
            )
            print(f"  -> [{i}/{total}] {entry['category']} / {entry['action']} -> {entry['result']}", file=sys.stderr)
            return entry
        except Exception as exc:
            print(f"[{i}/{total}] Worker failed for thread {thread.get('id', '?')}: {exc}", file=sys.stderr)
            return {
                "thread_id": thread.get("id", ""),
                "subject": subject,
                "category": "error",
                "action": "none",
                "result": f"worker_error: {exc}",
            }
        finally:
            if thread_service is not None:
                try:
                    http = getattr(getattr(thread_service, "_http", None), "http", None)
                    if http and hasattr(http, "connections"):
                        http.connections.clear()
                except Exception:
                    pass

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(_worker, enumerate(threads, start=1)))
    except Exception as exc:
        print(f"Fatal error in thread pool: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)
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
        help="Create Gmail draft replies for 'reply' (and trusted-sender spam thanks). Each successful draft removes the thread from INBOX (UNREAD kept).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute Gmail actions: spam, archive, mark_read, forward when chosen. Archive/spam keep UNREAD. Without --draft and without this flag, no Gmail changes.",
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
