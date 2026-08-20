from __future__ import annotations

import http.client
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import re
import socket
import sys
import threading
import time
from typing import Any
import unittest

import uvicorn


REPO_ROOT = Path(__file__).resolve().parents[4]
SERVER_ROOT = REPO_ROOT / "apps" / "gateway" / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))
SERVER_PATH = SERVER_ROOT / "server.py"
spec = importlib.util.spec_from_file_location("faryo_gateway_contract_legacy", SERVER_PATH)
legacy = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(legacy)

import asgi_app
import gateway_security


class ContractConfig:
    def __init__(self) -> None:
        self.cookie_secret = b"contract-cookie-secret"
        self.users = {"tester": {"auth_epoch": 7, "routes": ["lab"]}}
        self.icp_record = ""
        self.mcp_user = "mcp"
        self.audit_calls: list[dict[str, Any]] = []

    def auth_epoch(self, username: str) -> int:
        return int(self.users[username]["auth_epoch"])

    def user_routes(self, username: str) -> list[str]:
        return list(self.users[username]["routes"])

    def allowed_route(self, username: str, route: str) -> bool:
        return route in self.user_routes(username)

    def owner_token(self, route: str) -> str:
        return "contract-owner-token"

    def file_inbox_root(self, username: str, route: str) -> None:
        return None

    def workspace_root(self, username: str, route: str) -> None:
        return None

    def append_control_audit(self, **values: Any) -> None:
        self.audit_calls.append(values)

    def revoke_sessions(self, username: str) -> None:
        self.users[username]["auth_epoch"] += 1


class OwnerContractFixture(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        self.__class__.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        payload = json.loads(body.decode("utf-8")) if body else {}
        result = {"ok": True, "session": payload.get("session") or "", "duplicate": False}
        if self.path == "/api/agent-session/archive":
            result["archived"] = True
        elif self.path == "/api/agent-session/unarchive":
            result["archived"] = False
        data = json.dumps(result).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self.__class__.requests.append({"path": self.path, "headers": dict(self.headers), "body": b""})
        if self.path.startswith("/api/events"):
            data = b"event: status\ndata: first\n\nevent: status\ndata: second\n\n"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
        elif self.path.startswith("/api/"):
            data = json.dumps({"ok": True, "path": self.path}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
        elif self.path.startswith("/?session="):
            data = b"<!doctype html><title>Owner fixture</title>"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
        else:
            data = b"export const fixture = true;\n"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/javascript")
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class AsgiReadContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = ContractConfig()
        OwnerContractFixture.requests.clear()
        cls.owner_server = ThreadingHTTPServer(("127.0.0.1", 0), OwnerContractFixture)
        cls.owner_thread = threading.Thread(target=cls.owner_server.serve_forever, daemon=True)
        cls.owner_thread.start()
        cls.original_backends = dict(legacy.BACKENDS)
        legacy.BACKENDS["lab"] = ("127.0.0.1", cls.owner_server.server_address[1], "Lab")
        cls.legacy_server = legacy.ReusableThreadingHTTPServer(("127.0.0.1", 0), legacy.GatewayHandler)
        cls.legacy_server.config = cls.config
        cls.legacy_thread = threading.Thread(target=cls.legacy_server.serve_forever, daemon=True)
        cls.legacy_thread.start()
        cls.legacy_base = ("127.0.0.1", cls.legacy_server.server_address[1])

        cls.asgi_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cls.asgi_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        cls.asgi_socket.bind(("127.0.0.1", 0))
        cls.asgi_socket.listen(128)
        cls.asgi_base = ("127.0.0.1", cls.asgi_socket.getsockname()[1])
        cls.asgi_server = uvicorn.Server(uvicorn.Config(
            asgi_app.create_app(legacy, cls.config),
            log_level="error",
            access_log=False,
            lifespan="off",
        ))
        cls.asgi_thread = threading.Thread(target=cls.asgi_server.run, kwargs={"sockets": [cls.asgi_socket]}, daemon=True)
        cls.asgi_thread.start()
        for _attempt in range(100):
            if cls.asgi_server.started:
                break
            time.sleep(0.02)
        if not cls.asgi_server.started:
            raise RuntimeError("ASGI contract server did not start")

        codec = gateway_security.SessionCookieCodec(
            cls.config.cookie_secret,
            name=legacy.COOKIE_NAME,
            max_age=legacy.COOKIE_MAX_AGE,
            same_site=legacy.COOKIE_SAME_SITE,
        )
        cls.cookie = codec.issue("tester", cls.config.auth_epoch("tester")).split(";", 1)[0]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.asgi_server.should_exit = True
        cls.asgi_thread.join(timeout=5)
        cls.legacy_server.shutdown()
        cls.legacy_server.server_close()
        cls.legacy_thread.join(timeout=2)
        cls.owner_server.shutdown()
        cls.owner_server.server_close()
        cls.owner_thread.join(timeout=2)
        legacy.BACKENDS.clear()
        legacy.BACKENDS.update(cls.original_backends)

    def request(
        self,
        base: tuple[str, int],
        path: str,
        *,
        authenticated: bool = False,
        method: str = "GET",
        body: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, list[tuple[str, str]], bytes]:
        headers = {"Cookie": self.cookie} if authenticated else {}
        headers.update(extra_headers or {})
        connection = http.client.HTTPConnection(*base, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            connection.close()

    @staticmethod
    def selected_headers(headers: list[tuple[str, str]]) -> dict[str, list[str]]:
        selected = {
            "cache-control",
            "content-security-policy",
            "content-type",
            "location",
            "permissions-policy",
            "referrer-policy",
            "set-cookie",
            "strict-transport-security",
            "x-content-type-options",
            "x-frame-options",
        }
        result: dict[str, list[str]] = {}
        for name, value in headers:
            lower = name.lower()
            if lower not in selected:
                continue
            normalized = re.sub(r"nonce-[A-Za-z0-9_-]+", "nonce-<value>", value)
            if lower == "set-cookie":
                normalized = re.sub(r"(__Host-faryo_auth=)[^;]+", r"\1<signed>", normalized)
            result.setdefault(lower, []).append(normalized)
        return result

    @staticmethod
    def normalized_body(path: str, body: bytes) -> Any:
        if path in {"/manifest.json", "/api/csrf"}:
            return json.loads(body.decode("utf-8"))
        text = body.decode("utf-8", errors="replace")
        return re.sub(r"nonce=\"[A-Za-z0-9_-]+\"", 'nonce="<value>"', text)

    def assert_contract(self, path: str, *, authenticated: bool = False) -> None:
        legacy_result = self.request(self.legacy_base, path, authenticated=authenticated)
        asgi_result = self.request(self.asgi_base, path, authenticated=authenticated)
        self.assertEqual(asgi_result[0], legacy_result[0], path)
        self.assertEqual(self.selected_headers(asgi_result[1]), self.selected_headers(legacy_result[1]), path)
        self.assertEqual(self.normalized_body(path, asgi_result[2]), self.normalized_body(path, legacy_result[2]), path)

    def test_public_read_contracts_match(self) -> None:
        for path in ("/manifest.json", "/sw.js", "/workbench.css", "/appearance.js", "/login?next=%2F"):
            with self.subTest(path=path):
                self.assert_contract(path)

    def test_csrf_contract_matches_with_and_without_authentication(self) -> None:
        self.assert_contract("/api/csrf")
        self.assert_contract("/api/csrf", authenticated=True)

    def test_authenticated_home_and_logout_contracts_match(self) -> None:
        self.assert_contract("/", authenticated=True)
        self.assert_contract("/logout", authenticated=True)

    def test_proxy_control_post_and_audit_contract_match(self) -> None:
        body = json.dumps({"session": "fixture-session", "text": "anonymous"}).encode("utf-8")
        csrf = gateway_security.csrf_token(self.config.cookie_secret, "tester", self.config.auth_epoch("tester"))
        headers = {legacy.CSRF_HEADER: csrf, "Content-Type": "application/json"}
        self.config.audit_calls.clear()
        OwnerContractFixture.requests.clear()
        legacy_result = self.request(
            self.legacy_base, "/lab/api/send", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        asgi_result = self.request(
            self.asgi_base, "/lab/api/send", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        self.assertEqual(asgi_result[0], legacy_result[0])
        self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))
        self.assertEqual(len(OwnerContractFixture.requests), 2)
        for forwarded in OwnerContractFixture.requests:
            self.assertEqual(forwarded["headers"]["X-Owner-Token"], "contract-owner-token")
            self.assertNotIn(legacy.CSRF_HEADER, forwarded["headers"])
        self.assertEqual(len(self.config.audit_calls), 2)
        normalized = [
            {key: value for key, value in call.items() if key not in {"request_id", "duration_ms"}}
            for call in self.config.audit_calls
        ]
        self.assertEqual(normalized[0], normalized[1])
        self.assertEqual(normalized[0]["action"], "send")
        self.assertEqual(normalized[0]["target"], "fixture-session")

    def test_proxy_control_rejects_missing_csrf_equally(self) -> None:
        body = json.dumps({"session": "fixture-session"}).encode("utf-8")
        legacy_result = self.request(self.legacy_base, "/lab/api/down", authenticated=True, method="POST", body=body)
        asgi_result = self.request(self.asgi_base, "/lab/api/down", authenticated=True, method="POST", body=body)
        self.assertEqual(asgi_result[0], legacy_result[0])
        self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))

    def test_owner_json_get_contract_matches(self) -> None:
        self.assert_contract("/lab/api/status?session=fixture", authenticated=True)

    def test_owner_sse_bytes_and_headers_match(self) -> None:
        self.assert_contract("/lab/api/events?session=fixture", authenticated=True)

    def test_owner_get_requires_authentication_equally(self) -> None:
        self.assert_contract("/lab/api/status")

    def test_owner_page_and_static_resource_contracts_match(self) -> None:
        for path in ("/lab/?session=fixture", "/lab/app.js", "/lab/owner/changes-panel.mjs"):
            with self.subTest(path=path):
                self.assert_contract(path, authenticated=True)

    def test_owner_page_redirects_to_login_without_authentication(self) -> None:
        self.assert_contract("/lab/?session=fixture")

    def test_unknown_owner_resource_is_not_proxied(self) -> None:
        legacy_result = self.request(self.legacy_base, "/lab/private.txt", authenticated=True)
        asgi_result = self.request(self.asgi_base, "/lab/private.txt", authenticated=True)
        self.assertEqual(asgi_result[0], legacy_result[0])
        self.assertEqual(asgi_result[0], HTTPStatus.NOT_FOUND)

    def test_session_history_archive_restore_and_audit_contract_match(self) -> None:
        csrf = gateway_security.csrf_token(self.config.cookie_secret, "tester", self.config.auth_epoch("tester"))
        headers = {legacy.CSRF_HEADER: csrf, "Content-Type": "application/json"}
        body = json.dumps({"route": "lab", "agent_session_id": "thread-fixture"}).encode("utf-8")
        for path, action, archived in (
            ("/api/session-history/archive", "archive", True),
            ("/api/session-history/unarchive", "unarchive", False),
        ):
            with self.subTest(path=path):
                self.config.audit_calls.clear()
                legacy_result = self.request(self.legacy_base, path, authenticated=True, method="POST", body=body, extra_headers=headers)
                asgi_result = self.request(self.asgi_base, path, authenticated=True, method="POST", body=body, extra_headers=headers)
                self.assertEqual(asgi_result[0], legacy_result[0])
                self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))
                self.assertEqual(json.loads(asgi_result[2])["archived"], archived)
                self.assertEqual(len(self.config.audit_calls), 2)
                normalized = [
                    {key: value for key, value in call.items() if key not in {"request_id", "duration_ms"}}
                    for call in self.config.audit_calls
                ]
                self.assertEqual(normalized[0], normalized[1])
                self.assertEqual(normalized[0]["action"], action)
                self.assertEqual(normalized[0]["target"], "thread-fixture")

    def test_session_history_validation_contract_matches(self) -> None:
        csrf = gateway_security.csrf_token(self.config.cookie_secret, "tester", self.config.auth_epoch("tester"))
        headers = {legacy.CSRF_HEADER: csrf, "Content-Type": "application/json"}
        body = json.dumps({"route": "lab"}).encode("utf-8")
        legacy_result = self.request(self.legacy_base, "/api/session-history/archive", authenticated=True, method="POST", body=body, extra_headers=headers)
        asgi_result = self.request(self.asgi_base, "/api/session-history/archive", authenticated=True, method="POST", body=body, extra_headers=headers)
        self.assertEqual(asgi_result[0], legacy_result[0])
        self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))

    def test_revoke_sessions_and_audit_contract_match(self) -> None:
        body = json.dumps({"confirm": "revoke"}).encode("utf-8")
        csrf = gateway_security.csrf_token(self.config.cookie_secret, "tester", 7)
        headers = {legacy.CSRF_HEADER: csrf, "Content-Type": "application/json"}
        self.config.users["tester"]["auth_epoch"] = 7
        self.config.audit_calls.clear()
        legacy_result = self.request(
            self.legacy_base, "/api/auth/revoke-all", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        self.config.users["tester"]["auth_epoch"] = 7
        asgi_result = self.request(
            self.asgi_base, "/api/auth/revoke-all", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        self.assertEqual(asgi_result[0], legacy_result[0])
        self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))
        self.assertEqual(len(self.config.audit_calls), 2)
        normalized = [
            {key: value for key, value in call.items() if key not in {"request_id", "duration_ms"}}
            for call in self.config.audit_calls
        ]
        self.assertEqual(normalized[0], normalized[1])
        self.assertEqual(normalized[0]["action"], "revoke-sessions")
        self.config.users["tester"]["auth_epoch"] = 7

    def test_revoke_requires_explicit_confirmation_equally(self) -> None:
        body = json.dumps({"confirm": "no"}).encode("utf-8")
        csrf = gateway_security.csrf_token(self.config.cookie_secret, "tester", 7)
        headers = {legacy.CSRF_HEADER: csrf, "Content-Type": "application/json"}
        self.config.users["tester"]["auth_epoch"] = 7
        legacy_result = self.request(
            self.legacy_base, "/api/auth/revoke-all", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        asgi_result = self.request(
            self.asgi_base, "/api/auth/revoke-all", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        self.assertEqual(asgi_result[0], legacy_result[0])
        self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))


if __name__ == "__main__":
    unittest.main()
