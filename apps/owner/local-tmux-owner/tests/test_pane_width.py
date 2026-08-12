import sys
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import server


class PaneWidthTest(unittest.TestCase):
    def setUp(self):
        self.config = server.Config("codex-test", "token", 500)

    def test_codex_tui_is_never_forced_to_capture_width(self):
        with (
            mock.patch.object(server, "has_session", return_value=True),
            mock.patch.object(server, "codex_cli_in_pane", return_value=True),
            mock.patch.object(server, "get_pane_width") as get_width,
            mock.patch.object(server, "tmux") as tmux,
        ):
            server.ensure_pane_width(self.config)

        get_width.assert_not_called()
        tmux.assert_not_called()

    def test_non_codex_background_pane_keeps_configured_capture_width(self):
        completed = mock.Mock(returncode=0, stderr="")
        with (
            mock.patch.object(server, "has_session", return_value=True),
            mock.patch.object(server, "codex_cli_in_pane", return_value=False),
            mock.patch.object(server, "get_pane_width", return_value=120),
            mock.patch.object(server, "tmux", return_value=completed) as tmux,
        ):
            server.ensure_pane_width(self.config)

        tmux.assert_called_once_with(
            self.config,
            ["resize-window", "-t", "codex-test", "-x", "500"],
            timeout=3,
        )


if __name__ == "__main__":
    unittest.main()
