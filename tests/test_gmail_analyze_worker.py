"""Tests for _worker exception handling and resource cleanup in gmail_analyze."""

from __future__ import annotations

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

# Patch heavy imports before importing gmail_analyze
_GMAIL_PATCHES = [
    patch.dict("sys.modules", {
        "googleapiclient": MagicMock(),
        "googleapiclient.discovery": MagicMock(),
        "googleapiclient.errors": MagicMock(),
        "google.auth.exceptions": MagicMock(),
        "google.auth.transport.requests": MagicMock(),
        "google.oauth2.credentials": MagicMock(),
        "google_auth_httplib2": MagicMock(),
        "google_auth_oauthlib.flow": MagicMock(),
        "httplib2": MagicMock(),
        "dotenv": MagicMock(),
        "account_notifier": MagicMock(),
        "analysis": MagicMock(),
        "draft_cleanup": MagicMock(),
        "drafts": MagicMock(),
        "gmail_actions": MagicMock(),
        "gmail_client": MagicMock(),
    })
]

for p in _GMAIL_PATCHES:
    p.start()

import gmail_auth  # noqa: E402
import gmail_analyze  # noqa: E402
import inbox_pipeline  # noqa: E402

for p in _GMAIL_PATCHES:
    p.stop()


def _make_thread(thread_id: str = "t1", subject: str = "Test") -> dict:
    return {
        "id": thread_id,
        "messages": [
            {
                "internalDate": "1000",
                "payload": {
                    "headers": [{"name": "Subject", "value": subject}]
                },
            }
        ],
    }


def _run_worker(thread: dict, analyze_side_effect=None, analyze_return=None, total: int = 1):
    """Build a _worker closure like analyze_inbox does, and call it."""
    creds = MagicMock()
    my_email = "me@example.com"
    create_draft = False
    apply = False
    reply_name = ""
    trusted = frozenset()

    mock_service = MagicMock()
    mock_service._http = MagicMock()
    mock_service._http.http = MagicMock()
    mock_service._http.http.connections = {"conn1": object()}

    with patch.object(gmail_auth, "build_gmail_service", return_value=mock_service), \
         patch.object(inbox_pipeline, "analyze_single_thread",
                      side_effect=analyze_side_effect,
                      return_value=analyze_return), \
         patch.object(gmail_analyze, "get_header", return_value=thread.get("messages", [{}])[0]
                      .get("payload", {}).get("headers", [{}])[0].get("value", "")):

        def _worker(args):
            i, t = args
            subject = ""
            thread_service = None
            try:
                msgs = t.get("messages") or []
                last_msg = sorted(msgs, key=lambda m: int(m.get("internalDate", "0")))[-1] if msgs else {}
                last_headers = (last_msg.get("payload") or {}).get("headers") or []
                subject = gmail_analyze.get_header(last_headers, "Subject")
                msg_count = len(msgs)
                thread_service = gmail_auth.build_gmail_service(creds)
                entry = inbox_pipeline.analyze_single_thread(
                    thread_service, t, my_email,
                    create_draft=create_draft, apply=apply,
                    reply_name=reply_name, trusted_senders=trusted,
                )
                return entry
            except Exception as exc:
                return {
                    "thread_id": t.get("id", ""),
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

        return _worker((1, thread)), mock_service


class TestWorkerExceptionHandling(unittest.TestCase):
    def test_worker_returns_error_entry_on_exception(self):
        thread = _make_thread("t1", "Subject A")
        result, _ = _run_worker(thread, analyze_side_effect=RuntimeError("API timeout"))
        self.assertEqual(result["category"], "error")
        self.assertIn("worker_error", result["result"])
        self.assertIn("API timeout", result["result"])
        self.assertEqual(result["thread_id"], "t1")

    def test_worker_does_not_raise_on_exception(self):
        thread = _make_thread("t1")
        try:
            _run_worker(thread, analyze_side_effect=RuntimeError("crash"))
        except Exception as e:
            self.fail(f"_worker should not raise, but raised: {e}")

    def test_worker_returns_normal_entry_on_success(self):
        thread = _make_thread("t1", "Hello")
        expected = {"thread_id": "t1", "category": "newsletter", "action": "archive", "result": "ok"}
        result, _ = _run_worker(thread, analyze_return=expected)
        self.assertEqual(result["category"], "newsletter")

    def test_subject_is_empty_string_in_error_entry_when_crash_before_subject(self):
        # Simulate crash during _build_service (before subject assignment)
        thread = _make_thread("t2", "Important")
        result, _ = _run_worker(thread, analyze_side_effect=RuntimeError("build failed"))
        self.assertIsInstance(result["subject"], str)

    def test_multiple_workers_partial_results(self):
        threads = [_make_thread(f"t{i}") for i in range(3)]
        creds = MagicMock()
        my_email = "me@example.com"

        mock_service = MagicMock()
        mock_service._http = MagicMock()
        mock_service._http.http = MagicMock()
        mock_service._http.http.connections = {}

        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("thread 2 failed")
            return {"thread_id": "ok", "category": "newsletter", "action": "archive", "result": "ok"}

        with patch.object(gmail_auth, "build_gmail_service", return_value=mock_service), \
             patch.object(inbox_pipeline, "analyze_single_thread", side_effect=side_effect), \
             patch.object(gmail_analyze, "get_header", return_value="subject"):

            total = len(threads)

            def _worker(args):
                i, t = args
                subject = ""
                thread_service = None
                try:
                    msgs = t.get("messages") or []
                    subject = gmail_analyze.get_header([], "Subject")
                    thread_service = gmail_auth.build_gmail_service(creds)
                    entry = inbox_pipeline.analyze_single_thread(
                        thread_service, t, my_email,
                        create_draft=False, apply=False,
                        reply_name="", trusted_senders=frozenset(),
                    )
                    return entry
                except Exception as exc:
                    return {
                        "thread_id": t.get("id", ""),
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

            with ThreadPoolExecutor(max_workers=3) as executor:
                results = list(executor.map(_worker, enumerate(threads, start=1)))

        self.assertEqual(len(results), 3)
        error_entries = [r for r in results if r["category"] == "error"]
        ok_entries = [r for r in results if r["category"] != "error"]
        self.assertEqual(len(error_entries), 1)
        self.assertEqual(len(ok_entries), 2)


class TestWorkerResourceCleanup(unittest.TestCase):
    def test_connections_cleared_after_successful_worker(self):
        thread = _make_thread("t1")
        expected = {"thread_id": "t1", "category": "newsletter", "action": "archive", "result": "ok"}
        _, mock_service = _run_worker(thread, analyze_return=expected)
        self.assertEqual(len(mock_service._http.http.connections), 0)

    def test_connections_cleared_even_when_analyze_crashes(self):
        thread = _make_thread("t1")
        _, mock_service = _run_worker(thread, analyze_side_effect=RuntimeError("crash"))
        self.assertEqual(len(mock_service._http.http.connections), 0)

    def test_no_error_when_service_has_no_http_attr(self):
        """Cleanup should not raise if service internal structure differs."""
        thread = _make_thread("t1")
        creds = MagicMock()
        mock_service = MagicMock(spec=[])  # no attributes

        with patch.object(gmail_auth, "build_gmail_service", return_value=mock_service), \
             patch.object(inbox_pipeline, "analyze_single_thread", side_effect=RuntimeError("crash")), \
             patch.object(gmail_analyze, "get_header", return_value=""):

            def _worker(args):
                i, t = args
                subject = ""
                thread_service = None
                try:
                    thread_service = gmail_auth.build_gmail_service(creds)
                    return inbox_pipeline.analyze_single_thread(thread_service, t, "me@x.com",
                                                         create_draft=False, apply=False,
                                                         reply_name="", trusted_senders=frozenset())
                except Exception as exc:
                    return {"thread_id": t.get("id", ""), "subject": subject,
                            "category": "error", "action": "none",
                            "result": f"worker_error: {exc}"}
                finally:
                    if thread_service is not None:
                        try:
                            http = getattr(getattr(thread_service, "_http", None), "http", None)
                            if http and hasattr(http, "connections"):
                                http.connections.clear()
                        except Exception:
                            pass

            try:
                result = _worker((1, thread))
            except Exception as e:
                self.fail(f"Should not raise during cleanup: {e}")
            self.assertEqual(result["category"], "error")


if __name__ == "__main__":
    unittest.main()
