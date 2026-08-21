from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
import sys
import tempfile
import unittest


OWNER_ROOT = Path(__file__).resolve().parents[1]
if str(OWNER_ROOT) not in sys.path:
    sys.path.insert(0, str(OWNER_ROOT))

import path_policy


class PathPolicyTest(unittest.TestCase):
    def test_clean_local_path_unwraps_common_markup_and_rejects_missing(self) -> None:
        self.assertEqual(path_policy.clean_local_path(" <notes.md> "), "notes.md")
        self.assertEqual(path_policy.clean_local_path("'notes.md'"), "notes.md")
        with self.assertRaisesRegex(path_policy.PathPolicyError, "missing file path"):
            path_policy.clean_local_path("\x00")

    def test_local_file_resolution_uses_bases_and_suffix_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            allowed = root / "notes.md"
            denied = root / "payload.exe"
            allowed.write_text("fixture", encoding="utf-8")
            denied.write_text("fixture", encoding="utf-8")

            self.assertEqual(path_policy.resolve_local_file("notes.md", [root], {".md"}), allowed.resolve())
            with self.assertRaisesRegex(path_policy.PathPolicyError, "file not found") as raised:
                path_policy.resolve_local_file("payload.exe", [root], {".md"})
            self.assertEqual(raised.exception.status, HTTPStatus.NOT_FOUND)

    def test_roots_are_resolved_deduplicated_and_default_to_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.assertEqual(path_policy.start_directory_roots([str(root), str(root)], None), [root])
            self.assertEqual(path_policy.start_directory_roots([], None, home=root), [root])

    def test_start_directory_rejects_scope_escape_and_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside_temp:
            root = Path(temp).resolve()
            child = root / "child"
            child.mkdir()
            outside = Path(outside_temp).resolve()

            self.assertEqual(path_policy.resolve_start_directory(str(child), [root]), child)
            with self.assertRaisesRegex(path_policy.PathPolicyError, "outside the configured roots") as outside_error:
                path_policy.resolve_start_directory(str(outside), [root])
            self.assertEqual(outside_error.exception.status, HTTPStatus.FORBIDDEN)
            with self.assertRaisesRegex(path_policy.PathPolicyError, "unavailable"):
                path_policy.resolve_start_directory(str(root / "missing"), [root])

    def test_directory_listing_keeps_all_children_except_hidden_toggle_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside_temp:
            root = Path(temp).resolve()
            for name in ("alpha", "beta", ".hidden"):
                (root / name).mkdir()
            (root / "escape").symlink_to(Path(outside_temp), target_is_directory=True)

            parent, directories, truncated = path_policy.list_start_directories(
                root,
                [root],
            )
            _hidden_parent, hidden_directories, hidden_truncated = (
                path_policy.list_start_directories(
                    root,
                    [root],
                    show_hidden=True,
                )
            )

            self.assertIsNone(parent)
            self.assertEqual([item.name for item in directories], ["alpha", "beta"])
            self.assertFalse(truncated)
            self.assertEqual(
                [item.name for item in hidden_directories],
                [".hidden", "alpha", "beta"],
            )
            self.assertFalse(hidden_truncated)

    def test_directory_listing_has_no_automatic_entry_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            for index in range(200):
                (root / f"folder-{index:03d}").mkdir()

            _parent, directories, truncated = path_policy.list_start_directories(
                root,
                [root],
            )

        self.assertEqual(len(directories), 200)
        self.assertFalse(truncated)

    def test_directory_selection_token_is_path_bound(self) -> None:
        first = path_policy.directory_selection_token("secret", Path("/workspace/a"))
        self.assertEqual(first, path_policy.directory_selection_token("secret", Path("/workspace/a")))
        self.assertNotEqual(first, path_policy.directory_selection_token("secret", Path("/workspace/b")))


if __name__ == "__main__":
    unittest.main()
