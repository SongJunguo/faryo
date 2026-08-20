from __future__ import annotations

from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
