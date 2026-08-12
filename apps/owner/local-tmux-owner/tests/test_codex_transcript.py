import sys
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import server


class CodexTranscriptTest(unittest.TestCase):
    def test_configured_codex_executable_wins_over_service_path(self):
        with mock.patch.dict(server.os.environ, {"FARYO_CODEX_BIN": "/opt/codex/bin/codex"}, clear=False):
            with mock.patch.object(server.shutil, "which", return_value="/usr/bin/codex"):
                self.assertEqual(server.agent_launch_executable("codex"), "/opt/codex/bin/codex")

    def test_codex_executable_falls_back_to_service_path(self):
        with mock.patch.dict(server.os.environ, {}, clear=False):
            server.os.environ.pop("FARYO_CODEX_BIN", None)
            with mock.patch.object(server.shutil, "which", return_value="/usr/bin/codex"):
                self.assertEqual(server.agent_launch_executable("codex"), "/usr/bin/codex")

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
