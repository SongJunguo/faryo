"""Incremental Starlette adapter for the Faryo Gateway contract."""

from __future__ import annotations

from http import HTTPStatus
import json
from pathlib import Path
import secrets
from typing import Any

from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

import gateway_security


class SecurityHeadersMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                nonce = str(scope.get("state", {}).get("csp_nonce") or "")
                for name, value in gateway_security.browser_security_headers(nonce).items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_security)


def create_app(legacy: Any, config: Any) -> Starlette:
    static_dir = Path(legacy.STATIC_DIR)
    shared_static_dir = Path(legacy.SHARED_STATIC_DIR)

    def codec() -> gateway_security.SessionCookieCodec:
        return gateway_security.SessionCookieCodec(
            config.cookie_secret,
            name=legacy.COOKIE_NAME,
            max_age=legacy.COOKIE_MAX_AGE,
            same_site=legacy.COOKIE_SAME_SITE,
        )

    def username(request: Request) -> str | None:
        return codec().username(request.headers.get("cookie", ""), config.users, config.auth_epoch)

    def html_page(request: Request, value: str, status: int = HTTPStatus.OK) -> HTMLResponse:
        nonce = secrets.token_urlsafe(18)
        request.scope.setdefault("state", {})["csp_nonce"] = nonce
        body = value.replace(legacy.CSP_NONCE_PLACEHOLDER, nonce)
        return HTMLResponse(body, status_code=status, headers={"Cache-Control": "no-store"})

    def json_response(value: dict[str, Any], status: int = HTTPStatus.OK) -> Response:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        return Response(body, status_code=status, headers={"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"})

    async def manifest(_request: Request) -> Response:
        return json_response(legacy.PWA_MANIFEST)

    async def service_worker(_request: Request) -> Response:
        return Response(legacy.PWA_SW.encode("utf-8"), media_type="text/javascript", headers={"Cache-Control": "no-store"})

    async def static_asset(request: Request) -> Response:
        filename = request.path_params["filename"]
        content_type = legacy.GATEWAY_STATIC_FILES.get(filename) or legacy.SHARED_STATIC_FILES.get(filename)
        if not content_type:
            return Response("not found", status_code=HTTPStatus.NOT_FOUND)
        root = static_dir if filename in legacy.GATEWAY_STATIC_FILES else shared_static_dir
        return Response((root / filename).read_bytes(), headers={"Content-Type": content_type, "Cache-Control": "no-store"})

    async def login(request: Request) -> Response:
        target = gateway_security.safe_target(request.query_params.get("next", "/"))
        if username(request):
            return RedirectResponse(target, status_code=HTTPStatus.SEE_OTHER)
        return html_page(request, legacy.login_html(target, icp=config.icp_record))

    async def logout(_request: Request) -> Response:
        response = RedirectResponse("/login", status_code=HTTPStatus.SEE_OTHER)
        response.raw_headers.append((b"set-cookie", codec().expire().encode("latin-1")))
        response.raw_headers.append((b"set-cookie", codec().expire(legacy.LEGACY_COOKIE_NAME).encode("latin-1")))
        return response

    async def csrf(request: Request) -> Response:
        current = username(request)
        if not current:
            return json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        value = gateway_security.csrf_token(config.cookie_secret, current, config.auth_epoch(current))
        return json_response({"ok": True, "csrf": value})

    async def home(request: Request) -> Response:
        current = username(request)
        if not current:
            target = gateway_security.safe_target(request.url.path + (f"?{request.url.query}" if request.url.query else ""))
            return RedirectResponse("/login?" + legacy.urlencode({"next": target}), status_code=HTTPStatus.SEE_OTHER)
        return html_page(request, legacy.portal_html(current, config.user_routes(current)))

    routes = [
        Route("/manifest.json", manifest, methods=["GET"]),
        Route("/sw.js", service_worker, methods=["GET"]),
        Route("/login", login, methods=["GET"]),
        Route("/logout", logout, methods=["GET"]),
        Route("/api/csrf", csrf, methods=["GET"]),
        Route("/", home, methods=["GET"]),
        Route("/{filename}", static_asset, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(SecurityHeadersMiddleware)
    return app
