import sys
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import server


class CodexTranscriptTest(unittest.TestCase):
    def setUp(self):
        with server._codex_rollout_cache_lock:
            server._codex_rollout_cache.clear()

    def tearDown(self):
        with server._rate_limit_lock:
            server._rate_limit_cache = None
            server._rate_limit_cache_at = 0.0
            server._rate_limit_refreshing = False
        with server._claude_rate_limit_lock:
            server._claude_rate_limit_cache = None
            server._claude_rate_limit_cache_at = 0.0
            server._claude_rate_limit_refreshing = False

    def test_context_usage_uses_agent_reported_total_and_window(self):
        event = {
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 45_659,
                        "output_tokens": 1_761,
                        "total_tokens": 47_420,
                    },
                    "model_context_window": 258_400,
                },
            },
        }
        with tempfile.TemporaryDirectory() as root:
            history = Path(root) / "rollout.jsonl"
            history.write_text(json.dumps(event) + "\n", encoding="utf-8")

            usage = server.latest_context_usage(str(history))

        self.assertEqual(usage["usedTokens"], 47_420)
        self.assertEqual(usage["contextWindow"], 258_400)
        self.assertEqual(usage["contextWindowSource"], "agent-reported")
        self.assertEqual(usage["percent"], 18.4)

    def test_configured_codex_executable_wins_over_service_path(self):
        with mock.patch.dict(server.os.environ, {"FARYO_CODEX_BIN": "/opt/codex/bin/codex"}, clear=False):
            with mock.patch.object(server.shutil, "which", return_value="/usr/bin/codex"):
                self.assertEqual(server.agent_launch_executable("codex"), "/opt/codex/bin/codex")

    def test_codex_executable_falls_back_to_service_path(self):
        with mock.patch.dict(server.os.environ, {}, clear=False):
            server.os.environ.pop("FARYO_CODEX_BIN", None)
            with mock.patch.object(server.shutil, "which", return_value="/usr/bin/codex"):
                self.assertEqual(server.agent_launch_executable("codex"), "/usr/bin/codex")

    def test_app_server_uses_the_node_next_to_a_configured_codex_script(self):
        with tempfile.TemporaryDirectory() as root:
            version = Path(root) / "versions" / "node" / "v1"
            node = version / "bin" / "node"
            script = version / "lib" / "node_modules" / "pkg" / "bin" / "codex.js"
            node.parent.mkdir(parents=True)
            script.parent.mkdir(parents=True)
            node.write_text("runtime", encoding="utf-8")
            script.write_text("cli", encoding="utf-8")
            node.chmod(0o755)
            with mock.patch.object(server, "agent_launch_executable", return_value=str(script)):
                command = server.codex_app_server_argv("app-server", "--listen", "stdio://")

        self.assertEqual(command, [str(node), str(script), "app-server", "--listen", "stdio://"])

    def test_preserves_original_latex_from_agent_messages(self):
        formula = (
            "A generic bound gives\n\n"
            "\\[\n"
            "\\|w(s)\\|\\le C.\n"
            "\\]\n\n"
            "\\[\n"
            "q(s)=\\begin{cases}\n"
            "a,&0\\le s<s_0,\\\\\n"
            "b,&s\\ge s_0.\n"
            "\\end{cases}\n"
            "\\]"
        )
        thread = {
            "turns": [{
                "items": [
                    {"type": "userMessage", "content": [{"type": "text", "text": "Render generic notation"}]},
                    {"type": "agentMessage", "phase": "final_answer", "text": formula},
                ]
            }]
        }

        transcript = server.codex_thread_transcript(thread, 320)

        self.assertIn("› Render generic notation", transcript)
        self.assertIn("\\|w(s)\\|\\le C.", transcript)
        self.assertIn("a,&0\\le s<s_0,\\\\", transcript)
        self.assertIn("\\begin{cases}", transcript)

    def test_line_budget_keeps_the_latest_turn_intact(self):
        thread = {
            "turns": [
                {"items": [
                    {"type": "userMessage", "content": [{"type": "text", "text": "old"}]},
                    {"type": "agentMessage", "text": "old answer"},
                ]},
                {"items": [
                    {"type": "userMessage", "content": [{"type": "text", "text": "new"}]},
                    {"type": "agentMessage", "text": "\\[\nx^2+y^2\n\\]"},
                ]},
            ]
        }

        transcript = server.codex_thread_transcript(thread, 4)

        self.assertNotIn("old answer", transcript)
        self.assertIn("› new", transcript)
        self.assertIn("\\[\nx^2+y^2\n\\]", transcript)

    def test_rollout_transcript_is_incremental_and_preserves_markdown_math(self):
        events = [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Show the model"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "## Result\n\n\\[q(t)=\\begin{cases}a,&t<1,\\\\b,&t\\ge1.\\end{cases}\\]"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "internal instructions"}],
                },
            },
        ]
        with tempfile.TemporaryDirectory() as root:
            history = Path(root) / "rollout.jsonl"
            history.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

            first = server.codex_rollout_transcript(str(history), 320)
            with history.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Next question"}],
                    },
                }) + "\n")
            second = server.codex_rollout_transcript(str(history), 320)

        self.assertIn("› Show the model", first)
        self.assertIn("## Result", first)
        self.assertIn("\\begin{cases}", first)
        self.assertNotIn("internal instructions", first)
        self.assertEqual(second.count("› Show the model"), 1)
        self.assertIn("› Next question", second)

    def test_rollout_parser_waits_for_a_complete_jsonl_record(self):
        event = {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "complete after append"}],
            },
        }
        encoded = json.dumps(event)
        split_at = len(encoded) // 2
        with tempfile.TemporaryDirectory() as root:
            history = Path(root) / "rollout.jsonl"
            history.write_text(encoded[:split_at], encoding="utf-8")
            self.assertEqual(server.codex_rollout_transcript(str(history), 320), "")
            with history.open("a", encoding="utf-8") as fh:
                fh.write(encoded[split_at:] + "\n")
            transcript = server.codex_rollout_transcript(str(history), 320)

        self.assertEqual(transcript, "• complete after append")

    def test_large_rollout_initializes_from_a_bounded_tail(self):
        old_event = {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "old prefix must not be cached"}],
            },
        }
        usage_event = {
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
                    "model_context_window": 1_000,
                },
            },
        }
        latest_event = {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "latest bounded tail"}],
            },
        }
        with tempfile.TemporaryDirectory() as root:
            history = Path(root) / "rollout.jsonl"
            prefix = (json.dumps(old_event) + "\n") * 40
            history.write_text(prefix + json.dumps(usage_event) + "\n" + json.dumps(latest_event) + "\n", encoding="utf-8")
            with mock.patch.object(server, "CODEX_ROLLOUT_TAIL_SCAN_BYTES", 640):
                state = server.codex_rollout_state(str(history))

        transcript = server.codex_message_transcript(state["messages"], 320)
        self.assertLess(transcript.count("old prefix"), 40)
        self.assertIn("latest bounded tail", transcript)
        self.assertEqual(state["contextUsage"]["usedTokens"], 150)

    def test_rollout_cache_evicts_the_least_recent_path(self):
        event = {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "bounded"}],
            },
        }
        with tempfile.TemporaryDirectory() as root, mock.patch.object(server, "CODEX_ROLLOUT_CACHE_MAX_PATHS", 2):
            paths = []
            for index in range(3):
                path = Path(root) / f"rollout-{index}.jsonl"
                path.write_text(json.dumps(event) + "\n", encoding="utf-8")
                paths.append(str(path))
                server.codex_rollout_messages(str(path))

            with server._codex_rollout_cache_lock:
                keys = list(server._codex_rollout_cache)

        self.assertEqual(keys, paths[1:])

    def test_large_unread_gap_rebuilds_from_the_latest_tail(self):
        def message(text):
            return {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                },
            }

        with tempfile.TemporaryDirectory() as root:
            history = Path(root) / "rollout.jsonl"
            history.write_text(json.dumps(message("before gap")) + "\n", encoding="utf-8")
            self.assertIn("before gap", server.codex_rollout_transcript(str(history), 320))
            with history.open("a", encoding="utf-8") as fh:
                for _ in range(20):
                    fh.write(json.dumps({"type": "ignored", "padding": "x" * 48}) + "\n")
                fh.write(json.dumps(message("after gap")) + "\n")
            with mock.patch.object(server, "CODEX_ROLLOUT_MAX_CATCHUP_BYTES", 128), \
                 mock.patch.object(server, "CODEX_ROLLOUT_TAIL_SCAN_BYTES", 256):
                transcript = server.codex_rollout_transcript(str(history), 320)

        self.assertNotIn("before gap", transcript)
        self.assertIn("after gap", transcript)

    def test_structured_capture_prefers_the_durable_rollout(self):
        event = {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "structured answer"}],
            },
        }
        with tempfile.TemporaryDirectory() as root:
            history = Path(root) / "rollout.jsonl"
            history.write_text(json.dumps(event) + "\n", encoding="utf-8")
            thread = {"id": "thread-id", "rollout_path": str(history)}
            with mock.patch.object(server, "get_pane_cwd", return_value=str(root)), \
                 mock.patch.object(server, "active_agent_thread", return_value=thread), \
                 mock.patch.object(server, "cached_codex_thread") as app_server_read:
                capture = server.codex_structured_capture(mock.sentinel.config, 320)

        self.assertEqual(capture, ("• structured answer", "thread-id", "codex-jsonl"))
        app_server_read.assert_not_called()

    def test_stale_app_server_thread_survives_a_transient_read_failure(self):
        thread = {"turns": [{"items": [{"type": "agentMessage", "text": "cached"}]}]}
        with server._codex_thread_cache_lock:
            server._codex_thread_cache["thread-id"] = (
                time.monotonic() - server.CODEX_TRANSCRIPT_CACHE_TTL - 1,
                thread,
            )
        with mock.patch.object(server, "codex_app_server_request", return_value=None):
            result = server.cached_codex_thread("thread-id")

        self.assertIs(result, thread)

    def test_codex_rate_limit_cache_starts_only_one_background_refresh(self):
        started = []

        class FakeThread:
            def __init__(self, *, target, name, daemon):
                self.target = target
                self.name = name
                self.daemon = daemon

            def start(self):
                started.append(self)

        with mock.patch.object(server.threading, "Thread", FakeThread):
            self.assertIsNone(server.cached_weekly_rate_limit())
            self.assertIsNone(server.cached_weekly_rate_limit())

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0].name, "faryo-codex-rate-limit")

    def test_codex_rate_limit_fetch_reuses_the_shared_app_server(self):
        response = {
            "rateLimits": {
                "secondary": {
                    "usedPercent": 42,
                    "windowDurationMins": 10_080,
                    "resetsAt": 1_800_000_000,
                },
                "limitId": "codex",
                "planType": "example",
            },
        }
        with mock.patch.object(server, "codex_app_server_request", return_value=response) as request:
            result = server.fetch_weekly_rate_limit(timeout=7.0)

        request.assert_called_once_with("account/rateLimits/read", {}, timeout=7.0)
        self.assertEqual(result["usedPercent"], 42.0)
        self.assertEqual(result["windowDurationMins"], 10_080)

    def test_claude_rate_limit_cache_starts_only_one_background_refresh(self):
        started = []

        class FakeThread:
            def __init__(self, *, target, name, daemon):
                self.target = target
                self.name = name
                self.daemon = daemon

            def start(self):
                started.append(self)

        with mock.patch.object(server.threading, "Thread", FakeThread):
            self.assertIsNone(server.cached_claude_rate_limits())
            self.assertIsNone(server.cached_claude_rate_limits())

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0].name, "faryo-claude-rate-limit")

    def test_claude_rate_limit_thread_start_failure_allows_retry(self):
        class BrokenThread:
            def __init__(self, *, target, name, daemon):
                pass

            def start(self):
                raise RuntimeError("thread unavailable")

        with mock.patch.object(server.threading, "Thread", BrokenThread):
            self.assertIsNone(server.cached_claude_rate_limits())

        with server._claude_rate_limit_lock:
            self.assertFalse(server._claude_rate_limit_refreshing)

    def test_rate_limit_refresh_failure_does_not_wedge_future_attempts(self):
        with server._rate_limit_lock:
            server._rate_limit_refreshing = True
        with mock.patch.object(server, "fetch_weekly_rate_limit", side_effect=RuntimeError("transient")):
            server.refresh_weekly_rate_limit_cache()
        with server._rate_limit_lock:
            self.assertFalse(server._rate_limit_refreshing)
            self.assertIsNone(server._rate_limit_cache)

    def test_claude_rate_limit_refresh_failure_does_not_wedge_future_attempts(self):
        with server._claude_rate_limit_lock:
            server._claude_rate_limit_refreshing = True
        with mock.patch.object(server, "fetch_claude_rate_limits", side_effect=RuntimeError("transient")):
            server.refresh_claude_rate_limit_cache()
        with server._claude_rate_limit_lock:
            self.assertFalse(server._claude_rate_limit_refreshing)
            self.assertIsNone(server._claude_rate_limit_cache)

    def test_live_tail_starts_at_the_latest_turn_and_redacts_account(self):
        capture = (
            "› old question\n\n"
            "• old answer\n\n"
            "› current question\n"
            "│ Account: person@example.com (Plus)\n"
            "• Ran command\n"
            "• Working (2s • esc to interrupt)"
        )

        tail = server.codex_live_tail(capture)

        self.assertNotIn("old question", tail)
        self.assertIn("› current question", tail)
        self.assertIn("Account: <redacted>", tail)
        self.assertNotIn("person@example.com", tail)

    def test_live_shell_tail_drops_prior_status_panels(self):
        capture = (
            "› previous question\n"
            "│ Account: person@example.com (Plus)\n"
            "• Running sleep 4\n"
            "• Working (1s • esc to interrupt)"
        )

        tail = server.codex_live_tail(capture)

        self.assertEqual("• Running sleep 4\n• Working (1s • esc to interrupt)", tail)


if __name__ == "__main__":
    unittest.main()
