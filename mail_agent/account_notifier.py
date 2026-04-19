"""Detect senders of official account / security notifications (never treat as spam)."""

from __future__ import annotations

# Domains for security and account mail; subdomains match (e.g. x.mail.accounts.google.com).
ACCOUNT_NOTIFIER_DOMAINS: frozenset[str] = frozenset(
    {
        "accounts.google.com",
        "id.apple.com",
        "accountprotection.microsoft.com",
    }
)


def _host_matches_account_notifier(host: str) -> bool:
    h = host.lower().strip(".")
    if not h:
        return False
    if h in ACCOUNT_NOTIFIER_DOMAINS:
        return True
    return any(h.endswith("." + d) for d in ACCOUNT_NOTIFIER_DOMAINS)


def sender_is_account_notifier(sender_email: str) -> bool:
    addr = sender_email.strip().lower()
    if "@" not in addr:
        return False
    return _host_matches_account_notifier(addr.rsplit("@", 1)[-1])
