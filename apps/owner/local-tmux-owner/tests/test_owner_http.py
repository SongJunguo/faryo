from __future__ import annotations

import gzip
from http import HTTPStatus
import io
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlparse


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import owner_http


class FixtureError(Exception):
    def __init__(self, message: str, status: HTTPStatus) -> None:
        super().__init__(message)
        self.status = status


class Handler:
    def __init__(self, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status = None
        self.response_headers: list[tuple[str, str]] = []

    def send_response(self, status) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.response_headers.append((name, value))

    def end_headers(self) -> None:
        return


def support(handler: Handler) -> owner_http.OwnerHttpSupport:
    return owner_http.OwnerHttpSupport(
        handler,
        error_factory=lambda message, status: FixtureError(message, status),
        token=lambda: "fixture-token",
        max_attachment_bytes=25 * 1024 * 1024,
    )


class OwnerHttpTest(unittest.TestCase):
    def test_safe_log_path_discards_private_query(self) -> None:
        self.assertEqual(owner_http.safe_log_path("/api/status?token=private&session=secret"), "/api/status")

    def test_security_headers_keep_owner_loopback_page_hardened(self) -> None:
        headers = owner_http.browser_security_headers()
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])

    def test_token_accepts_header_or_query_and_rejects_missing(self) -> None:
        support(Handler(headers={"X-Owner-Token": "fixture-token"})).require_token(urlparse("/api/status"))
        support(Handler()).require_token(urlparse("/api/status?token=fixture-token"))
        with self.assertRaises(FixtureError) as raised:
            support(Handler()).require_token(urlparse("/api/status"))
        self.assertEqual(raised.exception.status, HTTPStatus.UNAUTHORIZED)

    def test_json_reader_requires_an_object_and_bounded_length(self) -> None:
        body = json.dumps({"ok": True}).encode()
        handler = Handler(body, {"Content-Length": str(len(body))})
        self.assertEqual(support(handler).read_json(), {"ok": True})
        with self.assertRaises(FixtureError):
            support(Handler(b"[]", {"Content-Length": "2"})).read_json()
        with self.assertRaises(FixtureError) as raised:
            support(Handler(headers={"Content-Length": "1000001"})).read_json()
        self.assertEqual(raised.exception.status, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

    def test_large_json_response_is_gzipped_and_length_is_exact(self) -> None:
        handler = Handler(headers={"Accept-Encoding": "gzip"})
        support(handler).write_json({"ok": True, "text": "x" * 2000})
        headers = dict(handler.response_headers)
        self.assertEqual(handler.status, HTTPStatus.OK)
        self.assertEqual(headers["Content-Encoding"], "gzip")
        self.assertEqual(int(headers["Content-Length"]), len(handler.wfile.getvalue()))
        self.assertTrue(json.loads(gzip.decompress(handler.wfile.getvalue()))["ok"])


if __name__ == "__main__":
    unittest.main()
