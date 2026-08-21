from __future__ import annotations

import io
from pathlib import Path
import sys
import unittest
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import codex_app_server


class Process:
    def __init__(self) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO()
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout=None) -> int:
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.returncode = -9


class CodexAppServerClientTest(unittest.TestCase):
    def client(self) -> codex_app_server.CodexAppServerClient:
        return codex_app_server.CodexAppServerClient(
            argv=lambda *args: ["codex", *args],
            client_version=lambda: "1.4.0",
        )

    def test_send_writes_one_json_line(self) -> None:
        process = Process()
        self.assertTrue(self.client().send(process, {"id": 1, "method": "ping"}))
        self.assertEqual(process.stdin.getvalue(), '{"id": 1, "method": "ping"}\n')

    def test_rpc_returns_result_and_error_contracts(self) -> None:
        client = self.client()
        process = Process()
        with (
            mock.patch.object(client, "start_locked", return_value=process),
            mock.patch.object(client, "read", side_effect=[{"id": 1, "result": {"ok": True}}]),
        ):
            self.assertEqual(client.rpc("ping", {}), {"ok": True, "result": {"ok": True}})

        client.request_id = 0
        with (
            mock.patch.object(client, "start_locked", return_value=process),
            mock.patch.object(client, "read", side_effect=[{"id": 1, "error": {"code": -1, "message": "failed"}}]),
        ):
            self.assertEqual(client.rpc("ping", {}), {"ok": False, "code": -1, "error": "failed"})

    def test_stop_closes_and_reaps_the_process(self) -> None:
        client = self.client()
        process = Process()
        client.process = process
        client.stop()
        self.assertIsNone(client.process)
        self.assertTrue(process.stdin.closed)
        self.assertEqual(process.returncode, 0)

    def test_start_uses_the_sanitized_codex_environment(self) -> None:
        process = Process()
        popen = mock.Mock(return_value=process)
        client = codex_app_server.CodexAppServerClient(
            argv=lambda *args: ["codex", *args],
            client_version=lambda: "1.6.7",
            environment=lambda argv: {"PATH": "/safe/bin", "ARGV0": argv[0]},
            popen=popen,
        )
        with mock.patch.object(client, "read", return_value={"id": 1, "result": {}}):
            self.assertIs(client.start_locked(0.1), process)

        self.assertEqual(
            popen.call_args.kwargs["env"],
            {"PATH": "/safe/bin", "ARGV0": "codex"},
        )


if __name__ == "__main__":
    unittest.main()
