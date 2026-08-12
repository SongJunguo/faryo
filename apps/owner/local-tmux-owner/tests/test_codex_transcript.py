import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import server


class CodexTranscriptTest(unittest.TestCase):
    def test_preserves_original_latex_from_agent_messages(self):
        formula = (
            "Boundedness gives\n\n"
            "\\[\n"
            "\\|d(t)\\|\\le M.\n"
            "\\]\n\n"
            "\\[\n"
            "d(t)=\\begin{cases}\n"
            "-1,&t<1,\\\\\n"
            "1,&t\\ge1.\n"
            "\\end{cases}\n"
            "\\]"
        )
        thread = {
            "turns": [{
                "items": [
                    {"type": "userMessage", "content": [{"type": "text", "text": "Explain bounded noise"}]},
                    {"type": "agentMessage", "phase": "final_answer", "text": formula},
                ]
            }]
        }

        transcript = server.codex_thread_transcript(thread, 320)

        self.assertIn("› Explain bounded noise", transcript)
        self.assertIn("\\|d(t)\\|\\le M.", transcript)
        self.assertIn("-1,&t<1,\\\\", transcript)
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
