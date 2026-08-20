"""Starlette route adapter for the shared MCP service."""

from __future__ import annotations

from http import HTTPStatus
import json
from typing import Any

from anyio import to_thread
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route


class McpRoutes:
    def __init__(self, legacy: Any, config: Any, service: Any) -> None:
        self.legacy = legacy
        self.config = config
        self.service = service

    def headers(self, request: Request) -> dict[str, str]:
        headers = {"Cache-Control": "no-store"}
        if origin := self.service.cors_origin(request.headers.get("origin", "")):
            headers["Access-Control-Allow-Origin"] = origin
            headers["Vary"] = "Origin"
        return headers

    def authorized(self, request: Request) -> bool:
        return self.service.authorized(
            request.headers.get("authorization", ""),
            request.headers.get("x-faryo-mcp-token", ""),
        )

    def json_response(self, request: Request, value: Any, status: int = HTTPStatus.OK) -> Response:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        headers = {**self.headers(request), "Content-Type": "application/json; charset=utf-8"}
        return Response(body, status_code=status, headers=headers)

    async def options(self, request: Request) -> Response:
        headers = self.headers(request)
        headers.pop("Cache-Control", None)
        headers["Access-Control-Allow-Headers"] = (
            "authorization, content-type, mcp-protocol-version, mcp-session-id, x-faryo-mcp-token"
        )
        headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return Response(status_code=HTTPStatus.NO_CONTENT, headers=headers)

    async def get(self, request: Request) -> Response:
        if not self.config.mcp_token:
            return self.json_response(request, self.service.error(None, -32001, "mcp disabled"), HTTPStatus.NOT_FOUND)
        if not self.authorized(request):
            return self.json_response(request, self.service.error(None, -32001, "unauthorized"), HTTPStatus.UNAUTHORIZED)
        headers = self.headers(request)
        headers["Allow"] = "POST, OPTIONS"
        return Response(status_code=HTTPStatus.METHOD_NOT_ALLOWED, headers=headers)

    async def post(self, request: Request) -> Response:
        if not self.config.mcp_token:
            return self.json_response(request, self.service.error(None, -32001, "mcp disabled"), HTTPStatus.NOT_FOUND)
        if not self.authorized(request):
            return self.json_response(request, self.service.error(None, -32001, "unauthorized"), HTTPStatus.UNAUTHORIZED)
        try:
            body = await request.body()
            if not body:
                raise ValueError("empty JSON body")
            if len(body) > self.legacy.BRIDGE_PACKAGE_MAX_BYTES:
                raise ValueError("request too large")
            payload = json.loads(body.decode("utf-8"))
            result = await to_thread.run_sync(lambda: self.service.response(payload, self.public_base_url(request)))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self.json_response(request, self.service.error(None, -32700, "invalid JSON body"), HTTPStatus.BAD_REQUEST)
        except ValueError as exc:
            return self.json_response(request, self.service.error(None, -32700, str(exc)), HTTPStatus.BAD_REQUEST)
        if result is None:
            return Response(status_code=HTTPStatus.ACCEPTED, headers=self.headers(request))
        return self.json_response(request, result)

    @staticmethod
    def public_base_url(request: Request) -> str:
        scheme = request.headers.get("x-forwarded-proto") or "https"
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        return f"{scheme}://{host}".rstrip("/")

    def routes(self) -> list[Route]:
        return [
            Route("/mcp", self.options, methods=["OPTIONS"]),
            Route("/mcp", self.get, methods=["GET", "DELETE"]),
            Route("/mcp", self.post, methods=["POST"]),
        ]
