"""Shared auth, bounded-body, and response support for the Owner ASGI app."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
from http import HTTPStatus
import json
from pathlib import Path
import secrets
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import FileResponse, Response

import owner_http


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
                for name, value in owner_http.browser_security_headers().items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_security)


class OwnerAsgiSupport:
    def __init__(self, core: Any, config: Any, runtime: Any) -> None:
        self.core = core
        self.config = config
        self.runtime = runtime

    @staticmethod
    def json_response(value: dict[str, Any], status: int = HTTPStatus.OK) -> Response:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return Response(
            body,
            status_code=int(status),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )

    def require_token(self, request: Request) -> None:
        supplied = request.headers.get("X-Owner-Token") or request.query_params.get("token")
        if not supplied or not secrets.compare_digest(supplied, self.config.token):
            raise self.core.OwnerError("unauthorized", HTTPStatus.UNAUTHORIZED)

    async def bounded_body(self, request: Request, max_bytes: int) -> bytes:
        try:
            declared = int(request.headers.get("content-length", "0") or "0")
        except ValueError as exc:
            raise self.core.OwnerError("invalid content length") from exc
        if declared > max_bytes:
            raise self.core.OwnerError("request too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > max_bytes:
                raise self.core.OwnerError("request too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        return bytes(body)

    async def read_json(self, request: Request, max_bytes: int = 1_000_000) -> dict[str, Any]:
        raw = await self.bounded_body(request, max_bytes)
        try:
            value = json.loads(raw.decode("utf-8", errors="strict") if raw else "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise self.core.OwnerError("invalid json") from exc
        if not isinstance(value, dict):
            raise self.core.OwnerError("json body must be an object")
        return value

    async def read_multipart_form(self, request: Request) -> dict[str, Any]:
        content_type = request.headers.get("content-type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            raise self.core.OwnerError("expected multipart/form-data")
        raw = await self.bounded_body(
            request,
            self.core.MAX_ATTACHMENT_UPLOAD_BYTES + 1_000_000,
        )
        if not raw:
            raise self.core.OwnerError("empty request")
        message = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + content_type.encode("utf-8") + b"\r\n\r\n" + raw
        )
        form: dict[str, Any] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            item = owner_http.MultipartFile(
                part.get_filename() or "",
                part.get_content_type(),
                part.get_payload(decode=True) or b"",
            )
            if name in form:
                form[name] = form[name] + [item] if isinstance(form[name], list) else [form[name], item]
            else:
                form[name] = item
        return form

    def workspace_root(self, request: Request) -> str | None:
        value = request.headers.get("X-Faryo-Workspace-Root")
        return value.strip() if value and value.strip() else None

    def history_root(self, request: Request) -> str | None:
        if request.headers.get("X-Faryo-History-Scope", "").strip().lower() != "workspace":
            return None
        return self.workspace_root(request) or ""

    @staticmethod
    def inbox_root(request: Request) -> str | None:
        value = request.headers.get("X-Faryo-File-Inbox-Root")
        return value.strip() if value and value.strip() else None

    def target(self, session: str | None) -> Any:
        return self.core.target_config(self.config, session)

    @staticmethod
    def file_response(path: Path, content_type: str, *, download: bool = False) -> FileResponse:
        return FileResponse(
            path,
            media_type=content_type,
            filename=path.name if download else None,
            content_disposition_type="attachment" if download else "inline",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    def error_response(self, error: BaseException) -> Response:
        status = getattr(error, "status", HTTPStatus.INTERNAL_SERVER_ERROR)
        message = str(error) if isinstance(error, self.core.OwnerError) else "internal server error"
        return self.json_response(
            {"ok": False, "error": message, "updatedAt": self.core.now_iso()},
            int(status),
        )
