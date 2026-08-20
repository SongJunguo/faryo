"""Starlette Owner GET, SSE, and allowlisted asset proxy routes."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from anyio import to_thread
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

import gateway_security
import owner_client


class OwnerProxyRoutes:
    def __init__(self, legacy: Any, config: Any, client: owner_client.OwnerClient, support: Any) -> None:
        self.legacy = legacy
        self.config = config
        self.client = client
        self.support = support

    async def proxy_get(self, request: Request, current: str, route: str, upstream_path: str) -> Response:
        try:
            stream = await to_thread.run_sync(
                lambda: self.client.open_stream(
                    route,
                    "GET",
                    upstream_path,
                    None,
                    current,
                    forwarded_headers=self.support.forwarded_request_headers(request),
                )
            )
        except owner_client.OwnerTransportError:
            return self.support.json_response({"ok": False, "error": "upstream unavailable"}, HTTPStatus.BAD_GATEWAY)
        headers = self.support.forwarded_response_headers(stream.headers)
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

    async def api_get(self, request: Request) -> Response:
        current = self.support.username(request)
        if not current:
            return self.support.json_response({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        route = str(request.path_params["route"])
        if route not in self.legacy.BACKENDS:
            return self.support.json_response({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
        if not self.config.allowed_route(current, route):
            return self.support.json_response({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN)
        upstream_path = "/api/" + str(request.path_params["tail"])
        if request.url.query:
            upstream_path += "?" + request.url.query
        return await self.proxy_get(request, current, route, upstream_path)

    async def resource_get(self, request: Request) -> Response:
        current = self.support.username(request)
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if not current:
            next_target = gateway_security.safe_target(target)
            return RedirectResponse(
                "/login?" + self.legacy.urlencode({"next": next_target}),
                status_code=HTTPStatus.SEE_OTHER,
            )
        route = str(request.path_params["route"])
        tail = str(request.path_params.get("tail") or "")
        if route not in self.legacy.BACKENDS:
            return Response("not found", status_code=HTTPStatus.NOT_FOUND)
        allowed = (
            (not tail and bool(request.query_params.get("session")))
            or tail in self.legacy.OWNER_STATIC_FILES
            or tail.startswith(self.legacy.OWNER_STATIC_PREFIXES)
        )
        if not allowed:
            return Response("not found", status_code=HTTPStatus.NOT_FOUND)
        if not self.config.allowed_route(current, route):
            return self.support.html_page(
                request,
                "<!doctype html><meta charset='utf-8'><title>403</title><p>Access denied for this endpoint</p>",
                HTTPStatus.FORBIDDEN,
            )
        upstream_path = "/" + tail
        if request.url.query:
            upstream_path += "?" + request.url.query
        return await self.proxy_get(request, current, route, upstream_path)

    def api_route(self) -> Route:
        return Route("/{route}/api/{tail:path}", self.api_get, methods=["GET"])

    def resource_route(self) -> Route:
        return Route("/{route}/{tail:path}", self.resource_get, methods=["GET"])
