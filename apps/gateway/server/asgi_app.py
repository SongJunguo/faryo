"""Incremental Starlette adapter for the Faryo Gateway contract."""

from __future__ import annotations

from http import HTTPStatus
import json
from pathlib import Path
import secrets
import time
from typing import Any

from anyio import sleep, to_thread
from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

import gateway_security
import owner_client
import mcp_service


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
    mcp = mcp_service.McpService(
        config,
        protocol_version=legacy.MCP_PROTOCOL_VERSION,
        server_version=legacy.MCP_SERVER_VERSION,
        tool_name=legacy.MCP_TOOL_NAME,
        tool_schema=legacy.MCP_TOOL_SCHEMAS[legacy.MCP_TOOL_NAME],
    )

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

    def append_audit(
        *, username_value: str, route: str, action: str, target: str, request_id: str,
        status: int, started: float, idempotent: bool = False,
    ) -> None:
        writer = getattr(config, "append_control_audit", None)
        if not callable(writer):
            return
        writer(
            username=username_value,
            route=route,
            action=action,
            target=target,
            request_id=request_id,
            status=int(status),
            duration_ms=round((time.monotonic() - started) * 1000),
            idempotent=idempotent,
        )

    async def read_json_body(request: Request, max_bytes: int) -> dict[str, Any]:
        body = await request.body()
        if not body:
            raise ValueError("empty JSON body")
        if len(body) > max_bytes:
            raise ValueError("request too large")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise ValueError("invalid JSON object")
        return payload

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
        append_audit(
            username_value=current, route=route, action=action, target=target,
            request_id=request_id, status=status, started=started, idempotent=idempotent,
        )
        return response

    async def session_history_lifecycle(request: Request) -> Response:
        current = username(request)
        if not current:
            return json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        request_id = secrets.token_hex(8)
        started = time.monotonic()
        archived = request.url.path == "/api/session-history/archive"
        action = "archive" if archived else "unarchive"
        route = ""
        target = ""
        idempotent = False
        supplied_csrf = request.headers.get(legacy.CSRF_HEADER, "").strip()
        expected_csrf = gateway_security.csrf_token(config.cookie_secret, current, config.auth_epoch(current))
        if not supplied_csrf or not secrets.compare_digest(supplied_csrf, expected_csrf):
            status = HTTPStatus.FORBIDDEN
            response = json_response({"ok": False, "error": "csrf required"}, status)
        else:
            try:
                body = await request.body()
                if not body:
                    raise ValueError("empty JSON body")
                if len(body) > 4096:
                    raise ValueError("request too large")
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("invalid JSON object")
                route = str(payload.get("route") or "").strip().lower()
                target = legacy.clean_agent_session_id(str(payload.get("agent_session_id") or payload.get("agentSessionId") or "")) or ""
                if route not in legacy.BACKENDS or not target:
                    raise ValueError("route and agent_session_id are required")
                if not config.allowed_route(current, route):
                    status = HTTPStatus.FORBIDDEN
                    response = json_response({"ok": False, "error": "forbidden"}, status)
                else:
                    result = await to_thread.run_sync(
                        lambda: client.json_request(
                            route, f"/api/agent-session/{action}", {"agent_session_id": target}, current, timeout=10,
                        )
                    )
                    if not result.get("ok"):
                        raw_status = int(result.get("httpStatus") or HTTPStatus.BAD_GATEWAY)
                        status = raw_status if 100 <= raw_status <= 599 else HTTPStatus.BAD_GATEWAY
                        response = json_response({"ok": False, "error": str(result.get("error") or f"owner {action} failed")}, status)
                    else:
                        idempotent = bool(result.get("duplicate"))
                        status = HTTPStatus.OK
                        response = json_response({
                            "ok": True,
                            "agentSessionId": target,
                            "archived": bool(result.get("archived")),
                            "duplicate": idempotent,
                        })
            except (UnicodeDecodeError, json.JSONDecodeError):
                status = HTTPStatus.BAD_REQUEST
                response = json_response({"ok": False, "error": "invalid JSON body"}, status)
            except (TypeError, ValueError) as exc:
                status = HTTPStatus.BAD_REQUEST
                response = json_response({"ok": False, "error": str(exc)}, status)
        response.headers["X-Faryo-Request-Id"] = request_id
        append_audit(
            username_value=current, route=route, action=action, target=target,
            request_id=request_id, status=status, started=started, idempotent=idempotent,
        )
        return response

    async def revoke_sessions(request: Request) -> Response:
        current = username(request)
        if not current:
            return json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        request_id = secrets.token_hex(8)
        started = time.monotonic()
        supplied_csrf = request.headers.get(legacy.CSRF_HEADER, "").strip()
        expected_csrf = gateway_security.csrf_token(config.cookie_secret, current, config.auth_epoch(current))
        if not supplied_csrf or not secrets.compare_digest(supplied_csrf, expected_csrf):
            status = HTTPStatus.FORBIDDEN
            response = json_response({"ok": False, "error": "csrf required"}, status)
        else:
            try:
                body = await request.body()
                if not body:
                    raise ValueError("empty JSON body")
                if len(body) > 4096:
                    raise ValueError("request too large")
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("invalid JSON object")
                if payload.get("confirm") != "revoke":
                    raise ValueError("explicit revoke confirmation is required")
                config.revoke_sessions(current)
                status = HTTPStatus.OK
                response = json_response({"ok": True, "signedOut": True})
            except (UnicodeDecodeError, json.JSONDecodeError):
                status = HTTPStatus.BAD_REQUEST
                response = json_response({"ok": False, "error": "invalid JSON body"}, status)
            except ValueError as exc:
                status = HTTPStatus.BAD_REQUEST
                response = json_response({"ok": False, "error": str(exc)}, status)
        response.headers["X-Faryo-Request-Id"] = request_id
        append_audit(
            username_value=current, route="", action="revoke-sessions", target=current,
            request_id=request_id, status=status, started=started,
        )
        return response

    async def agent_resume(request: Request) -> Response:
        current = username(request)
        if not current:
            return json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        request_id = secrets.token_hex(8)
        started = time.monotonic()
        route = ""
        target = ""
        supplied_csrf = request.headers.get(legacy.CSRF_HEADER, "").strip()
        expected_csrf = gateway_security.csrf_token(config.cookie_secret, current, config.auth_epoch(current))
        if not supplied_csrf or not secrets.compare_digest(supplied_csrf, expected_csrf):
            status = HTTPStatus.FORBIDDEN
            response = json_response({"ok": False, "error": "csrf required"}, status)
        else:
            try:
                body = await request.body()
                if not body:
                    raise ValueError("empty JSON body")
                if len(body) > 65536:
                    raise ValueError("request too large")
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("invalid JSON object")
                route = str(payload.get("route") or "").strip()
                target = legacy.clean_agent_session_id(str(payload.get("agent_session_id") or "")) or ""
                source = str(payload.get("source") or "")
                if route not in legacy.BACKENDS or not target or not source:
                    raise ValueError("route, agent_session_id and source are required")
                if not config.allowed_route(current, route):
                    status = HTTPStatus.FORBIDDEN
                    response = json_response({"ok": False, "error": "forbidden"}, status)
                else:
                    result = await to_thread.run_sync(
                        lambda: client.json_request(
                            route,
                            "/api/agent/resume",
                            {"agent_session_id": target, "source": source, "max_running": config.max_running(route)},
                            current,
                            timeout=20,
                        )
                    )
                    session = legacy.clean_session_id(str(result.get("session") or "")) if result.get("ok") else ""
                    if not session:
                        status = HTTPStatus.BAD_GATEWAY
                        response = json_response({"ok": False, "error": result.get("error") or "owner resume failed"}, status)
                    else:
                        status = HTTPStatus.OK
                        response = json_response({"ok": True, "redirect": f"/{route}/?session={session}", "session": session})
            except (UnicodeDecodeError, json.JSONDecodeError):
                status = HTTPStatus.BAD_REQUEST
                response = json_response({"ok": False, "error": "invalid JSON body"}, status)
            except ValueError as exc:
                status = HTTPStatus.BAD_REQUEST
                response = json_response({"ok": False, "error": str(exc)}, status)
        response.headers["X-Faryo-Request-Id"] = request_id
        append_audit(
            username_value=current, route=route, action="resume", target=target,
            request_id=request_id, status=status, started=started,
        )
        return response

    async def agent_new(request: Request) -> Response:
        current = username(request)
        if not current:
            return json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        request_id = secrets.token_hex(8)
        started = time.monotonic()
        route = ""
        target = ""
        idempotent = False
        supplied_csrf = request.headers.get(legacy.CSRF_HEADER, "").strip()
        expected_csrf = gateway_security.csrf_token(config.cookie_secret, current, config.auth_epoch(current))
        if not supplied_csrf or not secrets.compare_digest(supplied_csrf, expected_csrf):
            status = HTTPStatus.FORBIDDEN
            response = json_response({"ok": False, "error": "csrf required"}, status)
        else:
            try:
                body = await request.body()
                if not body:
                    raise ValueError("empty JSON body")
                if len(body) > 4096:
                    raise ValueError("request too large")
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("invalid JSON object")
                route = str(payload.get("route") or "").strip()
                command = legacy.clean_agent_launch_command(str(payload.get("command") or ""))
                requested_cwd = str(payload.get("cwd") or "").strip().rstrip("/")
                cwd_token = str(payload.get("cwd_token") or payload.get("cwdToken") or "").strip()
                raw_launch_id = str(payload.get("client_launch_id") or payload.get("clientLaunchId") or "").strip()
                launch_id = legacy.clean_client_launch_id(raw_launch_id)
                target = launch_id or ""
                if route not in legacy.BACKENDS or not command:
                    raise ValueError("route and command are required")
                if raw_launch_id and not launch_id:
                    raise ValueError("invalid client launch id")
                if not config.allowed_route(current, route):
                    status = HTTPStatus.FORBIDDEN
                    response = json_response({"ok": False, "error": "forbidden"}, status)
                elif current != config.mcp_user and command != "codex":
                    status = HTTPStatus.FORBIDDEN
                    response = json_response({"ok": False, "error": "forbidden command"}, status)
                else:
                    launch = {"command": command, "max_running": config.max_running(route), **({"client_launch_id": launch_id} if launch_id else {})}
                    history_result = await to_thread.run_sync(
                        lambda: client.json_request(
                            route, legacy.owner_history_query(legacy.HISTORY_PAGE_SIZE, 0), None, current, method="GET",
                        )
                    )
                    recent_sessions = [
                        item for key in ("activeSessions", "sessions")
                        for item in (history_result.get(key) if isinstance(history_result.get(key), list) else [])
                        if isinstance(item, dict)
                    ]
                    if requested_cwd:
                        expected_cwd_token = legacy.owner_directory_selection_token(config.owner_token(route), requested_cwd)
                        if not cwd_token or not secrets.compare_digest(cwd_token, expected_cwd_token):
                            raise ValueError("working directory selection is invalid or expired")
                    selected_cwd = requested_cwd or legacy.select_recent_agent_cwd(recent_sessions, config.workspace_root(current, route))
                    selected_launch = {**launch, "cwd": selected_cwd, "cwd_token": cwd_token} if selected_cwd else launch

                    async def start(values: dict[str, Any]) -> dict[str, Any]:
                        return await to_thread.run_sync(
                            lambda: client.json_request(route, "/api/agent/new", values, current, timeout=20)
                        )

                    result = await start(selected_launch)
                    if launch_id and result.get("transportError"):
                        await sleep(0.25)
                        result = await start(selected_launch)
                    if selected_cwd and not requested_cwd and not result.get("ok"):
                        result = await start(launch)
                    session = legacy.clean_session_id(str(result.get("session") or "")) if result.get("ok") else ""
                    if not session:
                        status = HTTPStatus.BAD_GATEWAY
                        response = json_response({"ok": False, "error": result.get("error") or "owner new session failed"}, status)
                    else:
                        target = session
                        idempotent = bool(result.get("duplicate"))
                        status = HTTPStatus.OK
                        response = json_response({"ok": True, "redirect": f"/{route}/?session={session}", "session": session})
            except (UnicodeDecodeError, json.JSONDecodeError):
                status = HTTPStatus.BAD_REQUEST
                response = json_response({"ok": False, "error": "invalid JSON body"}, status)
            except ValueError as exc:
                status = HTTPStatus.BAD_REQUEST
                response = json_response({"ok": False, "error": str(exc)}, status)
        response.headers["X-Faryo-Request-Id"] = request_id
        append_audit(
            username_value=current, route=route, action="start", target=target,
            request_id=request_id, status=status, started=started, idempotent=idempotent,
        )
        return response

    async def bridge_package_create(request: Request) -> Response:
        current = username(request)
        if not current:
            return json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        supplied_csrf = request.headers.get(legacy.CSRF_HEADER, "").strip()
        expected_csrf = gateway_security.csrf_token(config.cookie_secret, current, config.auth_epoch(current))
        if not supplied_csrf or not secrets.compare_digest(supplied_csrf, expected_csrf):
            return json_response({"ok": False, "error": "csrf required"}, HTTPStatus.FORBIDDEN)
        try:
            payload = await read_json_body(request, legacy.BRIDGE_PACKAGE_MAX_BYTES)
            package = await to_thread.run_sync(lambda: config.save_bridge_package(payload, current))
            return json_response({"ok": True, "package": package})
        except ValueError as exc:
            return json_response({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    async def bridge_package_assets(request: Request) -> Response:
        current = username(request)
        if not current:
            return json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        supplied_csrf = request.headers.get(legacy.CSRF_HEADER, "").strip()
        expected_csrf = gateway_security.csrf_token(config.cookie_secret, current, config.auth_epoch(current))
        if not supplied_csrf or not secrets.compare_digest(supplied_csrf, expected_csrf):
            return json_response({"ok": False, "error": "csrf required"}, HTTPStatus.FORBIDDEN)
        try:
            payload = await read_json_body(request, legacy.BRIDGE_PACKAGE_MAX_BYTES)
            assets = config.bridge_asset_sources(payload)
            package_id = str(payload.get("package_id") or payload.get("packageId") or "")
            package = await to_thread.run_sync(lambda: config.append_bridge_package_assets(package_id, assets, current))
            return json_response({"ok": True, "package": package})
        except ValueError as exc:
            return json_response({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    async def bridge_inject(request: Request) -> Response:
        current = username(request)
        if not current:
            return json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        request_id = secrets.token_hex(8)
        started = time.monotonic()
        route = ""
        target = ""
        supplied_csrf = request.headers.get(legacy.CSRF_HEADER, "").strip()
        expected_csrf = gateway_security.csrf_token(config.cookie_secret, current, config.auth_epoch(current))
        if not supplied_csrf or not secrets.compare_digest(supplied_csrf, expected_csrf):
            status = HTTPStatus.FORBIDDEN
            response = json_response({"ok": False, "error": "csrf required"}, status)
        else:
            try:
                payload = await read_json_body(request, 65536)
                package_id = legacy.clean_package_id(str(payload.get("package_id") or payload.get("packageId") or ""))
                route = str(payload.get("route") or "").strip()
                session = legacy.clean_session_id(str(payload.get("session") or ""))
                agent_session_id = legacy.clean_agent_session_id(str(payload.get("agent_session_id") or ""))
                source = str(payload.get("source") or "")
                target = session or agent_session_id or package_id or ""
                if not package_id or route not in legacy.BACKENDS or (not session and not agent_session_id):
                    raise ValueError("package_id, route and session or agent_session_id are required")
                if agent_session_id and not source:
                    raise ValueError("source is required with agent_session_id")
                if not config.allowed_route(current, route):
                    status = HTTPStatus.FORBIDDEN
                    response = json_response({"ok": False, "error": "forbidden"}, status)
                else:
                    package = config.bridge_package(package_id, current)
                    if not package:
                        status = HTTPStatus.NOT_FOUND
                        response = json_response({"ok": False, "error": "package not found"}, status)
                    else:
                        target_package = package
                        assets = package.get("assets") if isinstance(package.get("assets"), list) else []
                        if assets:
                            delivered = []
                            for asset in assets:
                                if not isinstance(asset, dict):
                                    continue
                                path = Path(str(asset.get("path") or ""))
                                if not path.is_file() or config.bridge_root not in path.resolve().parents:
                                    raise ValueError("bridge asset is missing")
                                uploaded = await to_thread.run_sync(lambda path=path, asset=asset: client.attachment_request(
                                    route,
                                    path,
                                    str(asset.get("mime_type") or "application/octet-stream"),
                                    str(asset.get("file_name") or path.name),
                                    current,
                                ))
                                owner_path = str(uploaded.get("path") or "")
                                if not uploaded.get("ok") or not owner_path:
                                    raise ValueError(str(uploaded.get("error") or "owner attachment upload failed"))
                                delivered_asset = dict(asset)
                                delivered_asset["source_path"] = str(path)
                                delivered_asset["path"] = owner_path
                                delivered_asset["owner_path"] = owner_path
                                delivered.append(delivered_asset)
                            target_package = dict(package)
                            target_package["assets"] = delivered
                        target_session = session
                        if not target_session:
                            resume = await to_thread.run_sync(lambda: client.json_request(
                                route, "/api/agent/resume",
                                {"agent_session_id": agent_session_id, "source": source, "max_running": config.max_running(route)},
                                current,
                            ))
                            if not resume.get("ok"):
                                status = HTTPStatus.BAD_GATEWAY
                                response = json_response({"ok": False, "error": resume.get("error") or "owner resume failed"}, status)
                                target_session = ""
                            else:
                                target_session = legacy.clean_session_id(str(resume.get("session") or "")) or ""
                                if not target_session:
                                    status = HTTPStatus.BAD_GATEWAY
                                    response = json_response({"ok": False, "error": "owner did not return target session"}, status)
                        if target_session:
                            sent = await to_thread.run_sync(lambda: client.json_request(
                                route, "/api/send", {"session": target_session, "text": legacy.bridge_prompt_text(target_package)}, current,
                            ))
                            if not sent.get("ok"):
                                status = HTTPStatus.BAD_GATEWAY
                                response = json_response({"ok": False, "error": sent.get("error") or "owner inject failed"}, status)
                            else:
                                package["status"] = "injected"
                                package["target"] = {"route": route, "session": target_session, "agentSessionId": agent_session_id or "", "source": source}
                                config.update_bridge_package(package)
                                target = target_session
                                status = HTTPStatus.OK
                                response = json_response({"ok": True, "redirect": f"/{route}/?session={target_session}", "package": package})
            except ValueError as exc:
                status = HTTPStatus.BAD_REQUEST
                response = json_response({"ok": False, "error": str(exc)}, status)
        response.headers["X-Faryo-Request-Id"] = request_id
        append_audit(
            username_value=current, route=route, action="file-inject", target=target,
            request_id=request_id, status=status, started=started,
        )
        return response

    def mcp_headers(request: Request) -> dict[str, str]:
        headers = {"Cache-Control": "no-store"}
        if origin := mcp.cors_origin(request.headers.get("origin", "")):
            headers["Access-Control-Allow-Origin"] = origin
            headers["Vary"] = "Origin"
        return headers

    def mcp_authorized(request: Request) -> bool:
        return mcp.authorized(
            request.headers.get("authorization", ""),
            request.headers.get("x-faryo-mcp-token", ""),
        )

    def mcp_json(request: Request, value: Any, status: int = HTTPStatus.OK) -> Response:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        headers = {**mcp_headers(request), "Content-Type": "application/json; charset=utf-8"}
        return Response(body, status_code=status, headers=headers)

    async def mcp_options(request: Request) -> Response:
        headers = mcp_headers(request)
        headers.pop("Cache-Control", None)
        headers["Access-Control-Allow-Headers"] = "authorization, content-type, mcp-protocol-version, mcp-session-id, x-faryo-mcp-token"
        headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        return Response(status_code=HTTPStatus.NO_CONTENT, headers=headers)

    async def mcp_get(request: Request) -> Response:
        if not config.mcp_token:
            return mcp_json(request, mcp.error(None, -32001, "mcp disabled"), HTTPStatus.NOT_FOUND)
        if not mcp_authorized(request):
            return mcp_json(request, mcp.error(None, -32001, "unauthorized"), HTTPStatus.UNAUTHORIZED)
        headers = mcp_headers(request)
        headers["Allow"] = "POST, OPTIONS"
        return Response(status_code=HTTPStatus.METHOD_NOT_ALLOWED, headers=headers)

    async def mcp_post(request: Request) -> Response:
        if not config.mcp_token:
            return mcp_json(request, mcp.error(None, -32001, "mcp disabled"), HTTPStatus.NOT_FOUND)
        if not mcp_authorized(request):
            return mcp_json(request, mcp.error(None, -32001, "unauthorized"), HTTPStatus.UNAUTHORIZED)
        try:
            body = await request.body()
            if not body:
                raise ValueError("empty JSON body")
            if len(body) > legacy.BRIDGE_PACKAGE_MAX_BYTES:
                raise ValueError("request too large")
            payload = json.loads(body.decode("utf-8"))
            result = await to_thread.run_sync(lambda: mcp.response(payload, public_base_url(request)))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return mcp_json(request, mcp.error(None, -32700, "invalid JSON body"), HTTPStatus.BAD_REQUEST)
        except ValueError as exc:
            return mcp_json(request, mcp.error(None, -32700, str(exc)), HTTPStatus.BAD_REQUEST)
        if result is None:
            return Response(status_code=HTTPStatus.ACCEPTED, headers=mcp_headers(request))
        return mcp_json(request, result)

    def public_base_url(request: Request) -> str:
        scheme = request.headers.get("x-forwarded-proto") or "https"
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        return f"{scheme}://{host}".rstrip("/")

    async def proxy_owner_get(request: Request, current: str, route: str, upstream_path: str) -> Response:
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
        return await proxy_owner_get(request, current, route, upstream_path)

    async def owner_resource(request: Request) -> Response:
        current = username(request)
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if not current:
            return RedirectResponse("/login?" + legacy.urlencode({"next": gateway_security.safe_target(target)}), status_code=HTTPStatus.SEE_OTHER)
        route = str(request.path_params["route"])
        tail = str(request.path_params.get("tail") or "")
        if route not in legacy.BACKENDS:
            return Response("not found", status_code=HTTPStatus.NOT_FOUND)
        allowed = (not tail and bool(request.query_params.get("session"))) or tail in legacy.OWNER_STATIC_FILES or tail.startswith(legacy.OWNER_STATIC_PREFIXES)
        if not allowed:
            return Response("not found", status_code=HTTPStatus.NOT_FOUND)
        if not config.allowed_route(current, route):
            return html_page(request, "<!doctype html><meta charset='utf-8'><title>403</title><p>Access denied for this endpoint</p>", HTTPStatus.FORBIDDEN)
        upstream_path = "/" + tail
        if request.url.query:
            upstream_path += "?" + request.url.query
        return await proxy_owner_get(request, current, route, upstream_path)

    routes = [
        Route("/manifest.json", manifest, methods=["GET"]),
        Route("/sw.js", service_worker, methods=["GET"]),
        Route("/login", login, methods=["GET"]),
        Route("/logout", logout, methods=["GET"]),
        Route("/api/csrf", csrf, methods=["GET"]),
        Route("/{route}/api/{tail:path}", owner_get, methods=["GET"]),
        Route("/{route}/api/{tail:path}", owner_control, methods=["POST"]),
        Route("/api/session-history/archive", session_history_lifecycle, methods=["POST"]),
        Route("/api/session-history/unarchive", session_history_lifecycle, methods=["POST"]),
        Route("/api/auth/revoke-all", revoke_sessions, methods=["POST"]),
        Route("/api/agent/resume", agent_resume, methods=["POST"]),
        Route("/api/agent/new", agent_new, methods=["POST"]),
        Route("/api/bridge-packages", bridge_package_create, methods=["POST"]),
        Route("/api/bridge-package-assets", bridge_package_assets, methods=["POST"]),
        Route("/api/bridge-inject", bridge_inject, methods=["POST"]),
        Route("/mcp", mcp_options, methods=["OPTIONS"]),
        Route("/mcp", mcp_get, methods=["GET"]),
        Route("/mcp", mcp_post, methods=["POST"]),
        Route("/", home, methods=["GET"]),
        Route("/{route}/{tail:path}", owner_resource, methods=["GET"]),
        Route("/{filename}", static_asset, methods=["GET"]),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(SecurityHeadersMiddleware)
    return app
