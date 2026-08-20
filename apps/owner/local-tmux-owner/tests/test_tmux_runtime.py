from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


OWNER_ROOT = Path(__file__).resolve().parents[1]
if str(OWNER_ROOT) not in sys.path:
    sys.path.insert(0, str(OWNER_ROOT))

import tmux_runtime


class TmuxRuntimeTest(unittest.TestCase):
    def test_command_runner_preserves_utf8_input_output_and_nonzero_status(self) -> None:
        result = tmux_runtime.run_command(
            [sys.executable, "-c", "import sys; value=sys.stdin.read(); print(value); raise SystemExit(7)"],
            input_text="中文 TeX",
        )
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.strip(), "中文 TeX")

    def test_command_timeout_is_not_silently_swallowed(self) -> None:
        with self.assertRaises(subprocess.TimeoutExpired):
            tmux_runtime.run_command([sys.executable, "-c", "import time; time.sleep(1)"], timeout=0.01)

    def test_process_table_parser_and_descendants_are_deterministic(self) -> None:
        table = tmux_runtime.parse_process_table("10 1 shell\n11 10 codex app-server\n12 10 node\n13 11 helper\ninvalid\n")
        self.assertEqual(table[11], (10, "codex app-server"))
        self.assertEqual(set(tmux_runtime.descendants(10, table)), {(11, "codex app-server"), (12, "node"), (13, "helper")})

    def test_identifier_policies_keep_exact_bounds(self) -> None:
        self.assertEqual(tmux_runtime.clean_tmux_session_name(" faryo1 "), "faryo1")
        self.assertIsNone(tmux_runtime.clean_tmux_session_name("bad session"))
        self.assertEqual(tmux_runtime.clean_agent_session_id("a" * 120), "a" * 120)
        self.assertIsNone(tmux_runtime.clean_agent_session_id("a" * 121))
        self.assertEqual(tmux_runtime.clean_client_message_id("message-1"), "message-1")
        self.assertIsNone(tmux_runtime.clean_client_message_id("short"))
        self.assertEqual(tmux_runtime.clean_client_launch_id("launch-1"), "launch-1")


if __name__ == "__main__":
    unittest.main()
