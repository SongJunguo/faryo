from __future__ import annotations

from pathlib import Path
import json
import sys
import unittest


OWNER_ROOT = Path(__file__).resolve().parents[1]
if str(OWNER_ROOT) not in sys.path:
    sys.path.insert(0, str(OWNER_ROOT))

import codex_history


class CodexHistoryPolicyTest(unittest.TestCase):
    def test_rollout_message_keeps_markdown_tex_and_attachment_paths(self) -> None:
        event = {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "Show $x^2$"},
            {"type": "input_image", "path": "./fixture.png"},
        ]}}
        self.assertEqual(codex_history.rollout_message(event), ("user", "Show $x^2$\nAttachment: ./fixture.png"))
        self.assertIsNone(codex_history.rollout_message({"type": "function_call"}))

    def test_thread_transcript_keeps_latest_complete_turns(self) -> None:
        thread = {"turns": [
            {"items": [{"type": "userMessage", "content": [{"text": "old"}]}, {"type": "agentMessage", "text": "old answer"}]},
            {"items": [{"type": "userMessage", "content": [{"text": "new"}]}, {"type": "agentMessage", "text": "\\[x^2\\]"}]},
        ]}
        transcript = codex_history.thread_transcript(thread, 4, page_turns=12, char_budget=1024, min_turns=1)
        self.assertNotIn("old answer", transcript)
        self.assertIn("› new", transcript)
        self.assertIn("\\[x^2\\]", transcript)

    def test_cursor_round_trip_and_expiry_are_explicit(self) -> None:
        revision = codex_history.history_revision((1, 2, 3, 4))
        cursor = codex_history.history_cursor(revision, 28)
        self.assertEqual(codex_history.decode_history_cursor(cursor, revision), 28)
        with self.assertRaises(codex_history.HistoryCursorError) as invalid:
            codex_history.decode_history_cursor("invalid", revision)
        self.assertFalse(invalid.exception.expired)
        with self.assertRaises(codex_history.HistoryCursorError) as expired:
            codex_history.decode_history_cursor(cursor, "0" * 16)
        self.assertTrue(expired.exception.expired)

    def test_preview_is_compact_bounded_and_nonempty(self) -> None:
        self.assertEqual(codex_history.history_preview("", 20), "Untitled question")
        self.assertEqual(codex_history.history_preview("  alpha   beta  ", 20), "alpha beta")
        self.assertEqual(codex_history.history_preview("x" * 20, 8), "xxxxxxx…")

    def test_bounded_rollout_messages_never_splits_the_latest_turn(self) -> None:
        messages = [("user", "old"), ("assistant", "old answer"), ("user", "new"), ("assistant", "line one\nline two")]
        selected = codex_history.bounded_rollout_messages(messages, page_turns=12, line_budget=2, char_budget=1024, min_turns=1)
        self.assertEqual(selected, [("user", "new"), ("assistant", "line one\nline two")])

    def test_goal_snapshot_is_status_only_and_never_returns_objective(self) -> None:
        snapshot = codex_history.goal_snapshot({
            "threadId": "private-thread",
            "objective": "private objective",
            "status": "active",
            "tokensUsed": 123,
            "timeUsedSeconds": 45,
            "updatedAt": 999,
        })

        self.assertEqual(snapshot, {
            "status": "active",
            "tokensUsed": 123,
            "timeUsedSeconds": 45,
            "updatedAt": 999,
        })
        self.assertNotIn("objective", snapshot)
        self.assertNotIn("threadId", snapshot)

    def test_direct_and_tool_goal_events_have_explicit_clear_semantics(self) -> None:
        direct = {
            "type": "response_item",
            "payload": {"type": "thread_goal_updated", "goal": {"status": "blocked", "objective": "private"}},
        }
        cleared = {"type": "response_item", "payload": {"type": "thread_goal_updated", "goal": None}}
        call = {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "call-goal",
                "input": "const result = await tools.get_goal({}); text(result);",
            },
        }
        output = {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-goal",
                "output": [
                    {"type": "input_text", "text": "ignored"},
                    {"type": "input_text", "text": json.dumps({
                        "goal": {"status": "complete", "objective": "private", "tokensUsed": 456},
                    })},
                ],
            },
        }

        self.assertEqual(codex_history.direct_goal_snapshot(direct), {"status": "blocked"})
        self.assertEqual(codex_history.direct_goal_snapshot(cleared), {"status": "none"})
        self.assertEqual(codex_history.goal_tool_call_id(call), "call-goal")
        self.assertEqual(codex_history.goal_tool_output(output), (
            "call-goal",
            {"status": "complete", "tokensUsed": 456},
        ))
        call["payload"]["input"] = "text('tools.get_goal is documentation, not a call')"
        self.assertIsNone(codex_history.goal_tool_call_id(call))


if __name__ == "__main__":
    unittest.main()
