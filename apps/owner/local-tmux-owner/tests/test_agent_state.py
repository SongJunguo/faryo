import importlib.util
import sys
import unittest
from pathlib import Path


SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
sys.path.insert(0, str(SERVER_PATH.parent))
SPEC = importlib.util.spec_from_file_location("faryo_owner_server", SERVER_PATH)
assert SPEC and SPEC.loader
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class AgentStateTest(unittest.TestCase):
    def test_ready_prompt(self) -> None:
        self.assertEqual(server.agent_state_from_text("work complete\n› "), "ready")

    def test_running_indicator(self) -> None:
        self.assertEqual(server.agent_state_from_text("Working\nEsc to interrupt"), "running")

    def test_upgrade_prompt_is_blocked(self) -> None:
        capture = "Update available: Codex 0.140.0\nWould you like to update now?\n1. Update\n2. Skip"
        self.assertEqual(server.agent_state_from_text(capture), "blocked")

    def test_approval_prompt_is_blocked(self) -> None:
        self.assertEqual(server.agent_state_from_text("Approval requested\nAllow Codex to run this command?"), "blocked")


if __name__ == "__main__":
    unittest.main()
