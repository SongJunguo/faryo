import sys
import sqlite3
import tempfile
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
        with server._codex_session_index_lock:
            server._codex_session_index_cache = {}
            server._codex_session_index_signature = None

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
            mock.patch.object(server, "agent_profile_in_pane", side_effect=lambda config: server.CODEX_PROFILE if config.session != "shell" else None),
            mock.patch.object(server, "managed_session", return_value=False),
        ):
            count = server.active_agent_count(self.config)

        self.assertEqual(count, 2)
        cleanup.assert_called_once_with(self.config)

    def test_active_limit_reserves_a_slot_while_managed_codex_is_starting(self):
        with (
            mock.patch.object(server, "cleanup_managed_sessions"),
            mock.patch.object(server, "tmux_sessions", return_value=["faryo1"]),
            mock.patch.object(server, "agent_profile_in_pane", return_value=None),
            mock.patch.object(server, "managed_session", return_value=True),
            mock.patch.object(server, "agent_session_lifecycle", return_value=("starting", False)),
        ):
            self.assertEqual(server.active_agent_count(self.config), 1)

    def test_new_managed_session_uses_the_first_available_faryo_number(self):
        with mock.patch.object(server, "tmux_sessions", return_value=["codex", "faryo1", "faryo3", "faryo-legacy"]):
            self.assertEqual(server.next_faryo_session_name(self.config), "faryo2")

    def test_codex_session_index_cache_reloads_after_rename_append(self):
        with tempfile.TemporaryDirectory() as root:
            index = Path(root) / "session_index.jsonl"
            index.write_text('{"id":"thread-a","thread_name":"Initial topic"}\n', encoding="utf-8")
            with mock.patch.object(server, "CODEX_SESSION_INDEX", index):
                self.assertEqual(server.codex_session_index_titles(), {"thread-a": "Initial topic"})
                with index.open("a", encoding="utf-8") as stream:
                    stream.write('{"id":"thread-a","thread_name":"Renamed topic"}\n')
                self.assertEqual(server.codex_session_index_titles(), {"thread-a": "Renamed topic"})

    def test_explicit_codex_rename_beats_managed_tmux_startup_title(self):
        thread = {"id": "thread-a", "title": "First prompt", "cwd": "/workspace", "updated_at": 1}
        with (
            mock.patch.object(server, "tmux_session_option", return_value="Startup title"),
            mock.patch.object(server, "session_git_label", return_value=""),
            mock.patch.object(server, "managed_session", return_value=True),
            mock.patch.object(server, "agent_session_running", return_value=False),
        ):
            item = server.codex_session_item(
                self.config,
                thread,
                {"thread-a": "Renamed topic"},
                {},
                "faryo1",
            )

        self.assertEqual(item["title"], "Renamed topic")
        self.assertEqual(item["tmuxSession"], "faryo1")

    def test_capture_metadata_exposes_only_explicit_codex_thread_name(self):
        with mock.patch.object(server, "codex_session_index_titles", return_value={"thread-a": "Renamed topic"}):
            self.assertEqual(server.codex_capture_session_metadata("thread-a"), {
                "sessionId": "thread-a",
                "sessionTitle": "Renamed topic",
            })
            self.assertEqual(server.codex_capture_session_metadata("thread-b"), {"sessionId": "thread-b"})

    def test_capture_event_digest_changes_when_only_thread_name_changes(self):
        before = server.capture_event_digest("same transcript", "", {"sessionTitle": "Initial topic"})
        after = server.capture_event_digest("same transcript", "", {"sessionTitle": "Renamed topic"})

        self.assertNotEqual(before, after)

    def test_directory_browser_lists_only_allowed_visible_directories(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root) / "workspace"
            visible = workspace / "visible"
            hidden = workspace / ".hidden"
            outside = Path(root) / "outside"
            visible.mkdir(parents=True)
            hidden.mkdir()
            outside.mkdir()
            (workspace / "file.txt").write_text("not a directory", encoding="utf-8")
            (workspace / "escape").symlink_to(outside, target_is_directory=True)
            with mock.patch.dict(server.os.environ, {
                "FARYO_START_DIRECTORY_ROOTS": str(workspace),
                "FARYO_PROJECT_WORKBENCH_ALLOWED_ROOTS": "",
            }, clear=False):
                payload = server.directory_browser_payload(self.config, str(workspace))
                child = server.directory_browser_payload(self.config, str(visible))
                with self.assertRaises(server.OwnerError) as denied:
                    server.resolve_start_directory(str(outside))

        self.assertEqual([item["name"] for item in payload["directories"]], ["visible"])
        self.assertEqual(payload["selectionToken"], server.directory_selection_token(self.config, workspace.resolve()))
        self.assertEqual(child["parent"], str(workspace.resolve()))
        self.assertEqual(denied.exception.status, server.HTTPStatus.FORBIDDEN)

    def test_agent_start_waits_for_a_real_codex_process(self):
        completed = server.subprocess.CompletedProcess(["tmux"], 0, "", "")
        with (
            mock.patch.object(server, "active_agent_count", return_value=0),
            mock.patch.object(server, "agent_login_shell", return_value="/bin/bash"),
            mock.patch.object(server, "codex_cli_argv", return_value=["/runtime/node", "/runtime/codex.js"]),
            mock.patch.object(server, "tmux", return_value=completed) as tmux,
            mock.patch.object(server, "tmux_session_option") as session_option,
            mock.patch.object(server, "managed_launch_session", return_value=""),
            mock.patch.object(server, "has_session", return_value=True),
            mock.patch.object(server, "codex_cli_in_pane", side_effect=[False, True]),
            mock.patch.object(server, "ensure_pane_width") as ensure_width,
            mock.patch.object(server.time, "sleep"),
        ):
            name = server.start_agent_runtime(self.config, Path("/workspace"), "codex", [], max_running=8, launch_id="web-launch-123")

        launch = next(call.args[1] for call in tmux.call_args_list if call.args[1][0] == "new-session")
        self.assertTrue(name.startswith("faryo") and name[5:].isdigit())
        self.assertIn("/bin/bash", launch)
        self.assertIn("/runtime/codex.js", launch[-1])
        session_option.assert_any_call(self.config, name, "@faryo_managed", "1")
        session_option.assert_any_call(self.config, name, "@faryo_launch_id", "web-launch-123")
        self.assertTrue(any(call.args[2] == "@faryo_starting_at" and call.args[3] for call in session_option.call_args_list))
        session_option.assert_any_call(self.config, name, "@faryo_starting_at", "")
        ensure_width.assert_called_once()

    def test_duplicate_launch_id_reuses_the_same_managed_session(self):
        with (
            mock.patch.object(server, "managed_launch_session", return_value="faryo7"),
            mock.patch.object(server, "active_agent_count") as active_count,
            mock.patch.object(server, "has_session", return_value=True),
            mock.patch.object(server, "codex_cli_in_pane", return_value=True),
            mock.patch.object(server, "ensure_pane_width") as ensure_width,
            mock.patch.object(server, "tmux") as tmux,
        ):
            name = server.start_agent_runtime(
                self.config,
                Path("/workspace"),
                "codex",
                [],
                max_running=1,
                launch_id="web-launch-123",
            )

        self.assertEqual(name, "faryo7")
        active_count.assert_not_called()
        self.assertFalse(any(call.args[1] and call.args[1][0] == "new-session" for call in tmux.call_args_list))
        ensure_width.assert_called_once()

    def test_agent_session_lifecycle_uses_process_and_start_marker_evidence(self):
        with mock.patch.object(server, "agent_ready_for_input", return_value=False):
            self.assertEqual(
                server.agent_session_lifecycle(self.config, "faryo1", server.CODEX_PROFILE, True),
                ("running", True),
            )
            self.assertEqual(
                server.agent_session_lifecycle(self.config, "desktop", server.CODEX_PROFILE, False),
                ("desktop", True),
            )
        with mock.patch.object(server, "agent_ready_for_input", return_value=True):
            self.assertEqual(
                server.agent_session_lifecycle(self.config, "faryo1", server.CODEX_PROFILE, True),
                ("waiting", False),
            )
        with (
            mock.patch.object(server, "agent_profile_in_pane", return_value=None),
            mock.patch.object(server, "tmux_session_option", return_value="1000"),
        ):
            self.assertEqual(server.agent_session_lifecycle(self.config, "faryo1", None, True, now=1010), ("starting", False))
            self.assertEqual(server.agent_session_lifecycle(self.config, "faryo1", None, True, now=1100), ("exited", False))

    def test_managed_shell_after_codex_exit_remains_visible_until_cleanup(self):
        def option(_config, _session, key, _value=None):
            return {
                "@faryo_agent_session_id": "thread-exited",
                "@faryo_agent_source": "codex-cli",
                "@faryo_session_title": "Exited fixture",
                "@faryo_starting_at": "",
                "@faryo_git_root": "",
            }.get(key, "")

        with (
            mock.patch.object(server, "tmux_sessions", return_value=["faryo1"]),
            mock.patch.object(server, "agent_profile_in_pane", return_value=None),
            mock.patch.object(server, "managed_session", return_value=True),
            mock.patch.object(server, "get_pane_cwd", return_value="/workspace/project"),
            mock.patch.object(server, "tmux_session_option", side_effect=option),
            mock.patch.object(server, "session_created_ts", return_value=100),
            mock.patch.object(server, "session_git_label", return_value=""),
        ):
            items, excluded = server.active_agent_session_items(self.config, codex_state=({}, set()))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["state"], "exited")
        self.assertFalse(items[0]["agentRunning"])
        self.assertEqual(items[0]["tmuxSession"], "faryo1")
        self.assertIn("thread-exited", excluded)

    def test_agent_start_timeout_removes_the_empty_tmux(self):
        completed = server.subprocess.CompletedProcess(["tmux"], 0, "", "")
        with (
            mock.patch.object(server, "AGENT_START_READY_TIMEOUT", 0),
            mock.patch.object(server, "active_agent_count", return_value=0),
            mock.patch.object(server, "agent_login_shell", return_value="/bin/bash"),
            mock.patch.object(server, "codex_cli_argv", return_value=["/runtime/codex"]),
            mock.patch.object(server, "tmux", return_value=completed) as tmux,
            mock.patch.object(server, "tmux_session_option"),
        ):
            with self.assertRaises(server.OwnerError) as raised:
                server.start_agent_runtime(self.config, Path("/workspace"), "codex", [])

        self.assertEqual(raised.exception.status, server.HTTPStatus.BAD_GATEWAY)
        self.assertTrue(any(call.args[1][:2] == ["kill-session", "-t"] for call in tmux.call_args_list))

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

    def test_detected_desktop_codex_source_does_not_grant_remote_close_ownership(self):
        def option(_config, _session, key, _value=None):
            return "codex-cli" if key == "@faryo_agent_source" else ""

        with (
            mock.patch.object(server, "tmux_sessions", return_value=["codex"]),
            mock.patch.object(server, "tmux_session_option", side_effect=option),
        ):
            self.assertFalse(server.managed_session(self.config, "codex"))

        with (
            mock.patch.object(server, "tmux_sessions", return_value=["faryo1"]),
            mock.patch.object(server, "tmux_session_option", return_value="1"),
        ):
            self.assertTrue(server.managed_session(self.config, "faryo1"))

    def test_codex_history_page_fetches_only_the_requested_window(self):
        active = [{"id": "live", "tmuxSession": "codex", "updatedTs": 100}]
        page = [{"id": f"history-{index}", "tmuxSession": "", "updatedTs": 50 - index} for index in range(10)]
        with (
            mock.patch.object(server, "active_codex_thread_state", return_value=({}, set())),
            mock.patch.object(server, "active_agent_session_items", return_value=(active, {"live"})),
            mock.patch.object(server, "codex_history_page", return_value=(page, 437)) as history_page,
        ):
            result = server.agent_session_page(self.config, 10, 390, "/workspace")

        history_page.assert_called_once_with(self.config, 10, 390, "/workspace", {"live"}, "", "all", "active")
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

    def test_history_search_matches_explicit_rename_and_literal_folder_symbols(self):
        rows = [
            {"id": "renamed", "title": "Old title", "cwd": "/workspace/alpha", "updated_at": 200},
            {"id": "symbols", "title": "Another title", "cwd": "/workspace/100%_literal", "updated_at": 190},
        ]
        with (
            mock.patch.object(server, "codex_history_filter", return_value=("1 = 1", ())),
            mock.patch.object(server, "codex_rows", return_value=rows),
            mock.patch.object(server, "codex_session_index_titles", return_value={"renamed": "Section IV revised"}),
            mock.patch.object(server, "codex_session_item", side_effect=lambda _config, item, *_args: item),
        ):
            renamed, renamed_total = server.codex_history_page(self.config, 10, query="section iv")
            symbols, symbols_total = server.codex_history_page(self.config, 10, query="%_")

        self.assertEqual(([item["id"] for item in renamed], renamed_total), (["renamed"], 1))
        self.assertEqual(([item["id"] for item in symbols], symbols_total), (["symbols"], 1))

    def test_history_period_and_archive_filters_are_metadata_only(self):
        now = 2_000_000_000.0
        rows = [
            {"id": "recent", "title": "Recent", "cwd": "/workspace/recent", "updated_at": now - 60},
            {"id": "old", "title": "Old", "cwd": "/workspace/old", "updated_at": now - 40 * 86400},
        ]
        with (
            mock.patch.object(server, "codex_rows", return_value=rows),
            mock.patch.object(server, "codex_session_index_titles", return_value={}),
            mock.patch.object(server, "codex_session_item", side_effect=lambda _config, item, *_args: item),
            mock.patch.object(server, "codex_conversation_history_page") as transcript_reader,
        ):
            sessions, total = server.codex_history_page(
                self.config,
                10,
                period="30d",
                archive="archived",
                now=now,
            )

        self.assertEqual(([item["id"] for item in sessions], total), (["recent"], 1))
        transcript_reader.assert_not_called()
        where, _params = server.codex_history_filter(None, set(), "archived")
        self.assertIn("COALESCE(archived, 0) != 0", where)

    def test_history_query_is_bounded_and_access_log_omits_query_string(self):
        self.assertEqual(len(server.clean_agent_history_query("x" * 200)), 96)
        handler = object.__new__(server.Handler)
        handler.path = "/api/agent-sessions?q=private-title&token=secret"
        handler.command = "GET"
        with mock.patch.object(server.sys, "stderr") as stderr:
            handler.log_message('"GET /api/agent-sessions?q=private-title HTTP/1.1" 200 -')

        logged = stderr.write.call_args.args[0]
        self.assertIn("GET /api/agent-sessions", logged)
        self.assertNotIn("private-title", logged)
        self.assertNotIn("secret", logged)

    def test_large_metadata_history_filters_before_pagination(self):
        now = 2_000_000_000.0
        with tempfile.TemporaryDirectory() as root:
            state_db = Path(root) / "state.sqlite"
            connection = sqlite3.connect(state_db)
            try:
                connection.execute(
                    "CREATE TABLE threads (id TEXT, title TEXT, rollout_path TEXT, tokens_used INTEGER, "
                    "model TEXT, reasoning_effort TEXT, cwd TEXT, updated_at REAL, source TEXT, "
                    "thread_source TEXT, archived INTEGER, created_at REAL)"
                )
                connection.executemany(
                    "INSERT INTO threads VALUES (?, ?, '', 0, '', '', ?, ?, 'cli', 'user', ?, ?)",
                    [
                        (
                            f"thread-{index:03d}",
                            f"Anonymous topic {index:03d}",
                            f"/workspace/{'target-folder' if index % 3 == 0 else 'other-folder'}-{index:03d}",
                            now - index * 3600,
                            int(index % 5 == 0),
                            now - index * 3600,
                        )
                        for index in range(455)
                    ],
                )
                connection.commit()
            finally:
                connection.close()
            with (
                mock.patch.object(server, "AGENT_STATE_DB", state_db),
                mock.patch.object(server, "codex_session_index_titles", return_value={}),
                mock.patch.object(server, "codex_session_item", side_effect=lambda _config, item, *_args: item),
            ):
                page, total = server.codex_history_page(
                    self.config,
                    10,
                    offset=10,
                    query="target-folder",
                    period="7d",
                    archive="all",
                    now=now,
                )

        expected = [index for index in range(455) if index % 3 == 0 and index <= 168]
        self.assertEqual(total, len(expected))
        self.assertEqual([item["id"] for item in page], [f"thread-{index:03d}" for index in expected[10:20]])


if __name__ == "__main__":
    unittest.main()
