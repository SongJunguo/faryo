from __future__ import annotations

from pathlib import Path
import sys
import unittest


SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import gateway_security


class GatewaySecurityTest(unittest.TestCase):
    def test_headers_keep_exact_csp_and_browser_hardening(self) -> None:
        headers = gateway_security.browser_security_headers("fixture-nonce")
        self.assertIn("script-src 'self' 'nonce-fixture-nonce'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Strict-Transport-Security"], "max-age=31536000")

    def test_cookie_round_trip_tamper_epoch_and_expiry(self) -> None:
        now = [1_000.0]
        codec = gateway_security.SessionCookieCodec(
            b"fixture-secret",
            name="__Host-faryo_auth",
            max_age=60,
            same_site="Strict",
            epoch_clock=lambda: now[0],
        )
        header = codec.issue("tester", 7)
        raw = header.split(";", 1)[0]
        users = {"tester": {}}
        self.assertEqual(codec.username(raw, users, lambda _user: 7), "tester")
        self.assertIsNone(codec.username(raw + "x", users, lambda _user: 7))
        self.assertIsNone(codec.username(raw, users, lambda _user: 8))
        now[0] += 60
        self.assertIsNone(codec.username(raw, users, lambda _user: 7))
        self.assertIn("Max-Age=0", codec.expire())

    def test_login_rate_key_trusts_cloudflare_only_from_loopback(self) -> None:
        self.assertEqual(gateway_security.login_rate_key("127.0.0.1", "203.0.113.7"), "203.0.113.7")
        self.assertEqual(gateway_security.login_rate_key("198.51.100.10", "203.0.113.7"), "198.51.100.10")
        self.assertEqual(gateway_security.login_rate_key("127.0.0.1", "invalid"), "127.0.0.1")

    def test_rate_limiter_blocks_at_threshold_and_can_clear(self) -> None:
        now = [0.0]
        limiter = gateway_security.LoginRateLimiter(window_seconds=10, block_seconds=20, max_failures=2, monotonic_clock=lambda: now[0])
        limiter.record_failure("client")
        self.assertFalse(limiter.limited("client"))
        limiter.record_failure("client")
        self.assertTrue(limiter.limited("client"))
        limiter.clear("client")
        self.assertFalse(limiter.limited("client"))

    def test_csrf_and_redirect_policy_are_deterministic(self) -> None:
        self.assertEqual(
            gateway_security.csrf_token(b"secret", "tester", 7),
            gateway_security.csrf_token(b"secret", "tester", 7),
        )
        self.assertEqual(gateway_security.safe_target("/txy/?session=fixture"), "/txy/?session=fixture")
        self.assertEqual(gateway_security.safe_target("//outside.invalid"), "/")
        self.assertEqual(gateway_security.safe_target("https://outside.invalid"), "/")


if __name__ == "__main__":
    unittest.main()
