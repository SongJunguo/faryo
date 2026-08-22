from __future__ import annotations

import unittest

from faryo_cli import session_backend


class SessionBackendTest(unittest.TestCase):
    def test_domain_names_keep_legacy_wire_values_private(self) -> None:
        self.assertEqual(session_backend.APP_SERVER.value, "web-managed")
        self.assertEqual(session_backend.CODEX_TUI.value, "terminal-managed")
        self.assertEqual(session_backend.APP_SERVER.label, "Codex App Server")
        self.assertEqual(session_backend.CODEX_TUI.label, "Codex TUI (tmux)")

    def test_source_default_and_invalid_wire_value(self) -> None:
        self.assertIs(
            session_backend.backend_for_source("codex-app-server"),
            session_backend.APP_SERVER,
        )
        self.assertIs(
            session_backend.backend_for_source("codex-cli"),
            session_backend.CODEX_TUI,
        )
        self.assertIsNone(session_backend.parse_backend("abstract-backend"))


if __name__ == "__main__":
    unittest.main()
