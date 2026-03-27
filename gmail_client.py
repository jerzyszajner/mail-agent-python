"""Gmail API helpers: decode message bodies from users.messages.get(format='full')."""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any

from bs4 import BeautifulSoup, Comment


def _pad_base64url(s: str) -> str:
    pad_len = (4 - len(s) % 4) % 4
    return s + ("=" * pad_len)


def decode_base64url_data(data: str | None) -> bytes:
    """Decode Gmail ``body.data`` (URL-safe base64, padding optional)."""
    if not data:
        return b""
    try:
        return base64.urlsafe_b64decode(_pad_base64url(data))
    except (binascii.Error, ValueError):
        return b""


def _base_mime(part: dict[str, Any]) -> str:
    raw = (part.get("mimeType") or "").strip().lower()
    return raw.split(";", 1)[0].strip()


def _charset_from_part(part: dict[str, Any]) -> str:
    for value in _header_values(part, "content-type"):
        m = re.search(r"charset\s*=\s*([^\s;]+)", value, re.I)
        if m:
            return m.group(1).strip("\"'")
    return "utf-8"


def _header_values(part: dict[str, Any], name: str) -> list[str]:
    expected = name.lower()
    out: list[str] = []
    for h in part.get("headers") or []:
        if (h.get("name") or "").lower() == expected:
            value = h.get("value")
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
    return out


def _is_attachment_part(part: dict[str, Any]) -> bool:
    filename = (part.get("filename") or "").strip()
    if filename:
        return True

    for value in _header_values(part, "content-disposition"):
        lowered = value.lower()
        if "attachment" in lowered:
            return True
    return False


def _normalize_text(text: str) -> str:
    # Keep paragraphs while collapsing noisy whitespace from MIME decoders.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u0000", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _bytes_to_text(data: bytes, part: dict[str, Any]) -> str:
    enc = _charset_from_part(part)
    try:
        decoded = data.decode(enc)
    except (LookupError, UnicodeDecodeError):
        decoded = data.decode("utf-8", errors="replace")
    return _normalize_text(decoded)


_HIDDEN_STYLE_RE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden"
    r"|opacity\s*:\s*0(?=[;\s\"'\)]|$)"
    r"|font-size\s*:\s*0(?=[;\s\"'\)]|$)",
    re.IGNORECASE,
)


def _style_attr_value(tag: Any) -> str:
    """Return inline ``style`` as a string; tolerate Tags with missing or broken ``attrs``."""
    attrs = getattr(tag, "attrs", None)
    if not isinstance(attrs, dict):
        return ""
    val = attrs.get("style", "")
    if isinstance(val, list):
        return " ".join(str(v) for v in val)
    return str(val) if val else ""


def _strip_html(html_str: str) -> str:
    soup = BeautifulSoup(html_str, "html.parser")
    for element in soup.find_all(string=lambda t: isinstance(t, Comment)):
        element.extract()
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(style=True):
        if _HIDDEN_STYLE_RE.search(_style_attr_value(tag)):
            tag.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def _collect_body_parts(
    part: dict[str, Any],
    plain_parts: list[str],
    html_parts: list[str],
) -> None:
    if _is_attachment_part(part):
        return

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


def get_header(headers: list[dict], name: str) -> str:
    """Return the first header value matching *name* (case-insensitive)."""
    name_l = name.lower()
    for h in headers:
        if (h.get("name") or "").lower() == name_l:
            return h.get("value") or ""
    return ""


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
