from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from faryo_cli import cli, diagnostics, installer, migration, operations, runtime


class FaryoCliTest(unittest.TestCase):
    def layout(self, root: Path, *, unsafe: bool = False) -> diagnostics.Layout:
        faryo_home = root / ".faryo"
        owner_env = faryo_home / "owner/config/faryo.env"
        gateway_env = faryo_home / "gateway/config/faryo.env"
        gateway_auth = faryo_home / "gateway/config/gateway-auth.json"
        owner_env.parent.mkdir(parents=True)
        gateway_env.parent.mkdir(parents=True)
        owner_env.write_text(
            "FARYO_OWNER_HOST=127.0.0.1\n"
            "FARYO_OWNER_PORT=8765\n"
            "FARYO_OWNER_TOKEN=private-owner-token\n"
            f"FARYO_PYTHON={sys.executable}\n"
            "FARYO_CODEX_BIN=/private/bin/codex\n",
            encoding="utf-8",
        )
        gateway_env.write_text(
            "GATEWAY_HOST=127.0.0.1\n"
            "GATEWAY_PORT=8780\n"
            "FARYO_GATEWAY_ROUTES=txy\n"
            "FARYO_GATEWAY_SESSION_HOURS=720\n"
            f"FARYO_PYTHON={sys.executable}\n"
            "FARYO_TXY_OWNER_TOKEN=private-owner-token\n",
            encoding="utf-8",
        )
        gateway_auth.write_text('{"users":{"private@example.invalid":{}}}\n', encoding="utf-8")
        for path in (owner_env, gateway_env, gateway_auth):
            path.chmod(0o644 if unsafe else 0o600)
        return diagnostics.Layout(root, faryo_home, owner_env, gateway_env, gateway_auth, ROOT)

    def report(self, layout: diagnostics.Layout) -> dict:
        def version(command, *_args, **_kwargs):
            return {"tmux": "tmux 3.5", "codex": "codex-cli 0.test"}.get(command)

        def state(name):
            return {
                "faryo-owner.service": "inactive",
                "faryo-gateway.service": "active",
                "faryo-owner-keepalive.timer": "active",
            }.get(name, "inactive")

        with (
            mock.patch.object(diagnostics, "command_version", side_effect=version),
            mock.patch.object(diagnostics, "resolve_codex", return_value="/fixture/codex"),
            mock.patch.object(diagnostics, "argv_version", return_value="codex-cli 0.test"),
            mock.patch.object(diagnostics, "systemd_user_available", return_value=True),
            mock.patch.object(diagnostics, "service_state", side_effect=state),
            mock.patch.object(diagnostics, "http_status", side_effect=lambda _host, port, _path: 200 if port in {8765, 8780} else None),
            mock.patch.object(diagnostics, "tmux_session_exists", return_value=True),
            mock.patch.object(diagnostics, "tmux_session_count", return_value=4),
            mock.patch.object(diagnostics.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"),
        ):
            return diagnostics.build_report(layout)

    def test_doctor_report_is_privacy_safe_and_marks_legacy_supervision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self.report(self.layout(Path(temp)))

        encoded = json.dumps(report, ensure_ascii=False).lower()
        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"]["error"], 0)
        self.assertEqual(report["runtime"]["tmuxSessions"], 4)
        self.assertTrue(diagnostics.compact_status(report)["legacyOwner"])
        for forbidden in ("private-owner-token", "private@example.invalid", str(Path(temp)).lower(), "/private/bin/codex"):
            self.assertNotIn(forbidden, encoded)

    def test_unsafe_private_files_are_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self.report(self.layout(Path(temp), unsafe=True))

        self.assertFalse(report["ok"])
        failed = {item["id"] for item in report["checks"] if item["status"] == "error"}
        self.assertTrue({"owner-config", "gateway-config", "gateway-auth"}.issubset(failed))

    def test_cli_json_and_human_output_have_stable_exit_codes(self) -> None:
        report = {
            "schemaVersion": 1,
            "ok": True,
            "checks": [{"id": "python", "status": "ok", "detail": "Python test"}],
            "counts": {"ok": 1, "warn": 0, "error": 0},
            "services": {"owner": "active", "gateway": "active", "legacyKeepalive": "inactive"},
            "runtime": {"environment": "venv", "tmuxSessions": 3},
        }
        with mock.patch.object(cli, "build_report", return_value=report):
            output = StringIO()
            with redirect_stdout(output):
                code = cli.main(["doctor", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["counts"]["ok"], 1)

            output = StringIO()
            with redirect_stdout(output):
                code = cli.main(["status"])
            self.assertEqual(code, 0)
            self.assertIn("Owner:  active", output.getvalue())

    def test_source_root_discovery_uses_application_markers(self) -> None:
        self.assertEqual(diagnostics.discover_source_root({"FARYO_INSTALL_ROOT": str(ROOT)}), ROOT)
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(diagnostics.discover_source_root({"FARYO_INSTALL_ROOT": temp}))

    def test_codex_resolution_supports_configured_and_nvm_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            older = home / ".nvm/versions/node/v22.0.0/bin/codex"
            latest = home / ".nvm/versions/node/v24.0.0/bin/codex"
            for path in (older, latest):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("#!/bin/sh\n", encoding="utf-8")
                path.chmod(0o700)

            with mock.patch.object(diagnostics.shutil, "which", return_value=None):
                self.assertEqual(diagnostics.resolve_codex("", home), str(latest))
                self.assertEqual(diagnostics.resolve_codex(str(older), home), str(older))

    def test_codex_javascript_launcher_uses_sibling_node(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "versions/node/v24.0.0"
            node = root / "bin/node"
            launcher = root / "bin/codex"
            script = root / "lib/node_modules/@openai/codex/bin/codex.js"
            node.parent.mkdir(parents=True)
            script.parent.mkdir(parents=True)
            node.write_text("runtime", encoding="utf-8")
            script.write_text("cli", encoding="utf-8")
            node.chmod(0o700)
            script.chmod(0o700)
            launcher.symlink_to(Path("../lib/node_modules/@openai/codex/bin/codex.js"))

            self.assertEqual(
                diagnostics.codex_argv(str(launcher), "--version"),
                [str(node), str(script), "--version"],
            )

    def test_legacy_start_is_idempotent_and_keeps_gateway_managed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            layout = self.layout(Path(temp))
            actions = []

            def exists(name):
                return name in {"faryo-gateway.service", "faryo-owner-keepalive.timer"}

            with (
                mock.patch.object(operations, "unit_exists", side_effect=exists),
                mock.patch.object(operations, "control_service", side_effect=lambda name, action: actions.append((name, action))),
                mock.patch.object(operations, "http_status", return_value=200),
                mock.patch.object(operations, "run_legacy_owner") as legacy,
                mock.patch.object(operations, "wait_for_health") as wait,
            ):
                result = operations.service_operation("start", layout)

        self.assertEqual(result, "started")
        self.assertEqual(actions, [
            ("faryo-owner-keepalive.timer", "start"),
            ("faryo-gateway.service", "start"),
        ])
        legacy.assert_not_called()
        wait.assert_called_once_with(layout)

    def test_direct_stop_never_touches_tmux_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            layout = self.layout(Path(temp))
            actions = []
            with (
                mock.patch.object(operations, "unit_exists", return_value=True),
                mock.patch.object(operations, "control_service", side_effect=lambda name, action: actions.append((name, action))),
                mock.patch.object(operations, "run_legacy_owner") as legacy,
            ):
                result = operations.service_operation("stop", layout)

        self.assertEqual(result, "stopped")
        self.assertEqual(actions, [
            ("faryo-gateway.service", "stop"),
            ("faryo-owner.service", "stop"),
        ])
        legacy.assert_not_called()

    def test_open_prints_only_loopback_gateway_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            layout = self.layout(Path(temp))
            self.assertEqual(operations.open_gateway(layout, print_only=True), "http://127.0.0.1:8780/")

    def test_cli_service_failures_are_bounded(self) -> None:
        output = StringIO()
        with mock.patch.object(cli, "service_operation", side_effect=operations.OperationError("bounded failure")):
            with redirect_stdout(output), mock.patch("sys.stderr", new=StringIO()) as error:
                code = cli.main(["restart"])
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("bounded failure", error.getvalue())

    def test_direct_owner_spec_keeps_token_out_of_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            layout = self.layout(Path(temp))
            spec = runtime.owner_process(layout)

        self.assertIn("private-owner-token", spec.environment.values())
        self.assertNotIn("private-owner-token", " ".join(spec.argv))
        self.assertEqual(spec.argv[-4:], ["--host", "127.0.0.1", "--port", "8765"])
        self.assertEqual(spec.environment["FARYO_PYTHON"], sys.executable)

    def test_direct_gateway_spec_uses_private_files_without_token_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            layout = self.layout(Path(temp))
            spec = runtime.gateway_process(layout)

        self.assertIn("--auth-config", spec.argv)
        self.assertIn("--owner-env", spec.argv)
        self.assertEqual(spec.argv[spec.argv.index("--owner-env") + 1], str(layout.gateway_env))
        self.assertNotIn("private-owner-token", " ".join(spec.argv))
        self.assertEqual(spec.environment["FARYO_GATEWAY_SESSION_HOURS"], "720")

        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); import server; print(','.join(server.BACKENDS))",
                str(ROOT / "apps/gateway/server"),
            ],
            env=spec.environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.strip(), "txy")

    def test_direct_runtime_rejects_non_loopback_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            layout = self.layout(Path(temp))
            body = layout.owner_env.read_text(encoding="utf-8").replace("127.0.0.1", "0.0.0.0")
            layout.owner_env.write_text(body, encoding="utf-8")
            layout.owner_env.chmod(0o600)
            with self.assertRaisesRegex(operations.OperationError, "must remain loopback"):
                runtime.owner_process(layout)

    def test_internal_owner_command_executes_only_validated_spec(self) -> None:
        spec = runtime.ProcessSpec([sys.executable, "server.py"], ROOT, {})
        with (
            mock.patch.object(cli, "owner_process", return_value=spec),
            mock.patch.object(cli, "exec_process") as execute,
        ):
            code = cli.main(["internal", "run-owner"])
        self.assertEqual(code, 0)
        execute.assert_called_once_with(spec)

    def test_service_units_use_unified_cli_and_no_legacy_owner_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            layout = self.layout(Path(temp))
            owner = installer.rendered_unit("owner", layout, sys.executable)
            gateway = installer.rendered_unit("gateway", layout, sys.executable)

        self.assertIn("-m faryo_cli internal run-owner", owner)
        self.assertIn("-m faryo_cli internal run-gateway", gateway)
        self.assertNotIn("start-web-owner.sh", owner)
        self.assertNotIn("run-gateway.sh", gateway)
        self.assertNotIn("@FARYO_", owner + gateway)

    def test_atomic_unit_install_backs_up_existing_unit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            layout = self.layout(root)
            xdg = root / "config"
            unit_dir = xdg / "systemd/user"
            unit_dir.mkdir(parents=True)
            old = unit_dir / "faryo-owner.service"
            old.write_text("old unit\n", encoding="utf-8")
            with (
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=False),
                mock.patch.object(installer, "systemctl") as systemctl,
            ):
                installed = installer.install_user_units(layout, components=("owner",), python=sys.executable)

            backup = root / ".local/share/faryo/state/unit-backups/faryo-owner.service.previous"
            self.assertEqual(installed, ["faryo-owner.service"])
            self.assertEqual(backup.read_text(encoding="utf-8"), "old unit\n")
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertEqual(old.stat().st_mode & 0o777, 0o644)
            systemctl.assert_called_once_with("daemon-reload")

    def test_unit_path_rejects_control_characters(self) -> None:
        with self.assertRaisesRegex(operations.OperationError, "control characters"):
            installer.unit_escape("bad\npath")
        self.assertEqual(installer.unit_path_escape("/path/with space"), "/path/with\\x20space")

    def test_owner_migration_stops_only_legacy_supervision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            layout = self.layout(Path(temp))
            calls = []
            with (
                mock.patch.object(migration, "unit_exists", return_value=True),
                mock.patch.object(migration, "legacy_owner_exists", return_value=True),
                mock.patch.object(migration, "service_state", return_value="inactive"),
                mock.patch.object(migration, "tmux_geometry", side_effect=[{"faryo1": (145, 44)}, {"faryo1": (145, 44)}]),
                mock.patch.object(migration, "stop_legacy_owner") as stop_legacy,
                mock.patch.object(migration, "wait_owner") as wait_owner,
                mock.patch.object(migration, "systemctl", side_effect=lambda *args, **kwargs: calls.append((args, kwargs))),
            ):
                result = migration.migrate_owner(layout)

        self.assertEqual(result, "migrated")
        stop_legacy.assert_called_once_with()
        wait_owner.assert_called_once_with(layout)
        self.assertIn((("enable", "faryo-owner.service"), {}), calls)
        self.assertIn((("start", "faryo-owner.service"), {}), calls)
        self.assertIn((("disable", "faryo-owner-keepalive.timer"), {"check": False}), calls)

    def test_owner_migration_restores_legacy_on_health_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            layout = self.layout(Path(temp))
            with (
                mock.patch.object(migration, "unit_exists", return_value=True),
                mock.patch.object(migration, "legacy_owner_exists", return_value=True),
                mock.patch.object(migration, "service_state", return_value="inactive"),
                mock.patch.object(migration, "tmux_geometry", return_value={"faryo1": (145, 44)}),
                mock.patch.object(migration, "stop_legacy_owner"),
                mock.patch.object(migration, "wait_owner", side_effect=operations.OperationError("not healthy")),
                mock.patch.object(migration, "restore_legacy") as restore,
                mock.patch.object(migration, "systemctl"),
            ):
                with self.assertRaisesRegex(operations.OperationError, "not healthy"):
                    migration.migrate_owner(layout)

        restore.assert_called_once_with(layout)

    def test_owner_migration_rejects_existing_geometry_change(self) -> None:
        with self.assertRaisesRegex(operations.OperationError, "geometry changed"):
            migration.verify_geometry({"faryo1": (145, 44)}, {"faryo1": (500, 44)})

    def test_install_requires_explicit_legacy_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            layout = self.layout(Path(temp))
            with mock.patch.object(migration, "legacy_owner_exists", return_value=True):
                with self.assertRaisesRegex(operations.OperationError, "requires --migrate-owner"):
                    installer.install_services(layout, python=sys.executable)

    def test_install_starts_direct_services_after_atomic_units(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            layout = self.layout(root)
            xdg = root / "config"
            actions = []
            with (
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=False),
                mock.patch.object(migration, "legacy_owner_exists", return_value=False),
                mock.patch.object(installer, "systemctl", side_effect=lambda *args, **kwargs: actions.append((args, kwargs))),
                mock.patch.object(operations, "control_service", side_effect=lambda name, action: actions.append(((name, action), {}))),
                mock.patch.object(operations, "wait_for_health") as wait,
            ):
                result = installer.install_services(layout, python=sys.executable)

            self.assertEqual(result, "installed")
            self.assertTrue((xdg / "systemd/user/faryo-owner.service").is_file())
            self.assertTrue((xdg / "systemd/user/faryo-gateway.service").is_file())
            self.assertIn((("faryo-owner.service", "start"), {}), actions)
            self.assertIn((("faryo-gateway.service", "restart"), {}), actions)
            wait.assert_called_once_with(layout)

    def test_install_restores_previous_units_when_health_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            layout = self.layout(root)
            xdg = root / "config"
            unit_dir = xdg / "systemd/user"
            unit_dir.mkdir(parents=True)
            gateway = unit_dir / "faryo-gateway.service"
            gateway.write_text("old gateway unit\n", encoding="utf-8")
            with (
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=False),
                mock.patch.object(migration, "legacy_owner_exists", return_value=False),
                mock.patch.object(installer, "systemctl"),
                mock.patch.object(operations, "control_service"),
                mock.patch.object(operations, "wait_for_health", side_effect=operations.OperationError("not healthy")),
            ):
                with self.assertRaisesRegex(operations.OperationError, "not healthy"):
                    installer.install_services(layout, python=sys.executable)

            self.assertEqual(gateway.read_text(encoding="utf-8"), "old gateway unit\n")
            self.assertFalse((unit_dir / "faryo-owner.service").exists())


if __name__ == "__main__":
    unittest.main()
