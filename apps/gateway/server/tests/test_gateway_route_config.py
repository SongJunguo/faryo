#!/usr/bin/env python3
"""Enabled-route and private runtime configuration regression tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[4]
SERVER_PATH = REPO_ROOT / "apps" / "gateway" / "server" / "server.py"

spec = importlib.util.spec_from_file_location("faryo_gateway_route_server", SERVER_PATH)
gateway = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(gateway)


class GatewayRouteConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_backends = dict(gateway.BACKENDS)

    def tearDown(self) -> None:
        gateway.BACKENDS.clear()
        gateway.BACKENDS.update(self.original_backends)

    def test_load_backends_includes_enabled_route_only(self) -> None:
        backends = gateway.load_backends({
            "FARYO_GATEWAY_ROUTES": "txy",
            "FARYO_TXY_OWNER_PORT": "9876",
        })

        self.assertEqual(list(backends), ["txy"])
        self.assertEqual(backends["txy"][1], 9876)

    def test_unknown_route_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported FARYO_GATEWAY_ROUTES"):
            gateway.load_backends({"FARYO_GATEWAY_ROUTES": "txy,unknown"})

    def test_each_route_fetches_enough_history_for_the_requested_page(self) -> None:
        gateway.BACKENDS.clear()
        gateway.BACKENDS["txy"] = ("127.0.0.1", 8765, "TXY")
        handler = object.__new__(gateway.GatewayHandler)
        handler.owner_json_request = mock.Mock(return_value={
            "ok": True,
            "activeCount": 0,
            "activeSessions": [],
            "sessions": [],
            "historyTotal": 0,
        })
        handler.max_running_for = mock.Mock(return_value=8)

        handler.owner_agent_sessions("txy", "tester", 1)
        self.assertEqual(
            handler.owner_json_request.call_args.args[1],
            "/api/agent-sessions?view=split&limit=10&offset=0",
        )

        handler.owner_agent_sessions("txy", "tester", 2)
        self.assertEqual(
            handler.owner_json_request.call_args.args[1],
            "/api/agent-sessions?view=split&limit=20&offset=0",
        )

    def test_workbench_keeps_active_sessions_above_ten_item_history_pages(self) -> None:
        gateway.BACKENDS.clear()
        gateway.BACKENDS.update({
            "txy": ("127.0.0.1", 8765, "TXY"),
            "hp": ("127.0.0.1", 8766, "HP"),
        })
        handler = object.__new__(gateway.GatewayHandler)
        histories = {
            "txy": [{"id": f"txy-{index}", "updatedTs": 40 - index} for index in range(20)],
            "hp": [{"id": f"hp-{index}", "updatedTs": 39.5 - index} for index in range(20)],
        }

        def route_payload(route: str, _username: str, page: int) -> dict:
            return {
                "activeSessions": [{"id": f"active-{route}", "tmuxSession": f"live-{route}", "updatedTs": 100}],
                "sessions": histories[route][:page * gateway.HISTORY_PAGE_SIZE],
                "historyTotal": len(histories[route]),
                "activeCount": 1,
                "maxRunning": 8,
                "canCreate": True,
            }

        handler.owner_agent_sessions = mock.Mock(side_effect=route_payload)
        config = mock.Mock()
        config.user_routes.return_value = ["txy", "hp"]
        config.list_bridge_packages.return_value = []
        config.mcp_user = "mcp-user"
        handler.server = mock.Mock(config=config)

        with mock.patch.object(gateway, "backend_status", side_effect=lambda route: {"id": route}):
            first = handler.workbench_payload("tester", 1)
            second = handler.workbench_payload("tester", 2)

        self.assertEqual(len(first["activeSessions"]), 2)
        self.assertEqual(len(first["sessions"]), 10)
        self.assertEqual(first["history"], {
            "page": 1,
            "pageSize": 10,
            "total": 40,
            "totalPages": 4,
            "hasPrevious": False,
            "hasNext": True,
        })
        self.assertEqual(len(second["activeSessions"]), 2)
        self.assertEqual(len(second["sessions"]), 10)
        self.assertEqual(second["history"]["page"], 2)
        self.assertTrue(set(item["id"] for item in first["sessions"]).isdisjoint(
            item["id"] for item in second["sessions"]
        ))

    def test_portal_has_separate_active_and_paginated_history_regions(self) -> None:
        gateway.BACKENDS.clear()
        gateway.BACKENDS["txy"] = ("127.0.0.1", 8765, "TXY")

        page = gateway.portal_html("tester", ["txy"])

        self.assertIn('id="activeSessionList"', page)
        self.assertIn('id="sessionList"', page)
        self.assertIn('id="historyPrev"', page)
        self.assertIn('id="historyNext"', page)
        self.assertIn('/api/workbench?page=', page)
        self.assertIn("active&&managed?", page)

    def test_gateway_config_requires_token_for_enabled_route_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            auth = root / "gateway-auth.json"
            env = root / "faryo.env"
            auth.write_text(json.dumps({
                "users": {
                    "tester": {
                        "bcrypt_hash": "not-checked-during-load",
                        "routes": ["txy"],
                        "default_route": "txy",
                    }
                }
            }), encoding="utf-8")
            env.write_text(
                "FARYO_GATEWAY_ROUTES=txy\n"
                "FARYO_TXY_OWNER_TOKEN=enabled-token\n",
                encoding="utf-8",
            )

            config = gateway.GatewayConfig(
                auth,
                env,
                root / "portal",
                root / "state" / "cookie-secret",
            )

            self.assertEqual(config.owner_tokens, {"txy": "enabled-token"})
            self.assertEqual(list(gateway.BACKENDS), ["txy"])
            self.assertEqual(config.max_running("txy"), 8)

    def test_gateway_config_accepts_route_max_running_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            auth = root / "gateway-auth.json"
            env = root / "faryo.env"
            auth.write_text(json.dumps({
                "users": {
                    "tester": {
                        "bcrypt_hash": "not-checked-during-load",
                        "routes": ["txy"],
                    }
                }
            }), encoding="utf-8")
            env.write_text(
                "FARYO_GATEWAY_ROUTES=txy\n"
                "FARYO_TXY_OWNER_TOKEN=enabled-token\n"
                "FARYO_TXY_MAX_RUNNING=12\n",
                encoding="utf-8",
            )

            config = gateway.GatewayConfig(
                auth,
                env,
                root / "portal",
                root / "state" / "cookie-secret",
            )

            self.assertEqual(config.max_running("txy"), 12)

    def test_gateway_config_rejects_invalid_route_max_running(self) -> None:
        for invalid in ("0", "33", "many"):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                auth = root / "gateway-auth.json"
                env = root / "faryo.env"
                auth.write_text(json.dumps({
                    "users": {
                        "tester": {
                            "bcrypt_hash": "not-checked-during-load",
                            "routes": ["txy"],
                        }
                    }
                }), encoding="utf-8")
                env.write_text(
                    "FARYO_GATEWAY_ROUTES=txy\n"
                    "FARYO_TXY_OWNER_TOKEN=enabled-token\n"
                    f"FARYO_TXY_MAX_RUNNING={invalid}\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ValueError, "FARYO_TXY_MAX_RUNNING"):
                    gateway.GatewayConfig(
                        auth,
                        env,
                        root / "portal",
                        root / "state" / "cookie-secret",
                    )

    def test_gateway_config_reads_shell_quoted_private_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            auth = root / "gateway-auth.json"
            env = root / "faryo.env"
            auth.write_text(json.dumps({
                "users": {
                    "tester": {
                        "bcrypt_hash": "not-checked-during-load",
                        "routes": ["txy"],
                    }
                }
            }), encoding="utf-8")
            env.write_text(
                "FARYO_GATEWAY_ROUTES='txy'\n"
                "FARYO_TXY_OWNER_TOKEN='quoted test token'\n",
                encoding="utf-8",
            )

            config = gateway.GatewayConfig(
                auth,
                env,
                root / "portal",
                root / "state" / "cookie-secret",
            )

            self.assertEqual(config.owner_tokens, {"txy": "quoted test token"})

    def test_enabled_route_still_requires_its_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            auth = root / "gateway-auth.json"
            env = root / "faryo.env"
            auth.write_text(json.dumps({
                "users": {
                    "tester": {
                        "bcrypt_hash": "not-checked-during-load",
                        "routes": ["txy"],
                    }
                }
            }), encoding="utf-8")
            env.write_text("FARYO_GATEWAY_ROUTES=txy\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "FARYO_TXY_OWNER_TOKEN"):
                gateway.GatewayConfig(
                    auth,
                    env,
                    root / "portal",
                    root / "state" / "cookie-secret",
                )

    def test_auth_generator_defaults_to_private_runtime_paths(self) -> None:
        module_path = REPO_ROOT / "apps" / "gateway" / "scripts" / "generate-gateway-auth-config.py"
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(
            os.environ,
            {"FARYO_HOME": temp},
            clear=False,
        ):
            generator_spec = importlib.util.spec_from_file_location("faryo_gateway_auth_generator", module_path)
            generator = importlib.util.module_from_spec(generator_spec)
            assert generator_spec and generator_spec.loader
            generator_spec.loader.exec_module(generator)

            self.assertEqual(generator.ENV_FILE, Path(temp) / "gateway" / "config" / "faryo.env")
            self.assertEqual(generator.AUTH_FILE, Path(temp) / "gateway" / "config" / "gateway-auth.json")

    def test_shell_loader_does_not_require_disabled_route_tokens(self) -> None:
        library = REPO_ROOT / "apps" / "gateway" / "scripts" / "_lib.sh"
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / "faryo.env"
            env_file.write_text(
                "FARYO_GATEWAY_ROUTES=txy\n"
                "FARYO_TXY_OWNER_TOKEN=enabled-token\n",
                encoding="utf-8",
            )
            process_env = {
                "HOME": os.environ.get("HOME", temp),
                "PATH": os.environ.get("PATH", ""),
                "FARYO_GATEWAY_ENV": str(env_file),
            }

            result = subprocess.run(
                ["bash", "-c", 'source "$1"; load_env', "bash", str(library)],
                env=process_env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_auth_generator_reads_mode_separated_password_file(self) -> None:
        module_path = REPO_ROOT / "apps" / "gateway" / "scripts" / "generate-gateway-auth-config.py"
        generator_spec = importlib.util.spec_from_file_location("faryo_gateway_password_generator", module_path)
        generator = importlib.util.module_from_spec(generator_spec)
        assert generator_spec and generator_spec.loader
        generator_spec.loader.exec_module(generator)
        with tempfile.TemporaryDirectory() as temp:
            password_file = Path(temp) / "password"
            password_file.write_text("generic-test-password\n", encoding="utf-8")

            password = generator.gateway_password({"FARYO_GATEWAY_PASSWORD_FILE": str(password_file)})

            self.assertEqual(password, "generic-test-password")

    def test_local_initializer_preserves_existing_login_config(self) -> None:
        script = REPO_ROOT / "apps" / "gateway" / "scripts" / "init-local-gateway.sh"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            faryo_home = root / ".faryo"
            owner_env = faryo_home / "owner" / "config" / "faryo.env"
            gateway_env = faryo_home / "gateway" / "config" / "faryo.env"
            auth = faryo_home / "gateway" / "config" / "gateway-auth.json"
            owner_env.parent.mkdir(parents=True)
            auth.parent.mkdir(parents=True)
            owner_env.write_text(
                "FARYO_OWNER_TOKEN=generic-owner-token\n"
                "FARYO_OWNER_HOST=127.0.0.1\n"
                "FARYO_OWNER_PORT=8765\n",
                encoding="utf-8",
            )
            original_auth = '{"users":{"tester":{"bcrypt_hash":"preserve-me","routes":["txy"]}}}\n'
            auth.write_text(original_auth, encoding="utf-8")
            process_env = {
                "HOME": str(root),
                "PATH": os.environ.get("PATH", ""),
                "FARYO_HOME": str(faryo_home),
                "FARYO_OWNER_ENV": str(owner_env),
                "FARYO_GATEWAY_ENV": str(gateway_env),
                "GATEWAY_AUTH_CONFIG": str(auth),
                "FARYO_PYTHON": sys.executable,
            }

            result = subprocess.run(
                ["bash", str(script)],
                env=process_env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(auth.read_text(encoding="utf-8"), original_auth)
            self.assertFalse((auth.parent / "initial-password").exists())
            self.assertEqual(auth.stat().st_mode & 0o777, 0o600)
            self.assertEqual(gateway_env.stat().st_mode & 0o777, 0o600)
            self.assertIn("FARYO_TXY_MAX_RUNNING=8\n", gateway_env.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
