from __future__ import annotations

import asyncio
import http.client
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import sys
import threading
import time
from unittest import mock
import unittest

import uvicorn


SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import asgi_owner_proxy
import asgi_app
import gateway_security
import run_asgi
import server as legacy


class FakeStream:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class ShutdownConfig:
    cookie_secret = b"shutdown-cookie-secret"
    mcp_user = "mcp"
    users = {"tester": {"auth_epoch": 1, "routes": ["lab"]}}

    def auth_epoch(self, username: str) -> int:
        return 1 if username == "tester" else 0

    def user(self, username: str):
        return {"routes": ["lab"]} if username == "tester" else None

    def user_routes(self, username: str) -> list[str]:
        return ["lab"] if username == "tester" else []

    def allowed_route(self, username: str, route: str) -> bool:
        return username == "tester" and route == "lab"

    def owner_token(self, route: str) -> str:
        return "shutdown-owner-token"

    def file_inbox_root(self, username: str, route: str) -> None:
        return None

    def workspace_root(self, username: str, route: str) -> None:
        return None


class SseOwner(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    stop = threading.Event()

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(b"event: status\ndata: ready\n\n")
            self.wfile.flush()
            while not self.__class__.stop.wait(0.05):
                pass
        except (BrokenPipeError, ConnectionResetError):
            return


class AsgiShutdownTest(unittest.TestCase):
    def test_proxy_closes_existing_and_rejects_new_streams_during_shutdown(self) -> None:
        routes = asgi_owner_proxy.OwnerProxyRoutes(mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock())
        existing = FakeStream()
        routes._track_stream(existing)

        self.assertEqual(routes.close_active_streams(), 1)
        self.assertEqual(existing.close_calls, 1)
        self.assertEqual(routes.close_active_streams(), 0)

        late = FakeStream()
        routes._track_stream(late)
        self.assertEqual(late.close_calls, 1)

    def test_runner_closes_owner_streams_before_uvicorn_waits_for_tasks(self) -> None:
        order: list[str] = []

        async def uvicorn_shutdown(_server, sockets=None) -> None:
            self.assertEqual(sockets, ["fixture-socket"])
            order.append("uvicorn")

        server = run_asgi.FaryoServer(mock.Mock(spec=uvicorn.Config), lambda: order.append("streams") or 1)
        with mock.patch.object(uvicorn.Server, "shutdown", new=uvicorn_shutdown):
            asyncio.run(server.shutdown(["fixture-socket"]))

        self.assertEqual(order, ["streams", "uvicorn"])

    def test_live_sse_does_not_hold_gateway_graceful_shutdown_open(self) -> None:
        owner = ThreadingHTTPServer(("127.0.0.1", 0), SseOwner)
        owner_thread = threading.Thread(target=owner.serve_forever, daemon=True)
        owner_thread.start()
        original_backends = dict(legacy.BACKENDS)
        legacy.BACKENDS.clear()
        legacy.BACKENDS["lab"] = ("127.0.0.1", owner.server_address[1], "Lab")
        gateway_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        gateway_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        gateway_socket.bind(("127.0.0.1", 0))
        gateway_socket.listen(128)
        gateway_port = gateway_socket.getsockname()[1]
        config = ShutdownConfig()
        app = asgi_app.create_app(legacy, config)
        uvicorn_config = uvicorn.Config(
            app,
            log_level="critical",
            access_log=False,
            lifespan="off",
            timeout_graceful_shutdown=1,
        )
        server = run_asgi.FaryoServer(uvicorn_config, app.state.close_owner_streams)
        gateway_thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [gateway_socket]},
            daemon=True,
        )
        gateway_thread.start()
        connection = None
        try:
            for _attempt in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            self.assertTrue(server.started)
            cookie = gateway_security.SessionCookieCodec(
                config.cookie_secret,
                name=legacy.COOKIE_NAME,
                max_age=legacy.COOKIE_MAX_AGE,
                same_site=legacy.COOKIE_SAME_SITE,
            ).issue("tester", config.auth_epoch("tester")).split(";", 1)[0]
            connection = http.client.HTTPConnection("127.0.0.1", gateway_port, timeout=3)
            connection.request("GET", "/lab/api/events", headers={"Cookie": cookie})
            response = connection.getresponse()
            self.assertEqual(response.status, HTTPStatus.OK)
            self.assertEqual(response.readline(), b"event: status\n")

            started = time.monotonic()
            server.should_exit = True
            gateway_thread.join(timeout=3)
            elapsed = time.monotonic() - started

            self.assertFalse(gateway_thread.is_alive())
            self.assertLess(elapsed, 1.0)
        finally:
            server.should_exit = True
            server.force_exit = True
            gateway_thread.join(timeout=2)
            if connection is not None:
                connection.close()
            SseOwner.stop.set()
            owner.shutdown()
            owner.server_close()
            owner_thread.join(timeout=2)
            SseOwner.stop.clear()
            legacy.BACKENDS.clear()
            legacy.BACKENDS.update(original_backends)


if __name__ == "__main__":
    unittest.main()
