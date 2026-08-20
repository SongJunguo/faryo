from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
from typing import Any
import unittest


SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from owner_client import OwnerClient


class StubConfig:
    mcp_user = "mcp"

    def owner_token(self, route: str) -> str:
        return f"token-{route}"

    def file_inbox_root(self, username: str, route: str) -> str:
        return "/scoped/inbox"

    def workspace_root(self, username: str, route: str) -> str:
        return "/scoped/workspace"


class OwnerFixture(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        self.__class__.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        if self.path == "/api/fail":
            payload = {"ok": False, "error": "fixture failure"}
            status = HTTPStatus.CONFLICT
        else:
            payload = {"ok": True, "size": len(body)}
            status = HTTPStatus.OK
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class OwnerClientTest(unittest.TestCase):
    def setUp(self) -> None:
        OwnerFixture.requests.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), OwnerFixture)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = OwnerClient(
            {"lab": ("127.0.0.1", self.server.server_address[1], "Test Label")},
            StubConfig(),
            encode_label=lambda value: value.replace(" ", "%20"),
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_headers_inject_owner_identity_and_scope(self) -> None:
        headers = self.client.headers("lab", "tester")
        self.assertEqual(headers["X-Owner-Token"], "token-lab")
        self.assertEqual(headers["X-Faryo-Owner-Label"], "Test%20Label")
        self.assertEqual(headers["X-Faryo-History-Scope"], "workspace")
        self.assertEqual(headers["X-Faryo-File-Inbox-Root"], "/scoped/inbox")
        self.assertEqual(headers["X-Faryo-Workspace-Root"], "/scoped/workspace")
        self.assertNotIn("X-Faryo-History-Scope", self.client.headers("lab", "mcp"))

    def test_json_request_preserves_unicode_and_upstream_status(self) -> None:
        result = self.client.json_request("lab", "/api/send", {"text": "中文公式"}, "tester")
        self.assertTrue(result["ok"])
        request = OwnerFixture.requests[-1]
        self.assertEqual(json.loads(request["body"].decode("utf-8")), {"text": "中文公式"})
        self.assertEqual(request["headers"]["X-Owner-Token"], "token-lab")

        failed = self.client.json_request("lab", "/api/fail", {}, "tester")
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["httpStatus"], HTTPStatus.CONFLICT)

    def test_attachment_request_sanitizes_filename_and_uses_fixed_field(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixture.png"
            path.write_bytes(b"png fixture")
            result = self.client.attachment_request("lab", path, "image/png", "../bad\r\nname.png", "tester")
        self.assertTrue(result["ok"])
        request = OwnerFixture.requests[-1]
        self.assertEqual(request["path"], "/api/attachment")
        self.assertIn(b'name="file"', request["body"])
        self.assertNotIn(b"\r\nname.png", request["body"])

    def test_raw_request_keeps_body_and_replaces_internal_headers(self) -> None:
        body = b'{"session":"fixture"}'
        response = self.client.raw_request(
            "lab",
            "POST",
            "/api/send?fixture=1",
            body,
            "tester",
            forwarded_headers={"Content-Type": "application/json", "X-Owner-Token": "spoofed"},
        )
        self.assertEqual(response.status, HTTPStatus.OK)
        request = OwnerFixture.requests[-1]
        self.assertEqual(request["path"], "/api/send?fixture=1")
        self.assertEqual(request["body"], body)
        self.assertEqual(request["headers"]["X-Owner-Token"], "token-lab")


if __name__ == "__main__":
    unittest.main()
