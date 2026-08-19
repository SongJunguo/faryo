#!/usr/bin/env python3
"""Privacy and retention tests for the Gateway control audit."""

from __future__ import annotations

import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[4]
SERVER_PATH = REPO_ROOT / "apps" / "gateway" / "server" / "server.py"

spec = importlib.util.spec_from_file_location("faryo_gateway_control_audit", SERVER_PATH)
gateway = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(gateway)


class ControlAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_backends = dict(gateway.BACKENDS)
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.auth = root / "gateway-auth.json"
        self.env = root / "faryo.env"
        self.secret = root / "state" / "cookie-secret"
        self.auth.write_text(json.dumps({
            "users": {
                "operator": {"bcrypt_hash": "unused", "routes": ["txy"]},
                "other": {"bcrypt_hash": "unused", "routes": ["txy"]},
            }
        }), encoding="utf-8")
        self.env.write_text(
            "FARYO_GATEWAY_ROUTES=txy\n"
            "FARYO_TXY_OWNER_TOKEN=anonymous-owner-token\n",
            encoding="utf-8",
        )
        self.config = gateway.GatewayConfig(self.auth, self.env, root / "portal", self.secret)

    def tearDown(self) -> None:
        gateway.BACKENDS.clear()
        gateway.BACKENDS.update(self.original_backends)
        self.temp.cleanup()

    def append(self, **overrides) -> None:
        values = {
            "username": "operator",
            "route": "txy",
            "action": "send",
            "target": "private-session-id",
            "request_id": "request-0001",
            "status": 200,
            "duration_ms": 12,
            "idempotent": False,
        }
        values.update(overrides)
        self.config.append_control_audit(**values)

    def test_audit_file_is_mode_600_and_contains_no_raw_target_or_body_fields(self) -> None:
        self.append()

        text = self.config.control_audit_path.read_text(encoding="utf-8")
        row = json.loads(text)
        self.assertEqual(stat.S_IMODE(self.config.control_audit_path.stat().st_mode), 0o600)
        self.assertNotIn("private-session-id", text)
        self.assertRegex(row["target"], r"^t_[0-9a-f]{16}$")
        self.assertTrue({"time", "requestId", "user", "route", "action", "target", "result", "http", "durationMs", "idempotent"}.issubset(row))
        for forbidden in ("text", "prompt", "message", "title", "cwd", "token", "cookie", "ip"):
            self.assertNotIn(forbidden, {key.lower() for key in row})

    def test_activity_is_scoped_by_user_and_route_and_skips_corrupt_tail(self) -> None:
        self.append(request_id="operator-row")
        self.append(username="other", request_id="other-row")
        with self.config.control_audit_path.open("a", encoding="utf-8") as stream:
            stream.write("{broken tail\n")

        entries = self.config.control_activity("operator", 30)

        self.assertEqual([entry["requestId"] for entry in entries], ["operator-row"])
        self.assertNotIn("user", entries[0])

    def test_audit_retention_keeps_the_newest_bounded_rows(self) -> None:
        with mock.patch.object(gateway, "CONTROL_AUDIT_MAX_ROWS", 3):
            for index in range(6):
                self.append(request_id=f"request-{index}")

        rows = [json.loads(line) for line in self.config.control_audit_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["requestId"] for row in rows], ["request-3", "request-4", "request-5"])

    def test_audit_io_failure_never_blocks_control(self) -> None:
        with mock.patch.object(gateway.os, "open", side_effect=OSError("read-only fixture")):
            self.append()

        self.assertFalse(self.config.control_audit_path.exists())

    def test_revoke_sessions_advances_auth_epoch_without_touching_routes(self) -> None:
        before = self.config.auth_epoch("operator")
        routes = self.config.user_routes("operator")

        self.config.revoke_sessions("operator")

        self.assertGreater(self.config.auth_epoch("operator"), before)
        self.assertEqual(self.config.user_routes("operator"), routes)


if __name__ == "__main__":
    unittest.main()
