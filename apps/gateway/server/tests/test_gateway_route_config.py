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


if __name__ == "__main__":
    unittest.main()
