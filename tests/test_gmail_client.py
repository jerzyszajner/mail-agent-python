from __future__ import annotations

import base64
import unittest

from gmail_client import decode_full_message_body


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


class DecodeFullMessageBodyTests(unittest.TestCase):
    def test_returns_text_plain_body(self) -> None:
        message = {
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": _b64url("Hello from plain text")},
            }
        }

        body = decode_full_message_body(message)

        self.assertEqual(body, "Hello from plain text")

    def test_falls_back_to_text_html_when_plain_missing(self) -> None:
        message = {
            "payload": {
                "mimeType": "text/html",
                "body": {"data": _b64url("<p>Hello <b>HTML</b></p>")},
            }
        }

        body = decode_full_message_body(message)

        self.assertEqual(body, "Hello HTML")

    def test_prefers_text_plain_in_multipart(self) -> None:
        message = {
            "payload": {
                "mimeType": "multipart/alternative",
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {"data": _b64url("<div>HTML version</div>")},
                    },
                    {
                        "mimeType": "text/plain",
                        "body": {"data": _b64url("Plain version")},
                    },
                ],
            }
        }

        body = decode_full_message_body(message)

        self.assertEqual(body, "Plain version")

    def test_returns_empty_string_when_body_missing(self) -> None:
        message = {"payload": {"mimeType": "multipart/mixed", "parts": []}}

        body = decode_full_message_body(message)

        self.assertEqual(body, "")


if __name__ == "__main__":
    unittest.main()
