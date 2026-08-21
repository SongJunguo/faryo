import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import codex_tui_interactions as interactions


MODEL_MENU = """
  Select Model and Effort
  Access legacy models through the CLI configuration

› 1. gpt-example-a (current)  Frontier model.
  2. gpt-example-b            Balanced model for everyday work.
  3. gpt-example-c            Fast model.

  Press enter to confirm or esc to go back
"""

REASONING_MENU = """
  Select Reasoning Level for gpt-example-a

  1. Low (default)              Fast responses with lighter reasoning
  2. Medium                     Balanced reasoning
  3. High                       Greater reasoning depth
› 4. More reasoning… (current)  Uses limits faster

  Press enter to confirm or esc to go back
"""

RESUME_MENU = """
  Choose working directory to resume this session

  Session = latest cwd recorded in the resumed session
  Current = your current working directory

› 1. Use session directory (/workspace/original)
  2. Use current directory (/workspace/current)
  3. Always use session directory
  4. Always use current directory

  Press enter to continue
"""

USAGE_MENU = """
  Usage
  View account usage or redeem an earned reset.

› 1. Show usage                View recent account token usage.
     Redeem usage limit reset  No usage limit resets available.

  Press enter to confirm or esc to go back
"""

ADVANCED_REASONING_MENU = """
  Advanced Reasoning
  Consumes usage limits faster

› 1. Max (current)  For difficult problems when quality matters more than speed
  2. Ultra          For demanding work using multiple agents

  Press enter to confirm or esc to go back
"""


class CodexTuiInteractionTest(unittest.TestCase):
    def test_detects_model_menu_and_preserves_current_separately(self):
        detected = interactions.detect_interaction(MODEL_MENU)

        self.assertEqual("model_select", detected.kind)
        self.assertEqual(3, len(detected.options))
        self.assertEqual("gpt-example-a", detected.options[0].label)
        self.assertTrue(detected.options[0].selected)
        self.assertTrue(detected.options[0].current)
        self.assertEqual("Balanced model for everyday work.", detected.options[1].description)
        self.assertEqual(0, detected.selected_index)

    def test_detects_reasoning_menu_and_normalizes_default_marker(self):
        detected = interactions.detect_interaction(REASONING_MENU)

        self.assertEqual("reasoning_select", detected.kind)
        self.assertEqual("Low", detected.options[0].label)
        self.assertTrue(detected.options[0].description.startswith("Default."))
        self.assertEqual("More reasoning...", detected.options[3].label)
        self.assertTrue(detected.options[3].current)
        self.assertTrue(detected.options[3].selected)

    def test_detects_resume_directory_as_a_specific_interaction(self):
        detected = interactions.detect_interaction(RESUME_MENU)

        self.assertEqual("resume_directory", detected.kind)
        self.assertEqual("Choose working directory", detected.title)
        self.assertEqual(4, len(detected.options))
        self.assertIn("/workspace/original", detected.options[0].label)

    def test_detects_single_choice_usage_menu_and_advanced_reasoning(self):
        usage = interactions.detect_interaction(USAGE_MENU)
        advanced = interactions.detect_interaction(ADVANCED_REASONING_MENU)

        self.assertEqual("usage_select", usage.kind)
        self.assertEqual(1, len(usage.options))
        self.assertEqual("Show usage", usage.options[0].label)
        self.assertEqual("reasoning_select", advanced.kind)
        self.assertEqual(["Max", "Ultra"], [option.label for option in advanced.options])
        self.assertTrue(advanced.options[0].current)

    def test_detects_permissions_as_a_specific_menu(self):
        detected = interactions.detect_interaction(
            """
Update Model Permissions
  1. Ask for approval  Ask before elevated actions.
› 2. Full Access (current)  Allow all actions.
Press enter to confirm or esc to go back
"""
        )

        self.assertEqual("permissions_select", detected.kind)
        self.assertEqual(2, len(detected.options))

    def test_detects_workspace_trust_and_approval(self):
        trust = interactions.detect_interaction(
            """
Do you trust the contents of this directory?
› 1. Yes, continue
  2. No, exit
Press enter to continue
"""
        )
        approval = interactions.detect_interaction(
            """
Would you like to run the following command?
  synthetic command summary
› 1. Yes, run it
  2. No, tell Codex what to do differently
Press enter to confirm
"""
        )

        self.assertEqual("workspace_trust", trust.kind)
        self.assertEqual("approval", approval.kind)

    def test_unknown_numbered_menu_gets_a_safe_generic_fallback(self):
        detected = interactions.detect_interaction(
            """
Choose a synthetic feature
› 1. First option
  2. Second option
Press enter to continue
"""
        )

        self.assertEqual("generic_tui", detected.kind)
        self.assertEqual(2, len(detected.options))

    def test_quoted_or_incomplete_menu_is_not_live(self):
        quoted = MODEL_MENU + "\n› Ask Codex to do anything\n"
        incomplete = MODEL_MENU.replace("Press enter to confirm or esc to go back", "")

        self.assertIsNone(interactions.detect_interaction(quoted))
        self.assertIsNone(interactions.detect_interaction(incomplete))

    def test_wrapped_description_is_appended_without_guessing_an_option(self):
        detected = interactions.detect_interaction(
            """
Select Model and Effort
› 1. gpt-example-a  A description that wraps
                    onto the next terminal row.
  2. gpt-example-b  Another option.
Press enter to confirm or esc to go back
"""
        )

        self.assertEqual(2, len(detected.options))
        self.assertIn("next terminal row", detected.options[0].description)

    def test_fingerprint_changes_only_with_semantic_state(self):
        first = interactions.detect_interaction(MODEL_MENU)
        same = interactions.detect_interaction("\x1b[2m" + MODEL_MENU + "\x1b[0m")
        changed = interactions.detect_interaction(MODEL_MENU.replace("› 1.", "  1.").replace("  2.", "› 2."))

        self.assertEqual(first.fingerprint(), same.fingerprint())
        self.assertNotEqual(first.fingerprint(), changed.fingerprint())


if __name__ == "__main__":
    unittest.main()
