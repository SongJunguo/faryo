"""Starlette login, session-cookie, CSRF, and password routes."""

from __future__ import annotations

from http import HTTPStatus
import secrets
from typing import Any

from anyio import to_thread
import bcrypt
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

import gateway_security


class AuthRoutes:
    def __init__(self, legacy: Any, config: Any, support: Any) -> None:
        self.legacy = legacy
        self.config = config
        self.support = support

    async def login(self, request: Request) -> Response:
        target = gateway_security.safe_target(request.query_params.get("next", "/"))
        if request.method == "POST":
            body = await request.body()
            form = self.legacy.parse_qs(body[:8192].decode("utf-8", errors="replace"))
            candidate = form.get("username", [""])[0].strip()
            password = form.get("password", [""])[0]
            target = gateway_security.safe_target(form.get("next", [target])[0] or "/")
            peer = request.client.host if request.client else ""
            rate_key = gateway_security.login_rate_key(peer, request.headers.get("cf-connecting-ip", ""))
            user = self.config.user(candidate)
            valid = not self.legacy.LOGIN_LIMITER.limited(rate_key) and bool(user)
            if valid:
                valid = await to_thread.run_sync(
                    lambda: bcrypt.checkpw(password.encode("utf-8"), self.config.password_hash(candidate))
                )
            if not valid:
                self.legacy.LOGIN_LIMITER.record_failure(rate_key)
                return self.support.html_page(
                    request,
                    self.legacy.login_html(target, "Invalid username or password", self.config.icp_record),
                )
            self.legacy.LOGIN_LIMITER.clear(rate_key)
            response = RedirectResponse(target, status_code=HTTPStatus.SEE_OTHER)
            response.raw_headers.append(
                (b"set-cookie", self.support.codec().issue(candidate, self.config.auth_epoch(candidate)).encode("latin-1"))
            )
            response.raw_headers.append(
                (b"set-cookie", self.support.codec().expire(self.legacy.LEGACY_COOKIE_NAME).encode("latin-1"))
            )
            return response
        if self.support.username(request):
            return RedirectResponse(target, status_code=HTTPStatus.SEE_OTHER)
        return self.support.html_page(request, self.legacy.login_html(target, icp=self.config.icp_record))

    async def logout(self, _request: Request) -> Response:
        response = RedirectResponse("/login", status_code=HTTPStatus.SEE_OTHER)
        response.raw_headers.append((b"set-cookie", self.support.codec().expire().encode("latin-1")))
        response.raw_headers.append(
            (b"set-cookie", self.support.codec().expire(self.legacy.LEGACY_COOKIE_NAME).encode("latin-1"))
        )
        return response

    async def csrf(self, request: Request) -> Response:
        current = self.support.username(request)
        if not current:
            return self.support.json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        value = gateway_security.csrf_token(
            self.config.cookie_secret,
            current,
            self.config.auth_epoch(current),
        )
        return self.support.json_response({"ok": True, "csrf": value})

    async def password(self, request: Request) -> Response:
        current = self.support.username(request)
        if not current:
            target = gateway_security.safe_target(request.url.path)
            return RedirectResponse(
                "/login?" + self.legacy.urlencode({"next": target}),
                status_code=HTTPStatus.SEE_OTHER,
            )
        csrf_value = gateway_security.csrf_token(
            self.config.cookie_secret,
            current,
            self.config.auth_epoch(current),
        )
        if request.method == "GET":
            return self.support.html_page(
                request,
                self.legacy.password_html(csrf_value, icp=self.config.icp_record),
            )
        body = await request.body()
        form = self.legacy.parse_qs(body[:8192].decode("utf-8", errors="replace"))
        current_password = form.get("current_password", [""])[0]
        new_password = form.get("new_password", [""])[0]
        confirmation = form.get("confirm_password", [""])[0]
        if not secrets.compare_digest(form.get("csrf", [""])[0], csrf_value):
            return self.support.html_page(
                request,
                self.legacy.password_html(csrf_value, "Reload and try again", self.config.icp_record),
            )
        valid = await to_thread.run_sync(
            lambda: bcrypt.checkpw(current_password.encode("utf-8"), self.config.password_hash(current))
        )
        if not valid:
            return self.support.html_page(
                request,
                self.legacy.password_html(csrf_value, "Current password is incorrect", self.config.icp_record),
            )
        if len(new_password) < 16:
            return self.support.html_page(
                request,
                self.legacy.password_html(
                    csrf_value,
                    "New password must be at least 16 characters",
                    self.config.icp_record,
                ),
            )
        if new_password != confirmation:
            return self.support.html_page(
                request,
                self.legacy.password_html(
                    csrf_value,
                    "New password confirmation does not match",
                    self.config.icp_record,
                ),
            )
        await to_thread.run_sync(lambda: self.config.set_password(current, new_password))
        response = RedirectResponse("/?password=changed", status_code=HTTPStatus.SEE_OTHER)
        response.raw_headers.append(
            (b"set-cookie", self.support.codec().issue(current, self.config.auth_epoch(current)).encode("latin-1"))
        )
        response.raw_headers.append(
            (b"set-cookie", self.support.codec().expire(self.legacy.LEGACY_COOKIE_NAME).encode("latin-1"))
        )
        return response

    def routes(self) -> list[Route]:
        return [
            Route("/login", self.login, methods=["GET", "POST"]),
            Route("/logout", self.logout, methods=["GET"]),
            Route("/api/csrf", self.csrf, methods=["GET"]),
            Route("/password", self.password, methods=["GET", "POST"]),
        ]
