import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "devfs.py"
SPEC = importlib.util.spec_from_file_location("faryo_owner_devfs", MODULE_PATH)
assert SPEC and SPEC.loader
devfs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = devfs
SPEC.loader.exec_module(devfs)


class DevfsToolsTest(unittest.TestCase):
    def test_search_text_uses_owner_native_search(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / "one.txt").write_text("alpha\nneedle\n", encoding="utf-8")
            with mock.patch.object(devfs, "_allowed_roots", return_value=[root]):
                result, status = devfs.handle_devfs({"action": "search_text", "path": str(root), "query": "needle"})
        self.assertEqual(status, 200)
        self.assertEqual(result["match_count"], 1)

    def test_git_status_is_read_only_structured_action(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / ".git").mkdir()
            completed = mock.Mock(returncode=0, stdout="## main\n", stderr="")
            with mock.patch.object(devfs, "_allowed_roots", return_value=[root]), mock.patch.object(devfs.subprocess, "run", return_value=completed) as run:
                result, status = devfs.handle_devfs({"action": "git_status", "cwd": str(root)})
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args.args[0], ["git", "status", "--short", "--branch"])

    def test_task_selects_fixed_command_without_shell_input(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / "package.json").write_text(json.dumps({"scripts": {"test": "node test.js"}}), encoding="utf-8")
            completed = mock.Mock(returncode=0, stdout="ok\n", stderr="")
            with mock.patch.object(devfs, "_allowed_roots", return_value=[root]), mock.patch.object(devfs.subprocess, "run", return_value=completed) as run:
                result, status = devfs.handle_task({"action": "run_tests", "cwd": str(root), "command": "rm -rf /"})
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args.args[0], ["npm", "test"])
        self.assertNotIn("shell", run.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
