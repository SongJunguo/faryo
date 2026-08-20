"""Shared Gateway cookie, CSRF, login-limit, redirect, and header policy."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
from http.cookies import SimpleCookie
from typing import Any, Callable, Mapping


def browser_security_headers(nonce: str = "") -> dict[str, str]:
    script_source = "'self'" + (f" 'nonce-{nonce}'" if nonce else "")
    return {
        "Content-Security-Policy": "; ".join([
            "default-src 'self'",
            f"script-src {script_source}",
            "script-src-attr 'none'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self'",
            "connect-src 'self'",
            "worker-src 'self'",
            "manifest-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
        ]),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), fullscreen=(self)",
        "Strict-Transport-Security": "max-age=31536000",
    }


def csrf_token(secret: bytes, username: str, auth_epoch: int) -> str:
    message = f"{username}|{auth_epoch}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def safe_target(value: str) -> str:
    return value if value.startswith("/") and not value.startswith("//") else "/"


def login_rate_key(peer: str, cloudflare_ip: str) -> str:
    try:
        peer_is_loopback = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        peer_is_loopback = False
    if peer_is_loopback:
        try:
            return ipaddress.ip_address(cloudflare_ip.strip()).compressed
        except ValueError:
            pass
    return peer


class SessionCookieCodec:
    def __init__(
        self,
        secret: bytes,
        *,
        name: str,
        max_age: int,
        same_site: str,
        epoch_clock: Callable[[], float] = time.time,
    ) -> None:
        self.secret = secret
        self.name = name
        self.max_age = max_age
        self.same_site = same_site
        self.epoch_clock = epoch_clock

    def issue(self, username: str, auth_epoch: int) -> str:
        payload = f"{username}|{int(self.epoch_clock())}|{auth_epoch}|{secrets.token_urlsafe(18)}"
        payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
        signature = hmac.new(self.secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{self.name}={payload_b64}.{signature}; Path=/; Max-Age={self.max_age}; HttpOnly; Secure; SameSite={self.same_site}"

    def expire(self, name: str | None = None) -> str:
        return f"{name or self.name}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite={self.same_site}"

    def username(self, raw_cookie: str, users: Mapping[str, Any], auth_epoch: Callable[[str], int]) -> str | None:
        if not raw_cookie:
            return None
        cookie = SimpleCookie(raw_cookie)
        morsel = cookie.get(self.name)
        if not morsel:
            return None
        try:
            payload_b64, signature = morsel.value.rsplit(".", 1)
            payload = base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
            expected = hmac.new(self.secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return None
            parts = payload.split("|")
            if len(parts) == 3:
                username, issued_at, _nonce = parts
                cookie_epoch = 0
            elif len(parts) == 4:
                username, issued_at, epoch, _nonce = parts
                cookie_epoch = int(epoch)
            else:
                return None
            if username not in users:
                return None
            current_epoch = auth_epoch(username)
            if current_epoch and cookie_epoch != current_epoch:
                return None
            if self.epoch_clock() - int(issued_at) >= self.max_age:
                return None
            return username
        except Exception:
            return None


class LoginRateLimiter:
    def __init__(
        self,
        *,
        window_seconds: float,
        block_seconds: float,
        max_failures: int,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self.max_failures = max_failures
        self.monotonic_clock = monotonic_clock
        self._state: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def limited(self, key: str) -> bool:
        now = self.monotonic_clock()
        with self._lock:
            entry = self._state.get(key)
            return bool(entry and entry.get("blocked_until", 0) > now)

    def record_failure(self, key: str) -> None:
        now = self.monotonic_clock()
        with self._lock:
            entry = self._state.setdefault(key, {"failures": [], "blocked_until": 0.0})
            entry["failures"] = [stamp for stamp in entry["failures"] if now - stamp < self.window_seconds] + [now]
            if len(entry["failures"]) >= self.max_failures:
                entry["blocked_until"] = now + self.block_seconds

    def clear(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)
