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

    def test_percent_encoded_unicode_owner_label_is_restored_safely(self):
        encoded = "Ubuntu%20%E5%B7%A5%E4%BD%9C%E7%AB%99"

        self.assertEqual(server.clean_owner_label(encoded), "Ubuntu 工作站")
        self.assertEqual(server.clean_owner_label("Safe%0D%0AInjected"), "SafeInjected")

    def test_only_codex_is_a_supported_agent_launcher(self):
        self.assertEqual(server.clean_agent_launch_command("codex"), "codex")
        self.assertIsNone(server.clean_agent_launch_command("claude"))

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
            mock.patch.object(server, "tmux_sessions", return_value=["desktop"]),
            mock.patch.object(server, "agent_profile_in_pane", return_value=server.CODEX_PROFILE),
            mock.patch.object(server, "get_pane_cwd", return_value="/private/project"),
            mock.patch.object(server, "path_under_root", return_value=False),
        ):
            items = server.agent_session_items(self.config, "/allowed/workspace")

        self.assertEqual(items, [])

    def test_codex_history_page_fetches_only_the_requested_window(self):
        active = [{"id": "live", "tmuxSession": "codex", "updatedTs": 100}]
        page = [{"id": f"history-{index}", "tmuxSession": "", "updatedTs": 50 - index} for index in range(10)]
        with (
            mock.patch.object(server, "active_codex_thread_state", return_value=({}, set())),
            mock.patch.object(server, "active_agent_session_items", return_value=(active, {"live"})),
            mock.patch.object(server, "codex_history_page", return_value=(page, 437)) as history_page,
        ):
            result = server.agent_session_page(self.config, 10, 390, "/workspace")

        history_page.assert_called_once_with(self.config, 10, 390, "/workspace", {"live"})
        self.assertEqual(result["activeSessions"], active)
        self.assertEqual(result["sessions"], page)
        self.assertEqual(result["historyTotal"], 437)
        self.assertEqual(result["historyOffset"], 390)

    def test_session_and_conversation_history_pagers_keep_distinct_contracts(self):
        with (
            mock.patch.object(server, "codex_history_filter", return_value=("1 = 1", ())),
            mock.patch.object(server, "codex_count", return_value=0),
            mock.patch.object(server, "codex_rows", return_value=[]),
        ):
            sessions, total = server.codex_history_page(self.config, 10, 20, "/workspace", {"live"})

        self.assertEqual((sessions, total), ([], 0))
        self.assertIsNot(server.codex_history_page, server.codex_conversation_history_page)

    def test_codex_history_filter_scopes_and_excludes_active_threads(self):
        where, params = server.codex_history_filter("/workspace/project", {"live-b", "live-a"})

        self.assertIn("id NOT IN (?,?)", where)
        self.assertIn("cwd LIKE ? ESCAPE", where)
        self.assertEqual(params[:2], ("live-a", "live-b"))
        self.assertEqual(params[2], "/workspace/project")
        self.assertEqual(params[3], "/workspace/project/%")


if __name__ == "__main__":
    unittest.main()
