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
    def test_picks_most_recent_cwd(self) -> None:
        sessions = [session("~/brain/projects/old", 10), session("~/brain/projects/faryo", 20)]
        self.assertEqual(gateway.select_recent_agent_cwd(sessions, None), "~/brain/projects/faryo")

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
