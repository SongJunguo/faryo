#!/usr/bin/env python3
"""Contract tests for the privacy-safe public Access verifier."""

from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "apps" / "gateway" / "scripts" / "verify-public-access.sh"
TARGET = "https://private-host.example/"


class VerifyPublicAccessTest(unittest.TestCase):
    def run_verifier(
        self,
        headers: str,
        body: str = "",
        metrics: str = "302 0",
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            fake_curl = Path(temporary) / "curl"
            fake_curl.write_text(textwrap.dedent("""\
                #!/usr/bin/env python3
                import os
                import pathlib
                import sys

                args = sys.argv[1:]
                headers = pathlib.Path(args[args.index("--dump-header") + 1])
                body = pathlib.Path(args[args.index("--output") + 1])
                headers.write_text(os.environ.get("FARYO_FAKE_HEADERS", ""), encoding="utf-8")
                body.write_text(os.environ.get("FARYO_FAKE_BODY", ""), encoding="utf-8")
                print(os.environ.get("FARYO_FAKE_METRICS", "302 0"), end="")
                raise SystemExit(int(os.environ.get("FARYO_FAKE_EXIT", "0")))
            """), encoding="utf-8")
            fake_curl.chmod(0o755)
            env = dict(os.environ)
            env.update({
                "PATH": f"{temporary}:{env.get('PATH', '')}",
                "FARYO_FAKE_HEADERS": headers,
                "FARYO_FAKE_BODY": body,
                "FARYO_FAKE_METRICS": metrics,
            })
            return subprocess.run(
                [str(SCRIPT), TARGET],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

    def test_accepts_cloudflare_access_login_redirect(self) -> None:
        result = self.run_verifier(
            "HTTP/2 302\r\n"
            "location: https://team.cloudflareaccess.com/cdn-cgi/access/login/application\r\n\r\n"
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("tls=PASS access=PASS origin-login=BLOCKED http=302", result.stdout)
        self.assertNotIn("private-host", result.stdout + result.stderr)

    def test_rejects_direct_faryo_login_redirect(self) -> None:
        result = self.run_verifier("HTTP/2 303\r\nlocation: /login\r\n\r\n", metrics="303 0")

        self.assertEqual(result.returncode, 3)
        self.assertIn("tls=PASS access=MISSING origin-login=EXPOSED http=303", result.stdout)
        self.assertNotIn("private-host", result.stdout + result.stderr)

    def test_rejects_direct_faryo_login_page(self) -> None:
        result = self.run_verifier(
            "HTTP/2 200\r\ncontent-type: text/html\r\n\r\n",
            '<form method="post" action="/login">',
            "200 0",
        )

        self.assertEqual(result.returncode, 3)
        self.assertIn("access=MISSING origin-login=EXPOSED", result.stdout)

    def test_unknown_response_is_inconclusive_not_a_pass(self) -> None:
        result = self.run_verifier("HTTP/2 502\r\n\r\n", metrics="502 0")

        self.assertEqual(result.returncode, 4)
        self.assertIn("access=INCONCLUSIVE origin-login=UNKNOWN", result.stdout)


if __name__ == "__main__":
    unittest.main()
