"""Batch INBOX analysis: fetch unread threads, classify with Gemini, apply Gmail actions."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from datetime import datetime
import sys
from typing import Any

from dotenv import load_dotenv
from googleapiclient.errors import HttpError

from draft_cleanup import cleanup_sent_agent_drafts
from gmail_auth import build_gmail_service, get_credentials, get_gmail_service
from gmail_client import get_header
from inbox_pipeline import analyze_single_thread
from inbox_thread import fetch_unread_threads
from trusted_senders import load_trusted_senders

DEFAULT_MAX_RESULTS = 10
DEFAULT_MAX_WORKERS = 5


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
        creds = get_credentials()
        service = build_gmail_service(creds)
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

    threads, had_error = fetch_unread_threads(service, max_results)
    if not threads:
        if had_error:
            return 1
        print("No unread messages in INBOX.", flush=True)
        return 0

    reply_name = os.environ.get("REPLY_NAME") or ""
    trusted = trusted_senders if trusted_senders is not None else load_trusted_senders()
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
            thread_service = build_gmail_service(creds)
            entry = analyze_single_thread(
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
        help="Create Gmail draft replies for 'reply', trusted-sender spam thanks, and trusted-sender normal FYI (mark_read). Each successful draft removes the thread from INBOX (UNREAD kept).",
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


__all__ = ["analyze_inbox", "get_gmail_service", "main", "get_header"]

if __name__ == "__main__":
    raise SystemExit(main())
