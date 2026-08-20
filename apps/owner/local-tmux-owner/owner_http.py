"""HTTP auth, bounded body parsing, and response helpers for the Owner adapter."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
import gzip
from http import HTTPStatus
import io
import json
from pathlib import Path
import re
import secrets
import shutil
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlparse


def browser_security_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": "; ".join([
            "default-src 'self'",
            "script-src 'self'",
            "script-src-attr 'none'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self'",
            "connect-src 'self'",
            "worker-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
        ]),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), fullscreen=(self)",
    }


def safe_log_path(value: str) -> str:
    return urlparse(value).path


class MultipartFile:
    def __init__(self, filename: str, content_type: str, data: bytes) -> None:
        self.filename = filename
        self.type = content_type
        self.file = io.BytesIO(data)


class OwnerHttpSupport:
    def __init__(
        self,
        handler: Any,
        *,
        error_factory: Callable[[str, HTTPStatus], Exception],
        token: Callable[[], str],
        max_attachment_bytes: int,
    ) -> None:
        self.handler = handler
        self.error_factory = error_factory
        self.token = token
        self.max_attachment_bytes = max_attachment_bytes

    def error(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> Exception:
        return self.error_factory(message, status)

    def read_multipart_form(self) -> dict[str, Any]:
        content_type = self.handler.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            raise self.error("expected multipart/form-data")
        try:
            length = int(self.handler.headers.get("Content-Length", "0") or "0")
        except ValueError as exc:
            raise self.error("invalid content length") from exc
        if length <= 0:
            raise self.error("empty request")
        if length > self.max_attachment_bytes + 1_000_000:
            raise self.error("request too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        raw = self.handler.rfile.read(length)
        message = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + content_type.encode("utf-8") + b"\r\n\r\n" + raw
        )
        form: dict[str, Any] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            item = MultipartFile(
                part.get_filename() or "",
                part.get_content_type(),
                part.get_payload(decode=True) or b"",
            )
            if name in form:
                form[name] = form[name] + [item] if isinstance(form[name], list) else [form[name], item]
            else:
                form[name] = item
        return form

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.handler.headers.get("Content-Length", "0") or "0")
        except ValueError as exc:
            raise self.error("invalid content length") from exc
        if length > 1_000_000:
            raise self.error("request too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        raw = self.handler.rfile.read(length).decode("utf-8", errors="replace") if length else "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise self.error(f"invalid json: {exc}") from exc
        if not isinstance(data, dict):
            raise self.error("json body must be an object")
        return data

    def require_token(self, parsed: Any) -> None:
        query = parse_qs(parsed.query)
        got = self.handler.headers.get("X-Owner-Token") or query.get("token", [None])[0]
        if not got or not secrets.compare_digest(got, self.token()):
            raise self.error("unauthorized", HTTPStatus.UNAUTHORIZED)

    def write_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        accepts_gzip = "gzip" in self.handler.headers.get("Accept-Encoding", "").lower()
        compressed = accepts_gzip and len(body) >= 1024
        if compressed:
            body = gzip.compress(body, compresslevel=6)
        self.handler.send_response(status)
        self.handler.send_header("Content-Type", "application/json; charset=utf-8")
        self.handler.send_header("Cache-Control", "no-store")
        self.handler.send_header("Vary", "Accept-Encoding")
        if compressed:
            self.handler.send_header("Content-Encoding", "gzip")
        self.handler.send_header("Content-Length", str(len(body)))
        self.handler.end_headers()
        try:
            self.handler.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def write_file(self, path: Path, content_type: str, download: bool = False) -> None:
        try:
            size = path.stat().st_size
            handle = path.open("rb")
        except OSError as exc:
            raise self.error("file not found", HTTPStatus.NOT_FOUND) from exc
        with handle:
            self.handler.send_response(HTTPStatus.OK)
            self.handler.send_header("Content-Type", content_type)
            self.handler.send_header("Content-Length", str(size))
            filename = re.sub(r"[^A-Za-z0-9._-]", "_", path.name) or "file"
            disposition = "attachment" if download else "inline"
            self.handler.send_header(
                "Content-Disposition",
                f"{disposition}; filename=\"{filename}\"; filename*=UTF-8''{quote(path.name)}",
            )
            self.handler.send_header("X-Content-Type-Options", "nosniff")
            self.handler.end_headers()
            try:
                shutil.copyfileobj(handle, self.handler.wfile)
            except (BrokenPipeError, ConnectionResetError):
                return
