"""Gmail OAuth (Desktop) and authenticated API service construction."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httplib2
import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _load_cached_credentials() -> Credentials | None:
    if not os.path.exists("token.json"):
        return None
    try:
        with open("token.json") as f:
            data = json.load(f)
        return Credentials.from_authorized_user_info(data, SCOPES)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        try:
            os.remove("token.json")
        except OSError:
            pass
        return None


def _save_credentials(creds: Credentials) -> None:
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }
    fd = os.open("token.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)


def _http_timeout_seconds() -> float:
    raw = os.environ.get("GMAIL_HTTP_TIMEOUT", "120")
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 120.0


def _google_auth_request() -> Request:
    """google.auth refresh/OAuth HTTP with a finite timeout (avoids launchd hangs)."""
    timeout = _http_timeout_seconds()
    session = requests.Session()
    orig = session.request

    def request(method: str, url: str, **kwargs: Any):
        kwargs.setdefault("timeout", timeout)
        return orig(method, url, **kwargs)

    session.request = request  # type: ignore[method-assign]
    return Request(session=session)


def get_credentials() -> Credentials:
    """Load, refresh, or interactively obtain OAuth credentials. Writes token.json on change."""
    creds = _load_cached_credentials()
    auth_req = _google_auth_request()

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(auth_req)
            _save_credentials(creds)
        except RefreshError:
            creds = None
            try:
                os.remove("token.json")
            except OSError:
                pass
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(
                f"Gmail token refresh failed ({type(exc).__name__}: {exc}). "
                "Check network; token.json was not removed."
            ) from exc

    if not creds or not creds.valid:
        if not sys.stdin.isatty():
            raise RuntimeError(
                "Gmail login required but there is no interactive terminal; "
                "run gmail_analyze.py once from Terminal, then restart the agent."
            )
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        _save_credentials(creds)

    return creds


def build_gmail_service(creds: Credentials) -> Any:
    """Build a Gmail API service from credentials. Safe to call per-thread."""
    t = _http_timeout_seconds()
    authed_http = AuthorizedHttp(creds, http=httplib2.Http(timeout=t))
    return build("gmail", "v1", http=authed_http, cache_discovery=False)


def get_gmail_service() -> Any:
    return build_gmail_service(get_credentials())
