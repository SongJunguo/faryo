import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = APP_DIR / "codex_update_preflight.py"
spec = importlib.util.spec_from_file_location("codex_update_preflight", MODULE_PATH)
assert spec and spec.loader
preflight = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = preflight
spec.loader.exec_module(preflight)


class FakeRunner:
    def __init__(self, installed="0.148.0", latest="0.149.0", update_ok=True):
        self.installed = installed
        self.latest = latest
        self.update_ok = update_ok
        self.calls = []

    def __call__(self, argv, **_kwargs):
        self.calls.append(list(argv))
        if argv[-1:] == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, f"codex-cli {self.installed}\n", "")
        if "view" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.latest), "")
        if "install" in argv:
            if self.update_ok:
                self.installed = self.latest
                return subprocess.CompletedProcess(argv, 0, "updated", "")
            return subprocess.CompletedProcess(argv, 1, "", "failed")
        return subprocess.CompletedProcess(argv, 1, "", "unsupported")


class CodexUpdatePreflightTest(unittest.TestCase):
    def launch(self, root: Path):
        node = root / "bin/node"
        npm = root / "bin/npm"
        script = root / "lib/node_modules/@openai/codex/bin/codex.js"
        for path in (node, npm, script):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")
            path.chmod(0o700)
        return [str(node), str(script), "-c", "check_for_update_on_startup=false"]

    def test_available_nvm_update_uses_matching_npm_and_confirms_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            launch = self.launch(root)
            runner = FakeRunner()
            state = preflight.run_preflight(
                launch,
                root / "state.json",
                runner=runner,
                environment={"HOME": temp, "PATH": "/usr/bin"},
                now=100,
            )
            self.assertEqual((root / "state.json").stat().st_mode & 0o777, 0o600)

        self.assertEqual(state["result"], "updated")
        install = next(call for call in runner.calls if "install" in call)
        self.assertEqual(install[:4], [str(root / "bin/npm"), "install", "-g", "@openai/codex@latest"])

    def test_current_version_does_not_reinstall(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = FakeRunner(installed="0.149.0", latest="0.149.0")
            state = preflight.run_preflight(
                self.launch(root),
                root / "state.json",
                runner=runner,
                environment={"HOME": temp, "PATH": "/usr/bin"},
                now=100,
            )

        self.assertEqual(state["result"], "current")
        self.assertFalse(any("install" in call for call in runner.calls))

    def test_recent_current_check_is_reused_without_registry_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state_file = root / "state.json"
            preflight.write_state(
                state_file,
                {
                    "schemaVersion": 1,
                    "checkedAt": 90,
                    "installedVersion": "0.149.0",
                    "latestVersion": "0.149.0",
                    "result": "current",
                },
            )
            runner = FakeRunner(installed="0.149.0", latest="0.150.0")
            state = preflight.run_preflight(
                self.launch(root),
                state_file,
                runner=runner,
                environment={"HOME": temp, "PATH": "/usr/bin"},
                now=100,
            )

        self.assertEqual(state["latestVersion"], "0.149.0")
        self.assertFalse(any("view" in call for call in runner.calls))

    def test_failed_update_is_bounded_and_preserves_installed_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = FakeRunner(update_ok=False)
            state = preflight.run_preflight(
                self.launch(root),
                root / "state.json",
                runner=runner,
                environment={"HOME": temp, "PATH": "/usr/bin"},
                now=100,
            )

        self.assertEqual(state["result"], "failed")
        self.assertEqual(state["installedVersion"], "0.148.0")

    def test_runtime_environment_prepends_matching_node_bin(self):
        launch = ["/runtime/v24/bin/node", "/runtime/v24/lib/codex.js"]
        environment = preflight.codex_runtime.codex_environment(
            preflight.command_prefix(launch),
            {"PATH": "/usr/bin:/bin"},
        )
        self.assertEqual(environment["PATH"].split(os.pathsep)[0], "/runtime/v24/bin")

    def test_preflight_failure_still_executes_the_installed_codex(self):
        with tempfile.TemporaryDirectory() as temp:
            launch = ["/runtime/bin/node", "/runtime/lib/codex.js"]
            argv = [
                "codex_update_preflight.py",
                "--session",
                "faryo1",
                "--state-dir",
                temp,
                "--",
                *launch,
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(preflight, "run_preflight", side_effect=RuntimeError("fixture")),
                mock.patch.object(preflight, "set_tmux_status") as status,
                mock.patch.object(preflight.os, "execvpe", side_effect=OSError("fixture")) as execute,
            ):
                self.assertEqual(preflight.main(), 127)

        status.assert_called_once_with("faryo1", "failed")
        self.assertEqual(execute.call_args.args[0], launch[0])
        self.assertEqual(execute.call_args.args[1], launch)


if __name__ == "__main__":
    unittest.main()
