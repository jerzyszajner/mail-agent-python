"""Gmail API helpers: decode message bodies from users.messages.get(format='full')."""

from __future__ import annotations

import base64
import html
import re
from typing import Any


def _pad_base64url(s: str) -> str:
    pad_len = (4 - len(s) % 4) % 4
    return s + ("=" * pad_len)


def decode_base64url_data(data: str | None) -> bytes:
    """Decode Gmail ``body.data`` (URL-safe base64, padding optional)."""
    if not data:
        return b""
    return base64.urlsafe_b64decode(_pad_base64url(data))


def _base_mime(part: dict[str, Any]) -> str:
    raw = (part.get("mimeType") or "").strip().lower()
    return raw.split(";", 1)[0].strip()


def _charset_from_part(part: dict[str, Any]) -> str:
    for h in part.get("headers") or []:
        if (h.get("name") or "").lower() != "content-type":
            continue
        value = h.get("value") or ""
        m = re.search(r"charset\s*=\s*([\w.-]+)", value, re.I)
        if m:
            return m.group(1).strip("\"'")
    return "utf-8"


def _bytes_to_text(data: bytes, part: dict[str, Any]) -> str:
    enc = _charset_from_part(part)
    try:
        return data.decode(enc)
    except (LookupError, UnicodeDecodeError):
        return data.decode("utf-8", errors="replace")


def _strip_html(html_str: str) -> str:
    no_scripts = re.sub(
        r"<script\b[^>]*>.*?</script>",
        "",
        html_str,
        flags=re.DOTALL | re.IGNORECASE,
    )
    no_styles = re.sub(
        r"<style\b[^>]*>.*?</style>",
        "",
        no_scripts,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", no_styles)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _collect_body_parts(
    part: dict[str, Any],
    plain_parts: list[str],
    html_parts: list[str],
) -> None:
    mime = _base_mime(part)
    body = part.get("body") or {}
    raw_b64 = body.get("data")
    # Parts with only attachmentId need files().get; skip here.
    if raw_b64:
        chunk = decode_base64url_data(raw_b64)
        if chunk:
            if mime == "text/plain":
                plain_parts.append(_bytes_to_text(chunk, part))
            elif mime == "text/html":
                html_parts.append(_bytes_to_text(chunk, part))

    for sub in part.get("parts") or []:
        _collect_body_parts(sub, plain_parts, html_parts)


def decode_full_message_body(message: dict[str, Any]) -> str:
    """
    Return the message body text from a Gmail API full message resource.

    Walks multipart payloads recursively, decodes base64url ``body.data``,
    prefers ``text/plain``, and falls back to ``text/html`` with tags stripped.
    """
    payload = message.get("payload")
    if not payload:
        return ""

    plain_parts: list[str] = []
    html_parts: list[str] = []
    _collect_body_parts(payload, plain_parts, html_parts)

    if plain_parts:
        return "\n\n".join(p for p in plain_parts if p.strip())

    if html_parts:
        return "\n\n".join(_strip_html(h) for h in html_parts if h.strip())

    return ""
