"""Trusted sender + mark_read: optional thanks draft in _dispatch_action."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

_GMAIL_PATCHES = [
    patch.dict(
        "sys.modules",
        {
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
        },
    )
]

for _p in _GMAIL_PATCHES:
    _p.start()

import gmail_analyze  # noqa: E402

for _p in _GMAIL_PATCHES:
    _p.stop()


class TestTrustedMarkReadDraft(unittest.TestCase):
    def test_mark_read_with_suggested_reply_creates_draft_then_archives(self):
        service = MagicMock()
        msg = {"id": "m1", "threadId": "t1", "payload": {"headers": []}}

        with patch.object(gmail_analyze, "sender_is_account_notifier", return_value=False), patch.object(
            gmail_analyze, "create_reply_draft", return_value=("draft-1", False)
        ) as crd, patch.object(gmail_analyze, "_sync_thread_out_of_inbox", return_value=True) as sync:
            out = gmail_analyze._dispatch_action(
                service,
                msg,
                "mark_read",
                "normal",
                create_draft=True,
                apply=True,
                suggested_reply="Thanks for the link!",
                thread_messages=[msg],
            )

        self.assertEqual(out, "draft created (draft-1) | archived (unread)")
        crd.assert_called_once()
        sync.assert_called_once()

    def test_mark_read_without_suggested_reply_skips_draft(self):
        service = MagicMock()
        msg = {"id": "m1", "threadId": "t1", "payload": {"headers": []}}

        with patch.object(gmail_analyze, "sender_is_account_notifier", return_value=False), patch.object(
            gmail_analyze, "create_reply_draft"
        ) as crd, patch.object(gmail_analyze, "_sync_thread_out_of_inbox", return_value=True):
            out = gmail_analyze._dispatch_action(
                service,
                msg,
                "mark_read",
                "normal",
                create_draft=True,
                apply=True,
                suggested_reply="",
                thread_messages=[msg],
            )

        self.assertEqual(out, "archived (unread)")
        crd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
