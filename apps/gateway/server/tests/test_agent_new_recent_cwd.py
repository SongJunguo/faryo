#!/usr/bin/env python3
"""Recent-cwd selection tests for new agent session launches."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SERVER_PATH = REPO_ROOT / "apps" / "gateway" / "server" / "server.py"

spec = importlib.util.spec_from_file_location("faryo_gateway_server", SERVER_PATH)
gateway = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(gateway)


def session(cwd: str, updated_ts: float) -> dict:
    return {"cwd": cwd, "updatedTs": updated_ts}


class SelectRecentAgentCwdTest(unittest.TestCase):
    def test_only_codex_is_a_supported_agent_launcher(self) -> None:
        self.assertEqual(gateway.clean_agent_launch_command("codex"), "codex")
        self.assertIsNone(gateway.clean_agent_launch_command("claude"))

    def test_context_window_is_optional_and_bounded_in_k_tokens(self) -> None:
        self.assertEqual(gateway.clean_context_window_k(None), 0)
        self.assertEqual(gateway.clean_context_window_k(272), 272)
        self.assertEqual(gateway.clean_context_window_k("1000"), 1000)
        for invalid in (True, 31, 1051, "272.5", "1m"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                gateway.clean_context_window_k(invalid)

    def test_picks_most_recent_cwd(self) -> None:
        sessions = [session("~/brain/projects/old", 10), session("~/brain/projects/faryo", 20)]
        self.assertEqual(gateway.select_recent_agent_cwd(sessions, None), "~/brain/projects/faryo")

    def test_cwd_choices_are_recent_distinct_and_include_workspace(self) -> None:
        sessions = [
            session("~/brain/projects/old", 10),
            session("~/brain/projects/faryo", 30),
            session("~/brain/projects/faryo/", 20),
        ]

        choices = gateway.agent_cwd_choices(sessions, "/srv/brain")

        self.assertEqual([item["value"] for item in choices], [
            "~/brain/projects/faryo",
            "~/brain/projects/old",
            "/srv/brain",
        ])
        self.assertEqual([item["kind"] for item in choices], ["recent", "recent", "workspace"])

    def test_home_shortened_workspace_is_not_duplicated(self) -> None:
        choices = gateway.agent_cwd_choices(
            [session("~/brain/projects", 20)],
            "/home/example/brain/projects",
        )

        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0]["kind"], "workspace")

    def test_directory_selection_token_is_bound_to_the_exact_path(self) -> None:
        token = gateway.owner_directory_selection_token("owner-secret", "/workspace/a")

        self.assertEqual(token, gateway.owner_directory_selection_token("owner-secret", "/workspace/a"))
        self.assertNotEqual(token, gateway.owner_directory_selection_token("owner-secret", "/workspace/b"))

    def test_client_launch_id_is_strict_and_owner_command_asset_is_proxyable(self) -> None:
        self.assertEqual(gateway.clean_client_launch_id("web-generic-launch-123"), "web-generic-launch-123")
        self.assertIsNone(gateway.clean_client_launch_id("short"))
        self.assertIsNone(gateway.clean_client_launch_id("bad launch id"))
        self.assertIn("codex-commands.js", gateway.OWNER_STATIC_FILES)
        self.assertIn("copy-fidelity.js", gateway.OWNER_STATIC_FILES)
        self.assertIn("owner-ui.js", gateway.OWNER_STATIC_FILES)

    def test_skips_exact_workspace_root(self) -> None:
        sessions = [session("/srv/brain", 20), session("/srv/brain/projects/faryo", 10)]
        self.assertEqual(gateway.select_recent_agent_cwd(sessions, "/srv/brain"), "/srv/brain/projects/faryo")

    def test_skips_home_shortened_workspace_root(self) -> None:
        sessions = [session("~/brain/00_inbox", 20), session("~/brain/projects/faryo", 10)]
        root = "/home/xiaofeng/brain/00_inbox"
        self.assertEqual(gateway.select_recent_agent_cwd(sessions, root), "~/brain/projects/faryo")

    def test_keeps_subdirectories_of_workspace_root(self) -> None:
        sessions = [session("~/brain/00_inbox/task-a", 20)]
        root = "/home/xiaofeng/brain/00_inbox"
        self.assertEqual(gateway.select_recent_agent_cwd(sessions, root), "~/brain/00_inbox/task-a")

    def test_ignores_blank_cwd_and_trailing_slash(self) -> None:
        sessions = [session("", 30), session("~/brain/00_inbox/", 20), session("~/brain/projects/faryo", 10)]
        root = "/home/xiaofeng/brain/00_inbox"
        self.assertEqual(gateway.select_recent_agent_cwd(sessions, root), "~/brain/projects/faryo")

    def test_skips_owner_home_directory(self) -> None:
        sessions = [session("~", 30), session("~/brain/projects/faryo", 10)]
        self.assertEqual(gateway.select_recent_agent_cwd(sessions, None), "~/brain/projects/faryo")

    def test_empty_when_no_candidate(self) -> None:
        self.assertEqual(gateway.select_recent_agent_cwd([], "/srv/brain"), "")
        self.assertEqual(gateway.select_recent_agent_cwd([session("/srv/brain", 5)], "/srv/brain"), "")
        self.assertEqual(gateway.select_recent_agent_cwd([session("~", 5)], "/home/xiaofeng/brain/00_inbox"), "")


if __name__ == "__main__":
    unittest.main()
