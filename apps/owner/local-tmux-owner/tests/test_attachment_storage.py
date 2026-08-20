from __future__ import annotations

import datetime as dt
from io import BytesIO
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


OWNER_ROOT = Path(__file__).resolve().parents[1]
if str(OWNER_ROOT) not in sys.path:
    sys.path.insert(0, str(OWNER_ROOT))

import attachment_storage


class AttachmentStorageTest(unittest.TestCase):
    def test_magic_bytes_take_precedence_over_name_and_mime(self) -> None:
        suffix = attachment_storage.attachment_suffix(
            "misleading.txt",
            "text/plain",
            b"\x89PNG\r\n\x1a\nfixture",
        )
        self.assertEqual(suffix, ".png")

    def test_mime_and_allowed_filename_fallbacks_are_normalized(self) -> None:
        self.assertEqual(attachment_storage.attachment_suffix("paper.bin", "application/pdf", b"fixture"), ".pdf")
        self.assertEqual(attachment_storage.attachment_suffix("photo.JPEG", "", b"fixture"), ".jpg")

    def test_unsupported_attachment_is_rejected(self) -> None:
        with self.assertRaisesRegex(attachment_storage.AttachmentStorageError, "unsupported attachment type"):
            attachment_storage.attachment_suffix("payload.exe", "application/octet-stream", b"fixture")

    def test_save_is_bounded_generated_and_classified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            item = SimpleNamespace(filename="../../private.png", type="image/png", file=BytesIO(b"\x89PNG\r\n\x1a\nfixture"))
            now = dt.datetime(2026, 8, 20, 12, 34, 56)

            path, size, kind = attachment_storage.save_uploaded_attachment(item, root, max_bytes=100, now=now)

            self.assertEqual(path.parent, root / "2026-08-20")
            self.assertRegex(path.name, r"^20260820-123456-[0-9a-f]{6}\.png$")
            self.assertEqual(path.read_bytes(), b"\x89PNG\r\n\x1a\nfixture")
            self.assertEqual(size, len(path.read_bytes()))
            self.assertEqual(kind, "image")

    def test_save_rejects_empty_and_oversized_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(attachment_storage.AttachmentStorageError, "empty attachment"):
                attachment_storage.save_uploaded_attachment(
                    SimpleNamespace(filename="empty.txt", type="text/plain", file=BytesIO(b"")),
                    root,
                    max_bytes=3,
                )
            with self.assertRaisesRegex(attachment_storage.AttachmentStorageError, "attachment too large") as raised:
                attachment_storage.save_uploaded_attachment(
                    SimpleNamespace(filename="large.txt", type="text/plain", file=BytesIO(b"four")),
                    root,
                    max_bytes=3,
                )
            self.assertEqual(raised.exception.status, 413)

    def test_cleanup_removes_only_expired_date_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expired = root / "2026-08-13"
            boundary = root / "2026-08-14"
            unrelated = root / "manual"
            for directory in (expired, boundary, unrelated):
                directory.mkdir()
                (directory / "fixture.txt").write_text("fixture", encoding="utf-8")

            attachment_storage.cleanup_old_uploads(root, retention_days=7, today=dt.date(2026, 8, 20))

            self.assertFalse(expired.exists())
            self.assertTrue(boundary.is_dir())
            self.assertTrue(unrelated.is_dir())


if __name__ == "__main__":
    unittest.main()
