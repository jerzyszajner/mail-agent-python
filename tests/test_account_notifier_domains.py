"""Tests for account-notifier domain detection (Google / Apple / Microsoft security mail)."""

from __future__ import annotations

import unittest

from account_notifier import sender_is_account_notifier


class TestAccountNotifierDomains(unittest.TestCase):
    def test_google_accounts(self):
        self.assertTrue(sender_is_account_notifier("no-reply@accounts.google.com"))

    def test_apple_id(self):
        self.assertTrue(sender_is_account_notifier("noreply@id.apple.com"))

    def test_microsoft_account_protection(self):
        self.assertTrue(
            sender_is_account_notifier(
                "account-security-noreply@accountprotection.microsoft.com"
            )
        )

    def test_random_domain_false(self):
        self.assertFalse(sender_is_account_notifier("x@example.com"))

    def test_subdomain_of_google_accounts(self):
        self.assertTrue(sender_is_account_notifier("x@mail.accounts.google.com"))


if __name__ == "__main__":
    unittest.main()
