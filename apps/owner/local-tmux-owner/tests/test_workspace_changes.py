#!/usr/bin/env python3
"""Security and bounded-output tests for read-only workspace changes."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import workspace_changes as changes


def git(cwd: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *arguments], check=True, capture_output=True)


class WorkspaceChangesTest(unittest.TestCase):
    def make_repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Anonymous Test")
        git(repo, "config", "user.email", "anonymous.invalid")
        (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-qm", "fixture")
        return repo

    def test_collects_staged_unstaged_and_untracked_without_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self.make_repo(root)
            (repo / "tracked.txt").write_text("after\n", encoding="utf-8")
            (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
            (repo / "line\nbreak.txt").write_text("untracked\n", encoding="utf-8")
            git(repo, "add", "staged.txt")

            payload = changes.collect_workspace_changes(repo, root)

            self.assertEqual(payload["schemaVersion"], 1)
            self.assertEqual(payload["repository"]["name"], "repo")
            self.assertEqual(payload["summary"]["files"], 3)
            self.assertEqual(payload["summary"]["staged"], 1)
            self.assertEqual(payload["summary"]["unstaged"], 1)
            self.assertEqual(payload["summary"]["untracked"], 1)
            self.assertIn("tracked.txt", payload["diff"])
            self.assertNotIn(str(root), str(payload))

    def test_rejects_git_root_outside_workspace_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            allowed = root / "allowed"
            allowed.mkdir()
            repo = self.make_repo(root)
            link = allowed / "outside"
            link.symlink_to(repo, target_is_directory=True)
            with self.assertRaisesRegex(changes.WorkspaceChangesError, "workspace-out-of-scope"):
                changes.collect_workspace_changes(link, allowed)

    def test_non_git_directory_has_controlled_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(changes.WorkspaceChangesError, "not-a-git-worktree"):
                changes.collect_workspace_changes(temp, temp)

    def test_external_diff_configuration_is_not_executed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self.make_repo(root)
            marker = root / "external-diff-ran"
            helper = root / "external-diff"
            helper.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
            helper.chmod(0o700)
            git(repo, "config", "diff.external", str(helper))
            git(repo, "config", "core.fsmonitor", str(helper))
            (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")

            payload = changes.collect_workspace_changes(repo, root)

            self.assertIn("tracked.txt", payload["diff"])
            self.assertFalse(marker.exists())

    def test_diff_output_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self.make_repo(root)
            (repo / "tracked.txt").write_text("x" * (changes.DIFF_MAX_BYTES + 10_000), encoding="utf-8")

            payload = changes.collect_workspace_changes(repo, root)

            self.assertTrue(payload["summary"]["diffTruncated"])
            self.assertGreater(payload["summary"]["diffBytes"], changes.DIFF_MAX_BYTES)
            self.assertLessEqual(len(payload["diff"].encode("utf-8")), changes.DIFF_MAX_BYTES + 100)


if __name__ == "__main__":
    unittest.main()
