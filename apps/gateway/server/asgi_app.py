"""Incremental Starlette adapter for the Faryo Gateway contract."""

from __future__ import annotations

from http import HTTPStatus
import json
from pathlib import Path
import secrets
import time
from typing import Any

from anyio import to_thread
from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

import gateway_security
import owner_client


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
    client = owner_client.OwnerClient(legacy.BACKENDS, config, encode_label=legacy.owner_label_header_value)

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

    def forwarded_request_headers(request: Request) -> dict[str, str]:
        return {
            key: value for key, value in request.headers.items()
            if key.lower() not in legacy.HOP_BY_HOP_HEADERS and key.lower() not in owner_client.INTERNAL_HEADER_NAMES
        }

    def forwarded_response_headers(headers: list[tuple[str, str]]) -> dict[str, str]:
        forwarded: dict[str, str] = {}
        for key, value in headers:
            lower = key.lower()
            if lower in legacy.HOP_BY_HOP_HEADERS or lower in legacy.UPSTREAM_SECURITY_HEADERS or lower == "content-length":
                continue
            forwarded[key] = value
        return forwarded

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

    async def owner_control(request: Request) -> Response:
        current = username(request)
        if not current:
            return json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        route = str(request.path_params["route"])
        upstream_path = "/api/" + str(request.path_params["tail"])
        action = legacy.PROXY_CONTROL_ACTIONS.get(upstream_path)
        if route not in legacy.BACKENDS or not action:
            return json_response({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
        request_id = secrets.token_hex(8)
        started = time.monotonic()
        status = HTTPStatus.BAD_GATEWAY
        target = ""
        idempotent = False
        if not config.allowed_route(current, route):
            status = HTTPStatus.FORBIDDEN
            response = json_response({"ok": False, "error": "forbidden"}, status)
        else:
            supplied_csrf = request.headers.get(legacy.CSRF_HEADER, "").strip()
            expected_csrf = gateway_security.csrf_token(config.cookie_secret, current, config.auth_epoch(current))
            if not supplied_csrf or not secrets.compare_digest(supplied_csrf, expected_csrf):
                status = HTTPStatus.FORBIDDEN
                response = json_response({"ok": False, "error": "csrf required"}, status)
            else:
                body = await request.body()
                target = legacy.control_target_from_json(body)
                forwarded = forwarded_request_headers(request)
                path = upstream_path + (f"?{request.url.query}" if request.url.query else "")
                try:
                    upstream = await to_thread.run_sync(
                        lambda: client.raw_request(route, request.method, path, body, current, forwarded_headers=forwarded)
                    )
                    status = upstream.status
                    try:
                        result = json.loads(upstream.body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        result = {}
                    if isinstance(result, dict):
                        target = str(result.get("session") or target)
                        idempotent = bool(result.get("duplicate") or result.get("idempotent"))
                    response = Response(upstream.body, status_code=status, headers=forwarded_response_headers(upstream.headers))
                except owner_client.OwnerTransportError:
                    status = HTTPStatus.BAD_GATEWAY
                    response = json_response({"ok": False, "error": "upstream unavailable"}, status)
        response.headers["X-Faryo-Request-Id"] = request_id
        writer = getattr(config, "append_control_audit", None)
        if callable(writer):
            writer(
                username=current,
                route=route,
                action=action,
                target=target,
                request_id=request_id,
                status=int(status),
                duration_ms=round((time.monotonic() - started) * 1000),
                idempotent=idempotent,
            )
        return response

    async def owner_get(request: Request) -> Response:
        current = username(request)
        if not current:
            return json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        route = str(request.path_params["route"])
        if route not in legacy.BACKENDS:
            return json_response({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
        if not config.allowed_route(current, route):
            return json_response({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN)
        upstream_path = "/api/" + str(request.path_params["tail"])
        if request.url.query:
            upstream_path += "?" + request.url.query
        try:
            stream = await to_thread.run_sync(
                lambda: client.open_stream(
                    route,
                    "GET",
                    upstream_path,
                    None,
                    current,
                    forwarded_headers=forwarded_request_headers(request),
                )
            )
        except owner_client.OwnerTransportError:
            return json_response({"ok": False, "error": "upstream unavailable"}, HTTPStatus.BAD_GATEWAY)
        headers = forwarded_response_headers(stream.headers)
        content_type = next((value for key, value in stream.headers if key.lower() == "content-type"), "")
        if content_type.lower().startswith("text/event-stream"):
            headers["Cache-Control"] = "no-store, no-transform"

            async def body_iterator():
                try:
                    while True:
                        chunk = await to_thread.run_sync(stream.readline)
                        if not chunk:
                            break
                        yield chunk
                finally:
                    await to_thread.run_sync(stream.close)

            return StreamingResponse(body_iterator(), status_code=stream.status, headers=headers)
        try:
            body = await to_thread.run_sync(stream.read)
        finally:
            await to_thread.run_sync(stream.close)
        return Response(body, status_code=stream.status, headers=headers)

    routes = [
        Route("/manifest.json", manifest, methods=["GET"]),
        Route("/sw.js", service_worker, methods=["GET"]),
        Route("/login", login, methods=["GET"]),
        Route("/logout", logout, methods=["GET"]),
        Route("/api/csrf", csrf, methods=["GET"]),
        Route("/{route}/api/{tail:path}", owner_get, methods=["GET"]),
        Route("/{route}/api/{tail:path}", owner_control, methods=["POST"]),
        Route("/", home, methods=["GET"]),
        Route("/{filename}", static_asset, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(SecurityHeadersMiddleware)
    return app
