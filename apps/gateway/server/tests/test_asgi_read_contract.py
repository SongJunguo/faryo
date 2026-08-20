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
import tempfile
import threading
import time
from typing import Any
import unittest

import uvicorn
import bcrypt


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
        self.password = "contract-password-long"
        self.password_digest = bcrypt.hashpw(self.password.encode("utf-8"), bcrypt.gensalt())
        self.icp_record = ""
        self.mcp_user = "mcp"
        self.audit_calls: list[dict[str, Any]] = []
        self.packages: dict[str, dict[str, Any]] = {}
        self.bridge_root = Path("/nonexistent")
        self.mcp_token = "contract-mcp-token"
        self.mcp_cors_origin = "https://client.invalid"

    def auth_epoch(self, username: str) -> int:
        return int(self.users[username]["auth_epoch"])

    def user(self, username: str) -> dict[str, Any] | None:
        return self.users.get(username)

    def password_hash(self, username: str) -> bytes:
        return self.password_digest

    def set_password(self, username: str, password: str) -> None:
        self.password_digest = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        self.users[username]["auth_epoch"] += 1

    def control_activity(self, username: str, limit: int = 30) -> list[dict[str, Any]]:
        return [{"time": "2026-01-01T00:00:00Z", "route": "lab", "action": "send", "target": "t_fixture", "result": "success"}][:limit]

    def list_bridge_packages(self, username: str, status: str | None = None) -> list[dict[str, Any]]:
        return list(self.packages.values())

    def user_routes(self, username: str) -> list[str]:
        return list(self.users[username]["routes"])

    def allowed_route(self, username: str, route: str) -> bool:
        return route in self.user_routes(username)

    def owner_token(self, route: str) -> str:
        return "contract-owner-token"

    def max_running(self, route: str) -> int:
        return 8

    def file_inbox_root(self, username: str, route: str) -> None:
        return None

    def workspace_root(self, username: str, route: str) -> None:
        return None

    def append_control_audit(self, **values: Any) -> None:
        self.audit_calls.append(values)

    def revoke_sessions(self, username: str) -> None:
        self.users[username]["auth_epoch"] += 1

    def save_bridge_package(self, payload: dict[str, Any], username: str) -> dict[str, Any]:
        package = {"id": "1-deadbeef", "owner": username, "title": payload.get("title") or "fixture", "status": "pending", "assets": []}
        self.packages[package["id"]] = package
        return package

    def bridge_asset_sources(self, payload: dict[str, Any]) -> list[Any]:
        return list(payload.get("attachments") or [])

    def append_bridge_package_assets(self, package_id: str, assets: list[Any], username: str) -> dict[str, Any]:
        package = self.packages[package_id]
        package["assets"].extend(assets)
        return package

    def bridge_package(self, package_id: str, username: str) -> dict[str, Any] | None:
        return self.packages.get(package_id)

    def update_bridge_package(self, package: dict[str, Any]) -> None:
        self.packages[str(package["id"])] = package


class OwnerContractFixture(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        self.__class__.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        payload = json.loads(body.decode("utf-8")) if body and self.path != "/api/attachment" else {}
        result = {"ok": True, "session": payload.get("session") or "", "duplicate": False}
        if self.path == "/api/agent-session/archive":
            result["archived"] = True
        elif self.path == "/api/agent-session/unarchive":
            result["archived"] = False
        elif self.path == "/api/agent/resume":
            result["session"] = "faryo3"
        elif self.path == "/api/agent/new":
            result["session"] = "faryo4"
        elif self.path == "/api/attachment":
            result["path"] = "/inbox/fixture.png"
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
    maxDiff = None
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
            "access-control-allow-headers",
            "access-control-allow-methods",
            "access-control-allow-origin",
            "allow",
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
            "vary",
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

    def test_login_success_and_failure_contracts_match(self) -> None:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        valid = legacy.urlencode({"username": "tester", "password": self.config.password, "next": "/"}).encode("utf-8")
        legacy_success = self.request(self.legacy_base, "/login", method="POST", body=valid, extra_headers=headers)
        asgi_success = self.request(self.asgi_base, "/login", method="POST", body=valid, extra_headers=headers)
        self.assertEqual(asgi_success[0], legacy_success[0])
        self.assertEqual(self.selected_headers(asgi_success[1]), self.selected_headers(legacy_success[1]))

        invalid = legacy.urlencode({"username": "tester", "password": "wrong", "next": "/"}).encode("utf-8")
        legacy_failure = self.request(self.legacy_base, "/login", method="POST", body=invalid, extra_headers=headers)
        asgi_failure = self.request(self.asgi_base, "/login", method="POST", body=invalid, extra_headers=headers)
        self.assertEqual(asgi_failure[0], legacy_failure[0])
        self.assertEqual(self.normalized_body("/login", asgi_failure[2]), self.normalized_body("/login", legacy_failure[2]))

    def test_password_page_validation_and_success_contracts_match(self) -> None:
        self.config.users["tester"]["auth_epoch"] = 7
        self.config.password_digest = bcrypt.hashpw(self.config.password.encode("utf-8"), bcrypt.gensalt())
        self.assert_contract("/password", authenticated=True)
        csrf = gateway_security.csrf_token(self.config.cookie_secret, "tester", 7)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        invalid = legacy.urlencode({
            "csrf": csrf,
            "current_password": "wrong",
            "new_password": "replacement-password",
            "confirm_password": "replacement-password",
        }).encode("utf-8")
        legacy_invalid = self.request(self.legacy_base, "/password", authenticated=True, method="POST", body=invalid, extra_headers=headers)
        asgi_invalid = self.request(self.asgi_base, "/password", authenticated=True, method="POST", body=invalid, extra_headers=headers)
        self.assertEqual(self.normalized_body("/password", asgi_invalid[2]), self.normalized_body("/password", legacy_invalid[2]))

        valid = legacy.urlencode({
            "csrf": csrf,
            "current_password": self.config.password,
            "new_password": "replacement-password",
            "confirm_password": "replacement-password",
        }).encode("utf-8")
        original_digest = bcrypt.hashpw(self.config.password.encode("utf-8"), bcrypt.gensalt())
        self.config.password_digest = original_digest
        self.config.users["tester"]["auth_epoch"] = 7
        legacy_success = self.request(self.legacy_base, "/password", authenticated=True, method="POST", body=valid, extra_headers=headers)
        self.config.password_digest = original_digest
        self.config.users["tester"]["auth_epoch"] = 7
        asgi_success = self.request(self.asgi_base, "/password", authenticated=True, method="POST", body=valid, extra_headers=headers)
        self.assertEqual(asgi_success[0], legacy_success[0])
        self.assertEqual(self.selected_headers(asgi_success[1]), self.selected_headers(legacy_success[1]))
        self.config.password_digest = bcrypt.hashpw(self.config.password.encode("utf-8"), bcrypt.gensalt())
        self.config.users["tester"]["auth_epoch"] = 7

    def test_security_activity_and_bridge_package_reads_match(self) -> None:
        self.config.packages["1-deadbeef"] = {"id": "1-deadbeef", "owner": "tester", "title": "fixture", "status": "pending", "assets": []}
        for path in ("/api/security-activity?limit=1", "/api/bridge-packages"):
            legacy_result = self.request(self.legacy_base, path, authenticated=True)
            asgi_result = self.request(self.asgi_base, path, authenticated=True)
            self.assertEqual(asgi_result[0], legacy_result[0])
            self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))

    def test_gateway_status_and_workbench_contracts_match(self) -> None:
        def normalized(payload: dict[str, Any]) -> dict[str, Any]:
            value = json.loads(json.dumps(payload))
            value["updatedAt"] = 0
            for entry in value.get("entries", []):
                entry["stateText"] = "<timing>"
                entry["detail"] = "<timing>"
            return value

        for path in ("/api/gateway-status", "/api/workbench?page=1&period=7d&archive=all&q=fixture"):
            legacy_result = self.request(self.legacy_base, path, authenticated=True)
            asgi_result = self.request(self.asgi_base, path, authenticated=True)
            self.assertEqual(asgi_result[0], legacy_result[0])
            self.assertEqual(normalized(json.loads(asgi_result[2])), normalized(json.loads(legacy_result[2])))

    def test_bridge_package_asset_read_contract_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.config.bridge_root = Path(temp)
            package_dir = self.config.bridge_root / "1-deadbeef"
            package_dir.mkdir()
            asset = package_dir / "fixture.png"
            asset.write_bytes(b"png fixture")
            self.config.packages["1-deadbeef"] = {"id": "1-deadbeef", "owner": "tester", "assets": []}
            legacy_result = self.request(self.legacy_base, "/bridge/packages/1-deadbeef/fixture.png", authenticated=True)
            asgi_result = self.request(self.asgi_base, "/bridge/packages/1-deadbeef/fixture.png", authenticated=True)
        self.assertEqual(asgi_result[0], legacy_result[0])
        self.assertEqual(asgi_result[2], legacy_result[2])
        self.assertEqual(self.selected_headers(asgi_result[1]), self.selected_headers(legacy_result[1]))

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

    def test_agent_resume_and_audit_contract_match(self) -> None:
        body = json.dumps({"route": "lab", "agent_session_id": "thread-fixture", "source": "codex-cli"}).encode("utf-8")
        csrf = gateway_security.csrf_token(self.config.cookie_secret, "tester", self.config.auth_epoch("tester"))
        headers = {legacy.CSRF_HEADER: csrf, "Content-Type": "application/json"}
        self.config.audit_calls.clear()
        legacy_result = self.request(
            self.legacy_base, "/api/agent/resume", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        asgi_result = self.request(
            self.asgi_base, "/api/agent/resume", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        self.assertEqual(asgi_result[0], legacy_result[0])
        self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))
        self.assertEqual(json.loads(asgi_result[2])["session"], "faryo3")
        normalized = [
            {key: value for key, value in call.items() if key not in {"request_id", "duration_ms"}}
            for call in self.config.audit_calls
        ]
        self.assertEqual(normalized[0], normalized[1])
        self.assertEqual(normalized[0]["action"], "resume")
        self.assertEqual(normalized[0]["target"], "thread-fixture")

    def test_agent_new_and_audit_contract_match(self) -> None:
        body = json.dumps({"route": "lab", "command": "codex", "client_launch_id": "launch-fixture"}).encode("utf-8")
        csrf = gateway_security.csrf_token(self.config.cookie_secret, "tester", self.config.auth_epoch("tester"))
        headers = {legacy.CSRF_HEADER: csrf, "Content-Type": "application/json"}
        self.config.audit_calls.clear()
        legacy_result = self.request(
            self.legacy_base, "/api/agent/new", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        asgi_result = self.request(
            self.asgi_base, "/api/agent/new", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        self.assertEqual(asgi_result[0], legacy_result[0])
        self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))
        self.assertEqual(json.loads(asgi_result[2])["session"], "faryo4")
        normalized = [
            {key: value for key, value in call.items() if key not in {"request_id", "duration_ms"}}
            for call in self.config.audit_calls
        ]
        self.assertEqual(normalized[0], normalized[1])
        self.assertEqual(normalized[0]["action"], "start")
        self.assertEqual(normalized[0]["target"], "faryo4")

    def test_agent_new_rejects_invalid_cwd_token_equally(self) -> None:
        body = json.dumps({
            "route": "lab",
            "command": "codex",
            "cwd": "/workspace/fixture",
            "cwd_token": "invalid",
            "client_launch_id": "launch-fixture",
        }).encode("utf-8")
        csrf = gateway_security.csrf_token(self.config.cookie_secret, "tester", self.config.auth_epoch("tester"))
        headers = {legacy.CSRF_HEADER: csrf, "Content-Type": "application/json"}
        legacy_result = self.request(
            self.legacy_base, "/api/agent/new", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        asgi_result = self.request(
            self.asgi_base, "/api/agent/new", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        self.assertEqual(asgi_result[0], legacy_result[0])
        self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))
        self.assertEqual(asgi_result[0], HTTPStatus.BAD_REQUEST)

    def test_bridge_package_create_and_empty_asset_append_match(self) -> None:
        csrf = gateway_security.csrf_token(self.config.cookie_secret, "tester", self.config.auth_epoch("tester"))
        headers = {legacy.CSRF_HEADER: csrf, "Content-Type": "application/json"}
        create_body = json.dumps({"title": "fixture"}).encode("utf-8")
        legacy_create = self.request(
            self.legacy_base, "/api/bridge-packages", authenticated=True, method="POST", body=create_body, extra_headers=headers,
        )
        self.config.packages.clear()
        asgi_create = self.request(
            self.asgi_base, "/api/bridge-packages", authenticated=True, method="POST", body=create_body, extra_headers=headers,
        )
        self.assertEqual(asgi_create[0], legacy_create[0])
        self.assertEqual(json.loads(asgi_create[2]), json.loads(legacy_create[2]))

        append_body = json.dumps({"package_id": "1-deadbeef", "attachments": []}).encode("utf-8")
        legacy_append = self.request(
            self.legacy_base, "/api/bridge-package-assets", authenticated=True, method="POST", body=append_body, extra_headers=headers,
        )
        asgi_append = self.request(
            self.asgi_base, "/api/bridge-package-assets", authenticated=True, method="POST", body=append_body, extra_headers=headers,
        )
        self.assertEqual(asgi_append[0], legacy_append[0])
        self.assertEqual(json.loads(asgi_append[2]), json.loads(legacy_append[2]))

    def test_bridge_inject_without_assets_and_audit_match(self) -> None:
        csrf = gateway_security.csrf_token(self.config.cookie_secret, "tester", self.config.auth_epoch("tester"))
        headers = {legacy.CSRF_HEADER: csrf, "Content-Type": "application/json"}
        body = json.dumps({"package_id": "1-deadbeef", "route": "lab", "session": "faryo4"}).encode("utf-8")
        base_package = {"id": "1-deadbeef", "owner": "tester", "title": "fixture", "status": "pending", "assets": []}
        self.config.packages["1-deadbeef"] = dict(base_package)
        self.config.audit_calls.clear()
        legacy_result = self.request(
            self.legacy_base, "/api/bridge-inject", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        self.config.packages["1-deadbeef"] = dict(base_package)
        asgi_result = self.request(
            self.asgi_base, "/api/bridge-inject", authenticated=True, method="POST", body=body, extra_headers=headers,
        )
        self.assertEqual(asgi_result[0], legacy_result[0])
        self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))
        normalized = [
            {key: value for key, value in call.items() if key not in {"request_id", "duration_ms"}}
            for call in self.config.audit_calls
        ]
        self.assertEqual(normalized[0], normalized[1])
        self.assertEqual(normalized[0]["action"], "file-inject")
        self.assertEqual(normalized[0]["target"], "faryo4")

    def test_bridge_inject_with_real_asset_upload_matches(self) -> None:
        csrf = gateway_security.csrf_token(self.config.cookie_secret, "tester", self.config.auth_epoch("tester"))
        headers = {legacy.CSRF_HEADER: csrf, "Content-Type": "application/json"}
        body = json.dumps({"package_id": "1-deadbeef", "route": "lab", "session": "faryo4"}).encode("utf-8")
        with tempfile.TemporaryDirectory() as temp:
            self.config.bridge_root = Path(temp)
            asset_path = self.config.bridge_root / "fixture.png"
            asset_path.write_bytes(b"png fixture")
            base_package = {
                "id": "1-deadbeef",
                "owner": "tester",
                "title": "fixture",
                "status": "pending",
                "assets": [{"path": str(asset_path), "file_name": "fixture.png", "mime_type": "image/png"}],
            }
            self.config.packages["1-deadbeef"] = json.loads(json.dumps(base_package))
            OwnerContractFixture.requests.clear()
            legacy_result = self.request(
                self.legacy_base, "/api/bridge-inject", authenticated=True, method="POST", body=body, extra_headers=headers,
            )
            self.config.packages["1-deadbeef"] = json.loads(json.dumps(base_package))
            asgi_result = self.request(
                self.asgi_base, "/api/bridge-inject", authenticated=True, method="POST", body=body, extra_headers=headers,
            )
        self.assertEqual(asgi_result[0], legacy_result[0])
        self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))
        uploads = [request for request in OwnerContractFixture.requests if request["path"] == "/api/attachment"]
        self.assertEqual(len(uploads), 2)
        for upload in uploads:
            self.assertIn(b'name="file"', upload["body"])
            self.assertEqual(upload["headers"]["X-Owner-Token"], "contract-owner-token")

    def test_mcp_auth_options_initialize_notification_batch_and_tool_contracts_match(self) -> None:
        cors_headers = {"Origin": self.config.mcp_cors_origin}
        legacy_options = self.request(self.legacy_base, "/mcp", method="OPTIONS", extra_headers=cors_headers)
        asgi_options = self.request(self.asgi_base, "/mcp", method="OPTIONS", extra_headers=cors_headers)
        self.assertEqual(asgi_options[0], legacy_options[0])
        self.assertEqual(self.selected_headers(asgi_options[1]), self.selected_headers(legacy_options[1]))

        legacy_denied = self.request(self.legacy_base, "/mcp")
        asgi_denied = self.request(self.asgi_base, "/mcp")
        self.assertEqual(asgi_denied[0], legacy_denied[0])
        self.assertEqual(json.loads(asgi_denied[2]), json.loads(legacy_denied[2]))

        headers = {
            "Authorization": f"Bearer {self.config.mcp_token}",
            "Content-Type": "application/json",
            "Origin": self.config.mcp_cors_origin,
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "gateway.invalid",
        }
        payloads = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": legacy.MCP_PROTOCOL_VERSION}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            [
                {"jsonrpc": "2.0", "id": 3, "method": "ping"},
                {"jsonrpc": "2.0", "id": 4, "method": "resources/list"},
            ],
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": legacy.MCP_TOOL_NAME, "arguments": {"title": "fixture", "intent": "handoff", "context": "context", "prompt": "prompt"}},
            },
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                body = json.dumps(payload).encode("utf-8")
                self.config.packages.clear()
                legacy_result = self.request(self.legacy_base, "/mcp", method="POST", body=body, extra_headers=headers)
                self.config.packages.clear()
                asgi_result = self.request(self.asgi_base, "/mcp", method="POST", body=body, extra_headers=headers)
                self.assertEqual(asgi_result[0], legacy_result[0])
                self.assertEqual(json.loads(asgi_result[2]), json.loads(legacy_result[2]))

        notification = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
        legacy_notification = self.request(self.legacy_base, "/mcp", method="POST", body=notification, extra_headers=headers)
        asgi_notification = self.request(self.asgi_base, "/mcp", method="POST", body=notification, extra_headers=headers)
        self.assertEqual(asgi_notification[0], legacy_notification[0])
        self.assertEqual(asgi_notification[0], HTTPStatus.ACCEPTED)


if __name__ == "__main__":
    unittest.main()
