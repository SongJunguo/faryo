from __future__ import annotations

import http.client
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
        self.users = {"tester": {"auth_epoch": 7, "routes": ["txy"]}}
        self.icp_record = ""

    def auth_epoch(self, username: str) -> int:
        return int(self.users[username]["auth_epoch"])

    def user_routes(self, username: str) -> list[str]:
        return list(self.users[username]["routes"])


class AsgiReadContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = ContractConfig()
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

    def request(self, base: tuple[str, int], path: str, *, authenticated: bool = False) -> tuple[int, list[tuple[str, str]], bytes]:
        headers = {"Cookie": self.cookie} if authenticated else {}
        connection = http.client.HTTPConnection(*base, timeout=5)
        try:
            connection.request("GET", path, headers=headers)
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


if __name__ == "__main__":
    unittest.main()
