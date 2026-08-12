import sys
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import server


class AgentSessionTest(unittest.TestCase):
    def setUp(self):
        self.config = server.Config("owner", "test-token", 145)

    def test_split_keeps_every_active_session_outside_history_pagination(self):
        active = [
            {"id": "active-old", "tmuxSession": "desktop", "updatedTs": 1},
            {"id": "active-new", "tmuxSession": "managed", "updatedTs": 100},
        ]
        history = [
            {"id": f"history-{index}", "tmuxSession": "", "updatedTs": 90 - index}
            for index in range(23)
        ]

        result = server.split_agent_session_items([active[1], *history, active[0]], 10, 10)

        self.assertEqual([item["id"] for item in result["activeSessions"]], ["active-new", "active-old"])
        self.assertEqual([item["id"] for item in result["sessions"]], [f"history-{index}" for index in range(10, 20)])
        self.assertEqual(result["historyTotal"], 23)
        self.assertEqual(result["historyOffset"], 10)
        self.assertEqual(result["historyLimit"], 10)

    def test_unmanaged_codex_tmux_is_discovered_as_active(self):
        with (
            mock.patch.object(server, "tmux_sessions", return_value=["desktop"]),
            mock.patch.object(server, "agent_profile_in_pane", return_value=server.CODEX_PROFILE),
            mock.patch.object(server, "get_pane_cwd", return_value="/workspace"),
            mock.patch.object(server, "active_agent_threads", return_value=[{"id": "live-thread"}, {"id": "superseded-thread"}]),
        ):
            active, superseded = server.active_codex_thread_state(self.config)

        self.assertEqual(active, {"live-thread": "desktop"})
        self.assertEqual(superseded, {"superseded-thread"})

    def test_active_limit_counts_managed_and_desktop_agents(self):
        with (
            mock.patch.object(server, "cleanup_managed_sessions") as cleanup,
            mock.patch.object(server, "tmux_sessions", return_value=["desktop", "managed", "shell"]),
            mock.patch.object(server, "agent_in_pane", side_effect=lambda config: config.session != "shell"),
        ):
            count = server.active_agent_count(self.config)

        self.assertEqual(count, 2)
        cleanup.assert_called_once_with(self.config)

    def test_workspace_history_scope_hides_unmapped_desktop_agent(self):
        with (
            mock.patch.object(server, "codex_history_items", return_value=[]),
            mock.patch.object(server, "active_claude_session_map", return_value={}),
            mock.patch.object(server, "claude_history_items", return_value=[]),
            mock.patch.object(server, "tmux_sessions", return_value=["desktop"]),
            mock.patch.object(server, "agent_profile_in_pane", return_value=server.CODEX_PROFILE),
            mock.patch.object(server, "get_pane_cwd", return_value="/private/project"),
            mock.patch.object(server, "path_under_root", return_value=False),
        ):
            items = server.agent_session_items(self.config, "/allowed/workspace")

        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
