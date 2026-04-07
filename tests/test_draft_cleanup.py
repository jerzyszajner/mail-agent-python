"""Tests for draft_cleanup heuristics."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import draft_cleanup
from draft_cleanup import (
    _load_pending,
    _save_pending,
    cleanup_sent_agent_drafts,
    register_agent_draft,
    thread_has_sent_newer_than,
)


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


class TestSavePending(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        self._orig_file = draft_cleanup.PENDING_DRAFTS_FILE
        draft_cleanup.PENDING_DRAFTS_FILE = os.path.join(self._tmp_dir, "pending.json")

    def tearDown(self):
        draft_cleanup.PENDING_DRAFTS_FILE = self._orig_file

    def test_save_load_roundtrip(self):
        rows = [{"draft_id": "d1", "thread_id": "t1", "draft_internal_ms": 1000}]
        _save_pending(rows)
        result = _load_pending()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["draft_id"], "d1")
        self.assertEqual(result[0]["thread_id"], "t1")

    def test_atomic_write_preserves_original_on_crash(self):
        original = [{"draft_id": "orig", "thread_id": "t0", "draft_internal_ms": 500}]
        _save_pending(original)

        tmp_path = draft_cleanup.PENDING_DRAFTS_FILE + ".tmp"
        with patch("json.dump", side_effect=OSError("disk full")):
            _save_pending([{"draft_id": "new", "thread_id": "t1", "draft_internal_ms": 999}])

        result = _load_pending()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["draft_id"], "orig")
        self.assertFalse(os.path.exists(tmp_path), "tmp file should be cleaned up")

    def test_deduplicates_draft_ids(self):
        rows = [
            {"draft_id": "dup", "thread_id": "t1", "draft_internal_ms": 100},
            {"draft_id": "dup", "thread_id": "t2", "draft_internal_ms": 200},
        ]
        _save_pending(rows)
        result = _load_pending()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["draft_id"], "dup")

    def test_register_agent_draft_idempotent(self):
        service = MagicMock()
        service.users().drafts().get.return_value.execute.return_value = {
            "message": {"internalDate": "1000"}
        }
        register_agent_draft(service, "d1", "t1")
        register_agent_draft(service, "d1", "t1")
        result = _load_pending()
        self.assertEqual(len(result), 1)

    def test_cleanup_removes_draft_when_sent_newer(self):
        _save_pending([{"draft_id": "d1", "thread_id": "t1", "draft_internal_ms": 1000}])

        service = MagicMock()
        service.users().drafts().get.return_value.execute.return_value = {
            "message": {"internalDate": "1000"}
        }
        service.users().threads().get.return_value.execute.return_value = {
            "messages": [{"labelIds": ["SENT"], "internalDate": "5000"}]
        }
        service.users().drafts().delete.return_value.execute.return_value = {}

        deleted = cleanup_sent_agent_drafts(service)
        self.assertEqual(deleted, 1)
        self.assertEqual(_load_pending(), [])


if __name__ == "__main__":
    unittest.main()
