import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import server


class StatusMetadataTest(unittest.TestCase):
    def test_fast_suffix_is_session_state_not_part_of_the_model_name(self):
        self.assertEqual(
            server.codex_model_status("gpt-5.6-sol max fast"),
            ("gpt-5.6-sol max", "max", "on"),
        )

    def test_model_without_fast_is_explicitly_default(self):
        self.assertEqual(
            server.codex_model_status("gpt-5.6-sol max"),
            ("gpt-5.6-sol max", "max", "off"),
        )

    def test_fast_inside_a_model_slug_is_not_treated_as_a_suffix(self):
        self.assertEqual(
            server.codex_model_status("gpt-fast-preview high"),
            ("gpt-fast-preview high", "high", "off"),
        )

    def test_missing_model_has_a_safe_default_speed(self):
        self.assertEqual(server.codex_model_status(None), (None, None, "off"))


if __name__ == "__main__":
    unittest.main()
