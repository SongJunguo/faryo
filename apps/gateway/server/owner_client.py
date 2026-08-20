"""Authenticated bounded requests from Gateway to one configured Owner."""

from __future__ import annotations

import http.client
import json
from pathlib import Path
import secrets
from typing import Any, Callable, Mapping


class OwnerClient:
    def __init__(
        self,
        backends: Mapping[str, tuple[str, int, str]],
        config: Any,
        *,
        encode_label: Callable[[str], str],
    ) -> None:
        self.backends = backends
        self.config = config
        self.encode_label = encode_label

    def headers(self, route: str, username: str) -> dict[str, str]:
        host, port, label = self.backends[route]
        headers = {
            "Host": f"{host}:{port}",
            "X-Faryo-Owner-Label": self.encode_label(label),
            "X-Owner-Token": self.config.owner_token(route),
            "X-Faryo-User": username,
        }
        if username != self.config.mcp_user:
            headers["X-Faryo-History-Scope"] = "workspace"
        if file_root := self.config.file_inbox_root(username, route):
            headers["X-Faryo-File-Inbox-Root"] = file_root
        if workspace_root := self.config.workspace_root(username, route):
            headers["X-Faryo-Workspace-Root"] = workspace_root
        return headers

    def json_request(
        self,
        route: str,
        path: str,
        payload: dict[str, Any] | None,
        username: str,
        *,
        method: str = "POST",
        timeout: float = 10,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        host, port, _label = self.backends[route]
        headers = self.headers(route, username)
        body = None
        if extra_headers:
            headers.update({key: value for key, value in extra_headers.items() if value})
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers.update({"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body))})
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
        except (OSError, UnicodeError) as exc:
            return {"ok": False, "error": str(exc), "retryable": True, "transportError": True}
        finally:
            connection.close()
        try:
            result = json.loads(response_body.decode("utf-8"))
        except Exception:
            result = {"ok": False, "error": f"owner returned HTTP {response.status}"}
        if response.status >= 400 and isinstance(result, dict):
            result.update({"ok": False, "httpStatus": response.status})
        return result if isinstance(result, dict) else {"ok": False, "error": "invalid owner response"}

    def attachment_request(self, route: str, path: Path, mime_type: str, filename: str, username: str) -> dict[str, Any]:
        host, port, _label = self.backends[route]
        boundary = "----FaryoBoundary" + secrets.token_hex(12)
        safe_name = Path(filename).name.replace('"', "_").replace("\r", "_").replace("\n", "_") or path.name
        data = path.read_bytes()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
        headers = self.headers(route, username)
        headers.update({"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))})
        connection = http.client.HTTPConnection(host, port, timeout=20)
        try:
            connection.request("POST", "/api/attachment", body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            connection.close()
        try:
            result = json.loads(response_body.decode("utf-8"))
        except Exception:
            result = {"ok": False, "error": f"owner returned HTTP {response.status}"}
        if response.status >= 400 and isinstance(result, dict):
            result.update({"ok": False, "httpStatus": response.status})
        return result if isinstance(result, dict) else {"ok": False, "error": "invalid owner response"}
