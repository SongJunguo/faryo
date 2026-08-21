from __future__ import annotations

from pathlib import Path
import sys
import unittest


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import owner_http


class OwnerHttpTest(unittest.TestCase):
    def test_safe_log_path_discards_private_query(self) -> None:
        self.assertEqual(
            owner_http.safe_log_path("/api/status?token=private&session=secret"),
            "/api/status",
        )

    def test_security_headers_keep_owner_loopback_page_hardened(self) -> None:
        headers = owner_http.browser_security_headers()
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_multipart_value_is_memory_only_and_compatible_with_storage(self) -> None:
        item = owner_http.MultipartFile("fixture.txt", "text/plain", b"fixture")
        self.assertEqual(item.filename, "fixture.txt")
        self.assertEqual(item.type, "text/plain")
        self.assertEqual(item.file.read(), b"fixture")


if __name__ == "__main__":
    unittest.main()
