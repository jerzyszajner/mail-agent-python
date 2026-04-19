"""Load optional trusted-sender allowlist from disk."""

from __future__ import annotations

import os

TRUSTED_SENDERS_FILE = "trusted_senders.txt"


def load_trusted_senders(path: str = TRUSTED_SENDERS_FILE) -> frozenset[str]:
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
