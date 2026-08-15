#!/usr/bin/env python3
"""Gateway CSRF security-boundary regression tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import importlib.util
import json
import re
import secrets
import threading
import time
import unittest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[4]
SERVER_PATH = REPO_ROOT / "apps" / "gateway" / "server" / "server.py"

spec = importlib.util.spec_from_file_location("faryo_gateway_server", SERVER_PATH)
gateway = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(gateway)


class StubConfig:
    def __init__(self, owner_route: str):
        self.cookie_secret = b"test-cookie-secret"
        self.guard_token = "guard-token"
        self.mcp_user = "tester"
        self.users = {"tester": {"auth_epoch": 7, "routes": [owner_route]}}
        self.owner_tokens = {owner_route: "owner-token"}
        self.bridge_create_calls = 0

    def auth_epoch(self, username: str) -> int:
        return int(self.users[username].get("auth_epoch") or 0)

    def user_routes(self, username: str) -> list[str]:
        return list(self.users[username]["routes"])

    def allowed_route(self, username: str, route: str) -> bool:
        return route in self.user_routes(username)

    def owner_token(self, route: str) -> str:
        return self.owner_tokens[route]

    def file_inbox_root(self, username: str, route: str) -> None:
        return None

    def workspace_root(self, username: str, route: str) -> None:
        return None

    def save_bridge_package(self, payload: dict[str, Any], username: str) -> dict[str, Any]:
        self.bridge_create_calls += 1
        return {"id": "pkg-test", "owner": username, "title": payload.get("title") or "test", "status": "pending"}


class OwnerHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        self.__class__.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        data = json.dumps({"ok": True, "path": self.path}).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class GatewayCsrfContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.route = "lab"
        OwnerHandler.requests.clear()
        self.owner = ThreadingHTTPServer(("127.0.0.1", 0), OwnerHandler)
        self.owner_thread = threading.Thread(target=self.owner.serve_forever, daemon=True)
        self.owner_thread.start()
        self.original_backends = dict(gateway.BACKENDS)
        gateway.BACKENDS[self.route] = ("127.0.0.1", self.owner.server_address[1], "Lab")
        self.config = StubConfig(self.route)
        self.server = gateway.ReusableThreadingHTTPServer(("127.0.0.1", 0), gateway.GatewayHandler)
        self.server.config = self.config
        self.gateway_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.gateway_thread.start()
        self.base = ("127.0.0.1", self.server.server_address[1])
        self.cookie = self.auth_cookie("tester")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.gateway_thread.join(timeout=2)
        self.owner.shutdown()
        self.owner.server_close()
        self.owner_thread.join(timeout=2)
        gateway.BACKENDS.clear()
        gateway.BACKENDS.update(self.original_backends)

    def auth_cookie(self, username: str) -> str:
        epoch = self.config.auth_epoch(username)
        payload = f"{username}|{int(time.time())}|{epoch}|{secrets.token_urlsafe(8)}"
        payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
        sig = hmac.new(self.config.cookie_secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{gateway.COOKIE_NAME}={payload_b64}.{sig}"

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        include_cookie: bool = True,
    ) -> tuple[int, dict[str, Any]]:
        payload = json.dumps(body or {}).encode("utf-8") if body is not None else None
        headers = {"Cookie": self.cookie} if include_cookie else {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        headers.update(extra_headers or {})
        conn = http.client.HTTPConnection(*self.base, timeout=5)
        try:
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8") or "{}")
        finally:
            conn.close()

    def csrf_token(self) -> str:
        status, data = self.request("GET", "/api/csrf")
        self.assertEqual(status, HTTPStatus.OK)
        return str(data["csrf"])

    def test_gateway_responses_include_browser_security_headers(self) -> None:
        conn = http.client.HTTPConnection(*self.base, timeout=5)
        try:
            conn.request("GET", "/api/csrf", headers={"Cookie": self.cookie})
            resp = conn.getresponse()
            resp.read()
            self.assertEqual(resp.status, HTTPStatus.OK)
            self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
            self.assertEqual(resp.getheader("X-Frame-Options"), "DENY")
            self.assertEqual(resp.getheader("Referrer-Policy"), "no-referrer")
            self.assertEqual(
                resp.getheader("Permissions-Policy"),
                "camera=(), microphone=(), geolocation=()",
            )
            self.assertEqual(resp.getheader("Strict-Transport-Security"), "max-age=31536000")
            csp = resp.getheader("Content-Security-Policy") or ""
            self.assertIn("default-src 'self'", csp)
            self.assertIn("script-src-attr 'none'", csp)
            self.assertIn("object-src 'none'", csp)
        finally:
            conn.close()

    def test_html_page_csp_nonce_matches_inline_portal_assets(self) -> None:
        conn = http.client.HTTPConnection(*self.base, timeout=5)
        try:
            conn.request("GET", "/", headers={"Cookie": self.cookie})
            resp = conn.getresponse()
            body = resp.read().decode("utf-8")
            self.assertEqual(resp.status, HTTPStatus.OK)
            csp = resp.getheader("Content-Security-Policy") or ""
            match = re.search(r"script-src 'self' 'nonce-([^']+)'", csp)
            self.assertIsNotNone(match)
            nonce = match.group(1)
            self.assertIn(f'<script nonce="{nonce}">', body)
            self.assertIn(f'<style nonce="{nonce}">', body)
            self.assertNotIn(gateway.CSP_NONCE_PLACEHOLDER, body)
        finally:
            conn.close()

    def test_portal_exposes_explicit_file_transfer_and_launcher_controls(self) -> None:
        conn = http.client.HTTPConnection(*self.base, timeout=5)
        try:
            conn.request("GET", "/", headers={"Cookie": self.cookie})
            resp = conn.getresponse()
            body = resp.read().decode("utf-8")
        finally:
            conn.close()

        self.assertEqual(resp.status, HTTPStatus.OK)
        self.assertIn("Files to session", body)
        self.assertIn("Choose files", body)
        self.assertIn("Send to…", body)
        self.assertIn("Start ${label}", body)
        self.assertIn("Start on ${e.label", body)
        self.assertNotIn("No handoff package", body)

    def test_auth_cookie_defaults_to_twelve_hours_host_only_and_strict(self) -> None:
        handler = object.__new__(gateway.GatewayHandler)
        handler.server = self.server

        cookie = handler.auth_cookie("tester")

        self.assertTrue(cookie.startswith(f"{gateway.COOKIE_NAME}="))
        self.assertIn("Max-Age=43200", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn("Domain=", cookie)

    def test_auth_cookie_honors_configured_twenty_four_hour_lifetime(self) -> None:
        handler = object.__new__(gateway.GatewayHandler)
        handler.server = self.server

        with mock.patch.object(gateway, "COOKIE_MAX_AGE", 24 * 60 * 60):
            cookie = handler.auth_cookie("tester")

        self.assertIn("Max-Age=86400", cookie)

    def test_gateway_state_change_requires_csrf(self) -> None:
        status, data = self.request("POST", "/api/bridge-packages", {"title": "blocked"})
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertEqual(data.get("error"), "csrf required")
        self.assertEqual(self.config.bridge_create_calls, 0)

    def test_gateway_state_change_accepts_valid_csrf(self) -> None:
        csrf = self.csrf_token()
        status, data = self.request("POST", "/api/bridge-packages", {"title": "allowed"}, {gateway.CSRF_HEADER: csrf})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(data.get("ok"))
        self.assertEqual(self.config.bridge_create_calls, 1)

    def test_owner_proxy_post_requires_gateway_csrf(self) -> None:
        status, data = self.request("POST", f"/{self.route}/api/send", {"text": "blocked"})
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertEqual(data.get("error"), "csrf required")
        self.assertEqual(OwnerHandler.requests, [])

    def test_owner_proxy_post_accepts_gateway_csrf_and_strips_it_upstream(self) -> None:
        csrf = self.csrf_token()
        status, data = self.request("POST", f"/{self.route}/api/send", {"text": "hello"}, {gateway.CSRF_HEADER: csrf})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(OwnerHandler.requests), 1)
        self.assertEqual(OwnerHandler.requests[0]["path"], "/api/send")
        self.assertNotIn(gateway.CSRF_HEADER, OwnerHandler.requests[0]["headers"])

    def test_login_rate_key_ignores_spoofable_forwarded_for(self) -> None:
        handler = object.__new__(gateway.GatewayHandler)
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = {
            "CF-Connecting-IP": "203.0.113.7",
            "X-Forwarded-For": "198.51.100.99",
        }
        self.assertEqual(handler.login_rate_key(), "203.0.113.7")

        handler.client_address = ("198.51.100.10", 12345)
        self.assertEqual(handler.login_rate_key(), "198.51.100.10")

    def test_dispatch_with_cookie_requires_csrf_not_guard_token(self) -> None:
        status, data = self.request("POST", "/api/faryo/dispatch", {})
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertEqual(data.get("error"), "csrf required")

    def test_dispatch_accepts_cookie_with_valid_csrf(self) -> None:
        csrf = self.csrf_token()
        status, data = self.request("POST", "/api/faryo/dispatch", {}, {gateway.CSRF_HEADER: csrf})
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(data.get("error"), "project_id is required")

    def test_dispatch_rejects_guard_token_without_cookie(self) -> None:
        status, data = self.request(
            "POST",
            "/api/faryo/dispatch",
            {},
            {"X-Faryo-Guard-Token": "guard-token"},
            include_cookie=False,
        )
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(data.get("error"), "unauthorized")


if __name__ == "__main__":
    unittest.main()
