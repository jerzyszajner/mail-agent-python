"""Thread-wide INBOX removal (_sync_thread_out_of_inbox)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from gmail_analyze import _sync_thread_out_of_inbox


class TestSyncThreadOutOfInbox(unittest.TestCase):
    def test_syncs_all_inbox_messages_with_important_for_notifier(self):
        service = MagicMock()
        modify = service.users.return_value.messages.return_value.modify
        modify.return_value.execute.return_value = {}

        m1 = {
            "id": "a",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "Google <no-reply@accounts.google.com>"}
                ]
            },
        }
        m2 = {
            "id": "b",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "Google <no-reply@accounts.google.com>"}
                ]
            },
        }
        ok = _sync_thread_out_of_inbox(
            service, [m1, m2], category="normal", trusted_sender=False
        )
        self.assertTrue(ok)
        self.assertEqual(modify.call_count, 2)
        for call in modify.call_args_list:
            body = call[1]["body"]
            self.assertIn("IMPORTANT", body["addLabelIds"])
            self.assertEqual(body["removeLabelIds"], ["INBOX"])

    def test_skips_messages_without_inbox(self):
        service = MagicMock()
        modify = service.users.return_value.messages.return_value.modify
        modify.return_value.execute.return_value = {}

        m1 = {
            "id": "a",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [{"name": "From", "value": "x <a@example.com>"}]
            },
        }
        m2 = {
            "id": "b",
            "labelIds": ["UNREAD"],
            "payload": {
                "headers": [{"name": "From", "value": "x <a@example.com>"}]
            },
        }
        ok = _sync_thread_out_of_inbox(
            service, [m1, m2], category="normal", trusted_sender=False
        )
        self.assertTrue(ok)
        self.assertEqual(modify.call_count, 1)


if __name__ == "__main__":
    unittest.main()
