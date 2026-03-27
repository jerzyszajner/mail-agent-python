"""Tests for draft_cleanup heuristics."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from draft_cleanup import thread_has_sent_newer_than


def _service_with_messages(messages: list) -> MagicMock:
    service = MagicMock()
    service.users().threads().get.return_value.execute.return_value = {
        "messages": messages
    }
    return service


class TestThreadHasSentNewerThan(unittest.TestCase):
    def test_no_sent(self):
        service = _service_with_messages(
            [{"labelIds": ["INBOX"], "internalDate": "9999"}]
        )
        self.assertFalse(thread_has_sent_newer_than(service, "t1", 1))

    def test_sent_older_than_draft(self):
        service = _service_with_messages(
            [{"labelIds": ["SENT"], "internalDate": "1000"}]
        )
        self.assertFalse(thread_has_sent_newer_than(service, "tid", 3000))

    def test_sent_newer_than_draft(self):
        service = _service_with_messages(
            [{"labelIds": ["SENT"], "internalDate": "5000"}]
        )
        self.assertTrue(thread_has_sent_newer_than(service, "tid", 3000))


if __name__ == "__main__":
    unittest.main()
