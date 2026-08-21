#!/usr/bin/env python3
"""Owner environment initialization regression tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
INIT_SCRIPT = REPO_ROOT / "apps" / "owner" / "scripts" / "init-owner-env.sh"


class InitOwnerEnvTest(unittest.TestCase):
    def test_initializer_needs_no_gateway_and_migrates_legacy_directory_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            faryo_home = Path(temp) / ".faryo"
            env_file = faryo_home / "owner" / "config" / "faryo.env"
            env_file.parent.mkdir(parents=True)
            env_file.write_text(
                "FARYO_OWNER_TOKEN=generic-owner-token\n"
                "FARYO_PROJECT_WORKBENCH_GATEWAY_URL=http://retired.invalid\n"
                "FARYO_PROJECT_WORKBENCH_ALLOWED_ROOTS=/workspace/a:/workspace/b\n",
                encoding="utf-8",
            )
            process_env = {
                "HOME": temp,
                "PATH": os.environ.get("PATH", ""),
                "FARYO_HOME": str(faryo_home),
                "FARYO_OWNER_ENV": str(env_file),
                "FARYO_PYTHON": sys.executable,
            }

            result = subprocess.run(
                ["bash", str(INIT_SCRIPT)],
                env=process_env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            values = dict(
                line.split("=", 1)
                for line in env_file.read_text(encoding="utf-8").splitlines()
                if line and "=" in line
            )
            self.assertEqual(values["FARYO_OWNER_TOKEN"], "generic-owner-token")
            self.assertEqual(values["FARYO_PYTHON"], str(Path(sys.executable).absolute()))
            self.assertEqual(values["FARYO_CODEX_BIN_PINNED"], "0")
            self.assertEqual(values["FARYO_CODEX_AUTO_UPDATE"], "1")
            self.assertEqual(values["FARYO_START_DIRECTORY_ROOTS"], "/workspace/a:/workspace/b")
            self.assertFalse(any(key.startswith("FARYO_PROJECT_WORKBENCH_") for key in values))
            self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
