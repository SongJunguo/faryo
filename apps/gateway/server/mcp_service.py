"""Stateless MCP JSON-RPC and Faryo handoff tool service."""

from __future__ import annotations

import hmac
import json
from typing import Any


class McpService:
    def __init__(
        self,
        config: Any,
        *,
        protocol_version: str,
        server_version: str,
        tool_name: str,
        tool_schema: dict[str, Any],
    ) -> None:
        self.config = config
        self.protocol_version = protocol_version
        self.server_version = server_version
        self.tool_name = tool_name
        self.tool_schema = tool_schema

    def authorized(self, authorization: str, explicit_token: str) -> bool:
        token = explicit_token.strip()
        auth = authorization.strip()
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        return bool(self.config.mcp_token and token and hmac.compare_digest(token, self.config.mcp_token))

    def cors_origin(self, origin: str) -> str:
        clean = origin.strip()
        return clean if clean and clean == self.config.mcp_cors_origin else ""

    @staticmethod
    def result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def tool_descriptors(self) -> list[dict[str, Any]]:
        return [{
            "name": self.tool_name,
            "title": "Create Faryo handoff package",
            "description": "Create a Faryo Inbox handoff package for cross-session, cross-device, or external workflow transfer. Attachments may be file objects, data_url strings, https URLs, or base64_data; do not pass local sandbox paths such as /mnt/data.",
            "inputSchema": self.tool_schema,
            "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
            "_meta": {
                "openai/fileParams": ["attachment", "attachments", "image", "images"],
                "openai/toolInvocation/invoking": "Creating Faryo handoff package...",
                "openai/toolInvocation/invoked": "Faryo handoff package created.",
            },
        }]

    def response(self, payload: Any, public_base_url: str) -> dict[str, Any] | list[dict[str, Any]] | None:
        if isinstance(payload, list):
            responses = []
            for item in payload:
                response = self.response(item, public_base_url) if isinstance(item, dict) else self.error(None, -32600, "invalid JSON-RPC message")
                if isinstance(response, list):
                    responses.extend(response)
                elif response is not None:
                    responses.append(response)
            return responses or None
        if not isinstance(payload, dict):
            return self.error(None, -32600, "invalid JSON-RPC message")
        request_id = payload.get("id")
        method = str(payload.get("method") or "")
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        if request_id is None:
            return None
        try:
            if method == "initialize":
                return self.result(request_id, {
                    "protocolVersion": str(params.get("protocolVersion") or self.protocol_version),
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "faryo-bridge", "version": self.server_version},
                    "instructions": "Create Faryo handoff packages for cross-session, cross-device, or external workflow transfer.",
                })
            if method == "tools/list":
                return self.result(request_id, {"tools": self.tool_descriptors()})
            if method == "resources/list":
                return self.result(request_id, {"resources": []})
            if method == "resources/read":
                return self.result(request_id, {"contents": []})
            if method == "ping":
                return self.result(request_id, {})
            if method == "tools/call":
                name = str(params.get("name") or "")
                arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
                if name == self.tool_name:
                    return self.result(request_id, self.create_handoff(arguments, public_base_url))
                return self.error(request_id, -32602, f"unknown tool: {name}")
            return self.error(request_id, -32601, f"method not found: {method}")
        except ValueError as exc:
            return self.error(request_id, -32602, str(exc))
        except Exception as exc:
            return self.error(request_id, -32000, str(exc))

    def create_handoff(self, arguments: dict[str, Any], public_base_url: str) -> dict[str, Any]:
        package = self.config.save_bridge_package({
            "title": str(arguments.get("title") or "").strip(),
            "source": "Faryo MCP",
            "intent": str(arguments.get("intent") or "").strip(),
            "context": str(arguments.get("context") or arguments.get("summary") or "").strip(),
            "prompt": str(arguments.get("prompt") or "").strip(),
            "attachment": arguments.get("attachment"),
            "attachments": arguments.get("attachments") if isinstance(arguments.get("attachments"), list) else [],
            "image": arguments.get("image"),
            "images": arguments.get("images") if isinstance(arguments.get("images"), list) else [],
        }, self.config.mcp_user)
        structured = {
            "ok": True,
            "package_id": package["id"],
            "title": package["title"],
            "assets": package["assets"],
            "gateway_url": public_base_url.rstrip("/") + "/",
        }
        return {
            "structuredContent": structured,
            "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
            "_meta": {},
        }
