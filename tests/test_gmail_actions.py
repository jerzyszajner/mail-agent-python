"""Tests for gmail_actions module."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from googleapiclient.errors import HttpError

from mail_agent.gmail_actions import archive, important_archive, report_spam


def _make_service_mock(side_effect=None):
    service = MagicMock()
    modify = service.users.return_value.messages.return_value.modify
    if side_effect:
        modify.return_value.execute.side_effect = side_effect
    return service, modify


def _http_error(status: int = 400) -> HttpError:
    resp = MagicMock()
    resp.status = status
    return HttpError(resp=resp, content=b"error")


class TestArchive(unittest.TestCase):
    def test_removes_inbox_only_keeps_unread(self):
        service, modify = _make_service_mock()
        ok, err = archive(service, "msg456")
        self.assertTrue(ok)
        self.assertIsNone(err)
        call_body = modify.call_args[1]["body"]
        self.assertEqual(call_body["removeLabelIds"], ["INBOX"])

    def test_returns_error_on_http_failure(self):
        service, _ = _make_service_mock(side_effect=_http_error(500))
        ok, err = archive(service, "msg456")
        self.assertFalse(ok)
        self.assertIn("500", err)


class TestImportantArchive(unittest.TestCase):
    def test_adds_important_removes_inbox(self):
        service, modify = _make_service_mock()
        ok, err = important_archive(service, "msg111")
        self.assertTrue(ok)
        self.assertIsNone(err)
        call_body = modify.call_args[1]["body"]
        self.assertIn("IMPORTANT", call_body["addLabelIds"])
        self.assertEqual(call_body["removeLabelIds"], ["INBOX"])

    def test_returns_error_on_http_failure(self):
        service, _ = _make_service_mock(side_effect=_http_error(403))
        ok, err = important_archive(service, "msg111")
        self.assertFalse(ok)
        self.assertIn("403", err)


class TestReportSpam(unittest.TestCase):
    def test_adds_spam_removes_inbox_keeps_unread(self):
        service, modify = _make_service_mock()
        ok, err = report_spam(service, "msg789")
        self.assertTrue(ok)
        self.assertIsNone(err)
        call_body = modify.call_args[1]["body"]
        self.assertIn("SPAM", call_body["addLabelIds"])
        self.assertEqual(call_body["removeLabelIds"], ["INBOX"])

    def test_returns_error_on_http_failure(self):
        service, _ = _make_service_mock(side_effect=_http_error(404))
        ok, err = report_spam(service, "msg789")
        self.assertFalse(ok)
        self.assertIn("404", err)


if __name__ == "__main__":
    unittest.main()
