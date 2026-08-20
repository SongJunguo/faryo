#!/usr/bin/env python3
"""Faryo public gateway with form login and route proxying."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import secrets
import socket
import sys
import time
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

import bcrypt

GATEWAY_MODULE_DIR = Path(__file__).resolve().parent
if str(GATEWAY_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_MODULE_DIR))
import gateway_security
import owner_client
import mcp_service
import workbench_service
import bridge_packages
import gateway_config

SHARED_DIR = Path(__file__).resolve().parents[2] / "shared"
SHARED_STATIC_DIR = SHARED_DIR / "static"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))


def gateway_session_max_age(values: Any) -> int:
    raw = str(values.get("FARYO_GATEWAY_SESSION_HOURS", "720")).strip()
    try:
        hours = int(raw)
    except ValueError as exc:
        raise ValueError("FARYO_GATEWAY_SESSION_HOURS must be an integer from 1 to 720") from exc
    if not 1 <= hours <= 720:
        raise ValueError("FARYO_GATEWAY_SESSION_HOURS must be an integer from 1 to 720")
    return hours * 60 * 60


COOKIE_NAME = "__Host-faryo_auth"
LEGACY_COOKIE_NAME = "faryo_auth"
COOKIE_MAX_AGE = gateway_session_max_age(os.environ)
COOKIE_SAME_SITE = "Strict"
CSRF_HEADER = "X-Faryo-Csrf"
LOGIN_RATE_WINDOW_SECONDS = 10 * 60
LOGIN_RATE_BLOCK_SECONDS = 5 * 60
LOGIN_RATE_MAX_FAILURES = 8
ROUTE_DEFAULTS = {
    "hp": (18766, "Home workstation"),
    "txy": (8765, "Ubuntu 工作站"),
    "pc": (18765, "Windows PC"),
}


def backend_from_values(route: str, default_port: int, default_label: str, values: Any) -> tuple[str, int, str]:
    prefix = f"FARYO_{route.upper()}_OWNER"
    host = str(values.get(f"{prefix}_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    port = int(values.get(f"{prefix}_PORT", str(default_port)))
    label = str(values.get(f"{prefix}_LABEL", default_label)).strip() or default_label
    return host, port, label


def owner_label_header_value(label: str) -> str:
    """Encode a user-facing Unicode label into an HTTP/1.1-safe header value."""
    return quote(label.strip()[:32], safe="-._~")


def configured_routes(values: Any) -> list[str]:
    raw = str(values.get("FARYO_GATEWAY_ROUTES", ",".join(ROUTE_DEFAULTS)))
    requested: list[str] = []
    unknown: list[str] = []
    for item in raw.split(","):
        route = item.strip().lower()
        if not route:
            continue
        if route not in ROUTE_DEFAULTS:
            unknown.append(route)
        elif route not in requested:
            requested.append(route)
    if unknown:
        raise ValueError("unsupported FARYO_GATEWAY_ROUTES: " + ", ".join(unknown))
    if not requested:
        raise ValueError("FARYO_GATEWAY_ROUTES has no valid route")
    return requested


def load_backends(values: Any) -> dict[str, tuple[str, int, str]]:
    backends: dict[str, tuple[str, int, str]] = {}
    for route in configured_routes(values):
        default_port, default_label = ROUTE_DEFAULTS[route]
        backends[route] = backend_from_values(route, default_port, default_label, values)
    return backends


BACKENDS = load_backends(os.environ)
SESSION_MAX_RUNNING_DEFAULTS = {"txy": 8, "hp": 4, "pc": 4}
SESSION_MAX_RUNNING_LIMIT = 32
WORKORDER_RECEIPT_WATCH_INTERVAL_SECONDS = 20
WORKORDER_RECEIPT_WATCH_ATTEMPTS = 90
NEW_SESSION_COMMANDS = {"codex"}
HISTORY_PAGE_SIZE = 10
HISTORY_MAX_FETCH = 1000
HISTORY_QUERY_MAX_CHARS = 96
HISTORY_PERIODS = {"all", "today", "7d", "30d"}
HISTORY_ARCHIVE_FILTERS = {"active", "archived", "all"}
SESSION_STATES = {"starting", "running", "waiting", "exited", "desktop", "resumable", "archived"}
SESSION_STATE_PRIORITY = {"running": 6, "starting": 5, "waiting": 4, "desktop": 3, "exited": 2, "resumable": 1, "archived": 0}
PROXY_CONTROL_ACTIONS = {
    "/api/send": "send",
    "/api/interrupt": "interrupt",
    "/api/approve": "enter",
    "/api/up": "up",
    "/api/down": "down",
    "/api/session/close": "close",
}
DIRECT_CONTROL_ACTIONS = {
    "/api/agent/new": "start",
    "/api/agent/resume": "resume",
    "/api/session-history/archive": "archive",
    "/api/session-history/unarchive": "unarchive",
    "/api/bridge-inject": "file-inject",
    "/api/auth/revoke-all": "revoke-sessions",
}
STATIC_DIR = Path(__file__).resolve().parent / "static"
GATEWAY_STATIC_FILES = {"workbench.css": "text/css; charset=utf-8", "workbench.js": "text/javascript; charset=utf-8"}
BRIDGE_PACKAGE_MAX_BYTES = 120 * 1024 * 1024
BRIDGE_ASSET_MAX_BYTES = 20 * 1024 * 1024
BRIDGE_ASSET_LIMIT = bridge_packages.BRIDGE_ASSET_LIMIT
BRIDGE_PENDING_RETENTION_SECONDS = bridge_packages.BRIDGE_PENDING_RETENTION_SECONDS
BRIDGE_DELIVERED_RETENTION_SECONDS = bridge_packages.BRIDGE_DELIVERED_RETENTION_SECONDS
BRIDGE_CLEANUP_INTERVAL_SECONDS = bridge_packages.BRIDGE_CLEANUP_INTERVAL_SECONDS
BRIDGE_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/rtf": ".rtf",
}
BRIDGE_SUFFIX_MIME = {suffix: mime for mime, suffix in BRIDGE_MIME_EXT.items()}
BRIDGE_SUFFIX_MIME[".jpeg"] = "image/jpeg"
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_SERVER_VERSION = "1.0.6"
MCP_TOOL_NAME = "create_faryo_handoff_package"
MCP_ATTACHMENT_SCHEMA = {"anyOf": [{"type": "object", "additionalProperties": True}, {"type": "string"}]}
MCP_TOOL_SCHEMAS = {MCP_TOOL_NAME: {"type": "object", "properties": {"title": {"type": "string"}, "intent": {"type": "string"}, "context": {"type": "string"}, "prompt": {"type": "string"}, "attachment": MCP_ATTACHMENT_SCHEMA, "attachments": {"type": "array", "items": MCP_ATTACHMENT_SCHEMA}, "image": MCP_ATTACHMENT_SCHEMA, "images": {"type": "array", "items": MCP_ATTACHMENT_SCHEMA}}, "required": ["title", "intent", "context", "prompt"]}}
PWA_MANIFEST = {
    "id": "/",
    "name": "Faryo",
    "short_name": "Faryo",
    "description": "Self-hosted mobile and desktop workbench for Codex sessions",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "theme_color": "#F6F7F9",
    "background_color": "#F6F7F9",
    "icons": [
        {"src": "/icons/pwa-light-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icons/pwa-light-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}
PWA_SW = """self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',(event)=>{event.waitUntil(caches.keys().then((keys)=>Promise.all(keys.map((key)=>caches.delete(key)))).then(()=>self.clients.claim()));});
self.addEventListener('fetch',()=>{});
"""

OWNER_STATIC_FILES = {"appearance.css", "appearance.js", "app.js", "style.css", "index.html", "event-stream.js", "internal-annotations.js", "local-file-view.js", "stable-blocks.js", "question-navigator.js", "live-scroll.js", "compact-rules-codex.js", "codex-commands.js", "copy-fidelity.js", "clipboard-images.js", "immersive-mode.js", "scroll-surface.js"}
OWNER_STATIC_PREFIXES = ("icons/", "pet/", "owner/", "vendor/katex/", "vendor/markdown-ast/", "vendor/diff-review/")
SHARED_STATIC_FILES = {
    "appearance.css": "text/css; charset=utf-8",
    "appearance.js": "text/javascript; charset=utf-8",
}
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
UPSTREAM_SECURITY_HEADERS = {
    "content-security-policy",
    "permissions-policy",
    "referrer-policy",
    "x-content-type-options",
    "x-frame-options",
}
LOGIN_LIMITER = gateway_security.LoginRateLimiter(
    window_seconds=LOGIN_RATE_WINDOW_SECONDS,
    block_seconds=LOGIN_RATE_BLOCK_SECONDS,
    max_failures=LOGIN_RATE_MAX_FAILURES,
)
CSP_NONCE_PLACEHOLDER = "__FARYO_CSP_NONCE__"


def html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def backend_status(route: str, timeout: float = 1.8) -> dict[str, Any]:
    host, port, label = BACKENDS[route]
    started = time.monotonic()
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        resp.read()
        elapsed_ms = round((time.monotonic() - started) * 1000)
    except OSError:
        return {
            "id": route,
            "label": label,
            "state": "offline",
            "stateText": "Off",
            "detail": "Owner backend is unreachable",
        }
    finally:
        try:
            conn.close()  # type: ignore[possibly-undefined]
        except Exception:
            pass
    if resp.status == 200:
        state = "slow" if elapsed_ms > 1500 else "online"
        return {
            "id": route,
            "label": label,
            "state": state,
            "stateText": f"{elapsed_ms}ms",
            "detail": f"{elapsed_ms} ms",
        }
    return {
        "id": route,
        "label": label,
        "state": "error",
        "stateText": f"E{resp.status}",
        "detail": f"health {resp.status}",
    }


def now_ts() -> int:
    return int(time.time())


def parse_updated_ts(value: Any) -> float:
    if isinstance(value, (int, float)): return float(value)
    try: return float(str(value or "").strip())
    except ValueError: pass
    try: return time.mktime(time.strptime(str(value).replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z"))
    except ValueError: return 0.0


def display_updated_at(value: Any) -> str:
    ts = parse_updated_ts(value)
    if ts <= 0: return str(value or "")
    local = time.localtime(ts)
    fmt = "%H:%M" if time.strftime("%Y-%m-%d", local) == time.strftime("%Y-%m-%d", time.localtime()) else "%m-%d %H:%M"
    return time.strftime(fmt, local)


def compact_path_label(value: Any) -> str:
    text = str(value or "").replace("\\", "/").rstrip("/")
    return text.split("/")[-1] if text and text != "~" else text


def display_session_title(value: Any) -> str:
    return " ".join(str(value or "").replace("\r", "\n").split()) or "Untitled session"


def normalize_history_filters(values: dict[str, Any] | None = None) -> dict[str, str]:
    raw = values or {}
    query = " ".join(str(raw.get("q") or "").replace("\x00", "").split())[:HISTORY_QUERY_MAX_CHARS]
    period = str(raw.get("period") or "all").strip().lower()
    archive = str(raw.get("archive") or "active").strip().lower()
    return {
        "q": query,
        "period": period if period in HISTORY_PERIODS else "all",
        "archive": archive if archive in HISTORY_ARCHIVE_FILTERS else "active",
    }


def history_filters_from_query(query: dict[str, list[str]]) -> dict[str, str]:
    return normalize_history_filters({
        "q": query.get("q", [""])[0],
        "period": query.get("period", ["all"])[0],
        "archive": query.get("archive", ["active"])[0],
    })


def owner_history_query(limit: int, offset: int, filters: dict[str, Any] | None = None) -> str:
    applied = normalize_history_filters(filters)
    params: list[tuple[str, str]] = [
        ("view", "split"),
        ("limit", str(limit)),
        ("offset", str(offset)),
    ]
    if applied["q"]:
        params.append(("q", applied["q"]))
    if applied["period"] != "all":
        params.append(("period", applied["period"]))
    if applied["archive"] != "active":
        params.append(("archive", applied["archive"]))
    return "/api/agent-sessions?" + urlencode(params)


def control_target_from_json(raw: bytes | None) -> str:
    if not raw:
        return ""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("session", "agent_session_id", "agentSessionId", "client_launch_id", "clientLaunchId", "package_id", "packageId"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value[:160]
    return ""


def clean_session_title(value: Any) -> str:
    return display_session_title(value)[:48]

def clean_re(value: str | None, pattern: str) -> str | None:
    value = (value or "").strip(); return value if re.fullmatch(pattern, value) else None


def clean_package_id(value: str | None) -> str | None: return clean_re(value, r"[0-9]+-[a-f0-9]{8}")
def clean_session_id(value: str | None) -> str | None: return clean_re(value, r"[A-Za-z0-9_.:-]{1,80}")
def clean_agent_session_id(value: str | None) -> str | None: return clean_re(value, r"[A-Za-z0-9_.:-]{1,120}")
def clean_client_launch_id(value: str | None) -> str | None: return clean_re(value, r"[A-Za-z0-9_.:-]{8,128}")
def clean_agent_launch_command(value: str | None) -> str | None:
    command = Path(str(value or "").strip()).name.lower()
    return command if command in NEW_SESSION_COMMANDS else None


def equivalent_owner_path(value: str, other: str) -> bool:
    left = str(value or "").strip().rstrip("/")
    right = str(other or "").strip().rstrip("/")
    if not left or not right:
        return False
    return left == right or (left.startswith("~/") and right.endswith(left[1:])) or (right.startswith("~/") and left.endswith(right[1:]))


def agent_cwd_choices(sessions: list[dict[str, Any]], workspace_root: str | None, limit: int = 8) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    root = str(workspace_root or "").strip().rstrip("/")
    for item in sorted(sessions, key=lambda entry: float(entry.get("updatedTs") or 0), reverse=True):
        cwd = str(item.get("cwd") or "").strip().rstrip("/")
        if not cwd or cwd == "~" or any(equivalent_owner_path(cwd, choice["value"]) for choice in choices):
            continue
        choices.append({
            "value": cwd,
            "label": compact_path_label(cwd) or cwd,
            "path": cwd,
            "kind": "workspace" if root and equivalent_owner_path(cwd, root) else "recent",
        })
        if len(choices) >= max(1, limit):
            break
    if root and not any(equivalent_owner_path(root, choice["value"]) for choice in choices):
        choices.append({"value": root, "label": compact_path_label(root) or root, "path": root, "kind": "workspace"})
    return choices


def owner_directory_selection_token(owner_token: str, path: str) -> str:
    return hmac.new(owner_token.encode("utf-8"), f"cwd:{path}".encode("utf-8"), hashlib.sha256).hexdigest()


def select_recent_agent_cwd(sessions: list[dict[str, Any]], workspace_root: str | None) -> str:
    return next((choice["value"] for choice in agent_cwd_choices(sessions, workspace_root) if choice["kind"] == "recent"), "")


def blocked_asset_ip(ip: Any) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def blocked_asset_host(hostname: str | None) -> bool:
    host = (hostname or "").strip().lower()
    if not host or host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        return blocked_asset_ip(ip)
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return True
    for info in infos:
        try:
            resolved_ip = ipaddress.ip_address(info[4][0])
        except (IndexError, ValueError):
            return True
        if blocked_asset_ip(resolved_ip):
            return True
    return False


def normalize_bridge_asset_payload(value: Any) -> dict[str, str] | None:
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("data:"): return {"data_url": raw, "base64_data": "", "asset_url": "", "mime_type": "application/octet-stream", "file_name": "faryo-attachment"}
        if raw.startswith("https://"): return {"data_url": "", "base64_data": "", "asset_url": raw, "mime_type": "application/octet-stream", "file_name": Path(urlparse(raw).path).name or "faryo-attachment"}
        if len(raw) > 100 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", raw): return {"data_url": "", "base64_data": raw, "asset_url": "", "mime_type": "image/png", "file_name": "faryo-image.png"}
        return None
    if not isinstance(value, dict): return None
    data_url = str(value.get("data_url") or value.get("dataUrl") or "").strip(); base64_data = str(value.get("base64_data") or value.get("base64Data") or value.get("b64_json") or "").strip()
    raw_data = value.get("data") or value.get("content")
    if isinstance(raw_data, str) and not data_url and not base64_data:
        if raw_data.strip().startswith("data:"): data_url = raw_data.strip()
        else: base64_data = raw_data.strip()
    asset_url = str(value.get("asset_url") or value.get("assetUrl") or value.get("image_url") or value.get("imageUrl") or value.get("url") or value.get("download_url") or value.get("downloadUrl") or "").strip()
    if not data_url and not base64_data and not asset_url: return None
    mime_type = str(value.get("mime_type") or value.get("mimeType") or value.get("type") or "application/octet-stream").split(";", 1)[0].strip().lower()
    file_name = Path(str(value.get("file_name") or value.get("fileName") or value.get("name") or "faryo-attachment")).name
    return {"data_url": data_url, "base64_data": base64_data, "asset_url": asset_url, "mime_type": mime_type, "file_name": file_name}


def bridge_mime_type(mime_type: str, file_name: str) -> str:
    mime_type = (mime_type or "application/octet-stream").strip().lower()
    suffix = Path(file_name or "").suffix.lower()
    if mime_type in BRIDGE_MIME_EXT:
        return mime_type
    if suffix in BRIDGE_SUFFIX_MIME:
        return BRIDGE_SUFFIX_MIME[suffix]
    return mime_type


def bridge_asset_bytes_from_payload(asset: dict[str, str]) -> tuple[str, bytes]:
    mime_type = bridge_mime_type(asset.get("mime_type") or "", asset.get("file_name") or "")
    if asset.get("data_url"):
        header, sep, payload = asset["data_url"].partition(",")
        if not sep or ";base64" not in header: raise ValueError("invalid attachment data_url")
        mime_type = (header.removeprefix("data:").split(";", 1)[0] or mime_type).strip().lower(); data = base64.b64decode(payload, validate=True)
        mime_type = bridge_mime_type(mime_type, asset.get("file_name") or "")
    elif asset.get("base64_data"):
        data = base64.b64decode(asset.get("base64_data") or "", validate=True)
    else:
        parsed = urlparse(asset.get("asset_url") or "")
        if parsed.scheme != "https": raise ValueError("attachment url must be https")
        if blocked_asset_host(parsed.hostname): raise ValueError("attachment url host is not allowed")
        with urllib.request.urlopen(urllib.request.Request(parsed.geturl(), headers={"User-Agent": "Faryo-Bridge/0.1"}), timeout=8) as resp:
            mime_type = (resp.headers.get_content_type() or mime_type).strip().lower(); data = resp.read(BRIDGE_ASSET_MAX_BYTES + 1)
        mime_type = bridge_mime_type(mime_type, asset.get("file_name") or Path(parsed.path).name)
    if mime_type not in BRIDGE_MIME_EXT: raise ValueError(f"unsupported attachment type: {mime_type or 'unknown'}")
    if len(data) > BRIDGE_ASSET_MAX_BYTES: raise ValueError("attachment is too large")
    return mime_type, data


def bridge_prompt_text(package: dict[str, Any]) -> str:
    parts = ["# Faryo Handoff Package", f"Title: {package.get('title') or 'Untitled handoff'}", f"Source: {package.get('source') or 'Faryo'}", "", "## Intent", str(package.get("intent") or ""), "", "## Context", str(package.get("context") or ""), "", "## Request", str(package.get("prompt") or "")]
    assets = package.get("assets") if isinstance(package.get("assets"), list) else []
    if assets: parts.extend(["", "## Attachments"] + [f"- {asset.get('file_name')}: {asset.get('path')}" for asset in assets if isinstance(asset, dict)])
    return "\n".join(parts).strip() + "\n"


GATEWAY_CONFIG_RUNTIME = gateway_config.GatewayConfigRuntime(
    backends=BACKENDS,
    load_backends=load_backends,
    route_max_defaults=SESSION_MAX_RUNNING_DEFAULTS,
    route_max_limit=SESSION_MAX_RUNNING_LIMIT,
    clean_package_id=clean_package_id,
    normalize_bridge_asset=normalize_bridge_asset_payload,
    bridge_asset_bytes=bridge_asset_bytes_from_payload,
    bridge_mime_extensions=BRIDGE_MIME_EXT,
    now_ts=now_ts,
)


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class GatewayConfig(gateway_config.GatewayConfig):
    def __init__(self, auth_config: Path, owner_env: Path, portal_dir: Path, secret_file: Path) -> None:
        super().__init__(auth_config, owner_env, portal_dir, secret_file, GATEWAY_CONFIG_RUNTIME)


class WorkbenchRuntime:
    BACKENDS = BACKENDS
    SESSION_STATES = SESSION_STATES
    SESSION_STATE_PRIORITY = SESSION_STATE_PRIORITY
    HISTORY_PAGE_SIZE = HISTORY_PAGE_SIZE
    HISTORY_MAX_FETCH = HISTORY_MAX_FETCH
    NEW_SESSION_COMMANDS = NEW_SESSION_COMMANDS
    display_session_title = staticmethod(display_session_title)
    compact_path_label = staticmethod(compact_path_label)
    display_updated_at = staticmethod(display_updated_at)
    parse_updated_ts = staticmethod(parse_updated_ts)
    owner_history_query = staticmethod(owner_history_query)
    normalize_history_filters = staticmethod(normalize_history_filters)
    backend_status = staticmethod(backend_status)
    agent_cwd_choices = staticmethod(agent_cwd_choices)
    now_ts = staticmethod(now_ts)


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "FaryoGateway/0.1"

    @property
    def config(self) -> GatewayConfig:
        return self.server.config  # type: ignore[attr-defined]

    def begin_control_audit(self, username: str, route: str, action: str) -> None:
        self._control_audit = {
            "username": username,
            "route": route,
            "action": action,
            "target": "",
            "requestId": secrets.token_hex(8),
            "started": time.monotonic(),
            "idempotent": False,
            "done": False,
        }

    def set_control_audit_target(self, target: str, *, route: str | None = None, idempotent: bool | None = None) -> None:
        context = getattr(self, "_control_audit", None)
        if not isinstance(context, dict) or context.get("done"):
            return
        if target:
            context["target"] = str(target)[:160]
        if route is not None:
            clean_route = str(route).strip().lower()
            context["route"] = clean_route if clean_route in BACKENDS else ""
        if idempotent is not None:
            context["idempotent"] = bool(idempotent)

    def complete_control_audit(self, status: int) -> None:
        context = getattr(self, "_control_audit", None)
        if not isinstance(context, dict) or context.get("done"):
            return
        context["done"] = True
        writer = getattr(self.config, "append_control_audit", None)
        if not callable(writer):
            return
        try:
            writer(
                username=str(context.get("username") or ""),
                route=str(context.get("route") or ""),
                action=str(context.get("action") or ""),
                target=str(context.get("target") or ""),
                request_id=str(context.get("requestId") or ""),
                status=int(status),
                duration_ms=round((time.monotonic() - float(context.get("started") or time.monotonic())) * 1000),
                idempotent=bool(context.get("idempotent")),
            )
        except Exception:
            return

    def send_response(self, code: int, message: str | None = None) -> None:
        super().send_response(code, message)
        self.complete_control_audit(int(code))

    def log_message(self, fmt: str, *args: Any) -> None:
        safe_path = self.path.split("?", 1)[0]
        print("[%s] %s %s" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), self.command, safe_path), flush=True)

    def end_headers(self) -> None:
        nonce = getattr(self, "_csp_nonce", "")
        audit = getattr(self, "_control_audit", None)
        if isinstance(audit, dict) and audit.get("requestId"):
            self.send_header("X-Faryo-Request-Id", str(audit["requestId"]))
        for name, value in gateway_security.browser_security_headers(nonce).items():
            self.send_header(name, value)
        super().end_headers()

    def do_OPTIONS(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/mcp":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_mcp_cors_headers()
            self.send_header("Access-Control-Allow-Headers", "authorization, content-type, mcp-protocol-version, mcp-session-id, x-faryo-mcp-token")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/mcp":
            self.handle_mcp_get(parsed)
            return
        self.send_error(HTTPStatus.NOT_IMPLEMENTED, "Unsupported method ('DELETE')")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/manifest.json":
            self.write_json(PWA_MANIFEST, HTTPStatus.OK)
            return
        if parsed.path == "/sw.js":
            self.write_asset(PWA_SW.encode("utf-8"), "text/javascript; charset=utf-8", "no-store")
            return
        if parsed.path.startswith("/icons/"):
            self.write_icon(parsed.path.rsplit("/", 1)[-1])
            return
        if parsed.path.lstrip("/") in GATEWAY_STATIC_FILES:
            filename = parsed.path.lstrip("/")
            self.write_asset((STATIC_DIR / filename).read_bytes(), GATEWAY_STATIC_FILES[filename], "no-store")
            return
        if parsed.path.lstrip("/") in SHARED_STATIC_FILES:
            filename = parsed.path.lstrip("/")
            self.write_asset((SHARED_STATIC_DIR / filename).read_bytes(), SHARED_STATIC_FILES[filename], "no-store")
            return
        if parsed.path == "/mcp":
            self.handle_mcp_get(parsed)
            return
        username = self.current_username()
        if parsed.path == "/login":
            if username:
                self.redirect(self.safe_next(parsed))
                return
            self.write_login_page(self.safe_next(parsed))
            return
        if parsed.path == "/favicon.ico":
            self.write_icon("favicon.ico")
            return
        if parsed.path == "/logout":
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Set-Cookie", self.expired_cookie())
            self.send_header("Set-Cookie", self.expired_cookie(LEGACY_COOKIE_NAME))
            self.send_header("Location", "/login")
            self.end_headers()
            return
        if not username and self.is_api_path(parsed.path):
            self.write_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        if not username:
            self.redirect("/login?" + urlencode({"next": self.request_target()}))
            return
        if parsed.path == "/api/csrf":
            self.write_json({"ok": True, "csrf": self.csrf_token(username)}, HTTPStatus.OK)
            return
        if parsed.path == "/api/security-activity":
            try:
                limit = int(parse_qs(parsed.query).get("limit", ["30"])[0])
            except ValueError:
                limit = 30
            self.write_json({"ok": True, "entries": self.config.control_activity(username, limit)}, HTTPStatus.OK)
            return
        if parsed.path == "/api/gateway-status":
            routes = self.config.user_routes(username)
            self.write_json({"ok": True, "entries": [backend_status(route) for route in routes]}, HTTPStatus.OK)
            return
        if parsed.path == "/api/workbench":
            query = parse_qs(parsed.query)
            try:
                history_page = max(1, int(query.get("page", ["1"])[0]))
            except ValueError:
                history_page = 1
            self.write_json(self.workbench_payload(username, history_page, history_filters_from_query(query)), HTTPStatus.OK)
            return
        if parsed.path == "/api/bridge-packages":
            self.write_json({"ok": True, "packages": self.config.list_bridge_packages(username)}, HTTPStatus.OK)
            return
        if parsed.path.startswith("/bridge/packages/"):
            self.write_bridge_package_asset(parsed.path, username)
            return
        if parsed.path == "/password":
            self.write_password_page()
            return
        route = self.route_for(parsed)
        if route:
            self.proxy(parsed, route, username)
            return
        if parsed.path == "/":
            self.serve_portal(username)
            return
        self.write_not_found(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/mcp":
            self.handle_mcp_post(parsed)
            return
        if parsed.path == "/login":
            self.handle_login(parsed)
            return
        username = self.current_username()
        if not username:
            self.write_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        route = self.route_for(parsed)
        if route and route[1] in PROXY_CONTROL_ACTIONS:
            self.begin_control_audit(username, route[0], PROXY_CONTROL_ACTIONS[route[1]])
        elif parsed.path in DIRECT_CONTROL_ACTIONS:
            self.begin_control_audit(username, "", DIRECT_CONTROL_ACTIONS[parsed.path])
        if route:
            if not self.require_csrf_header(username):
                return
            self.proxy(parsed, route, username)
            return
        if parsed.path == "/password":
            self.handle_password_change(username)
            return
        if not self.require_csrf_header(username):
            return
        if parsed.path == "/api/auth/revoke-all":
            self.handle_revoke_sessions(username)
            return
        if parsed.path == "/api/session-history/archive":
            self.handle_session_history_lifecycle(username, True)
            return
        if parsed.path == "/api/session-history/unarchive":
            self.handle_session_history_lifecycle(username, False)
            return
        if parsed.path == "/api/bridge-packages":
            self.handle_bridge_package_create(username)
            return
        if parsed.path == "/api/bridge-package-assets":
            self.handle_bridge_package_assets(username)
            return
        if parsed.path == "/api/bridge-inject":
            self.handle_bridge_inject(username)
            return
        if parsed.path == "/api/agent/new":
            self.handle_agent_new(username)
            return
        if parsed.path == "/api/agent/resume":
            self.handle_agent_resume(username)
            return
        self.write_not_found(parsed.path)

    def handle_mcp_get(self, parsed: Any) -> None:
        if not self.require_mcp_token():
            return
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED); self.send_mcp_cors_headers(); self.send_header("Allow", "POST, OPTIONS"); self.send_header("Cache-Control", "no-store"); self.end_headers()

    def handle_mcp_post(self, parsed: Any) -> None:
        if not self.require_mcp_token():
            return
        try: payload = self.read_json_payload(BRIDGE_PACKAGE_MAX_BYTES)
        except ValueError as exc: self.write_mcp_json(self.mcp_error(None, -32700, str(exc)), HTTPStatus.BAD_REQUEST); return
        try: response = self.mcp_response(payload)
        except ValueError as exc: self.write_mcp_json(self.mcp_error(None, -32700, str(exc)), HTTPStatus.BAD_REQUEST); return
        if response is None: self.send_response(HTTPStatus.ACCEPTED); self.send_mcp_cors_headers(); self.end_headers(); return
        self.write_mcp_json(response)

    def mcp_response(self, payload: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        return self.shared_mcp_service().response(payload, self.public_base_url())

    def shared_mcp_service(self) -> mcp_service.McpService:
        return mcp_service.McpService(
            self.config,
            protocol_version=MCP_PROTOCOL_VERSION,
            server_version=MCP_SERVER_VERSION,
            tool_name=MCP_TOOL_NAME,
            tool_schema=MCP_TOOL_SCHEMAS[MCP_TOOL_NAME],
        )

    def mcp_result(self, request_id: Any, result: dict[str, Any]) -> dict[str, Any]: return self.shared_mcp_service().result(request_id, result)
    def mcp_error(self, request_id: Any, code: int, message: str) -> dict[str, Any]: return self.shared_mcp_service().error(request_id, code, message)

    def mcp_tool_descriptors(self) -> list[dict[str, Any]]:
        return self.shared_mcp_service().tool_descriptors()

    def mcp_create_handoff(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.shared_mcp_service().create_handoff(arguments, self.public_base_url())

    def public_base_url(self) -> str:
        return f"{self.headers.get('X-Forwarded-Proto') or 'https'}://{self.headers.get('X-Forwarded-Host') or self.headers.get('Host') or ''}".rstrip("/")

    def mcp_cors_allowed(self) -> str:
        return self.shared_mcp_service().cors_origin(self.headers.get("Origin", ""))

    def send_mcp_cors_headers(self) -> None:
        origin = self.mcp_cors_allowed()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def write_mcp_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8"); self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_mcp_cors_headers(); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.write_bytes(body)

    def require_mcp_token(self) -> bool:
        if not self.config.mcp_token:
            self.write_mcp_json(self.mcp_error(None, -32001, "mcp disabled"), HTTPStatus.NOT_FOUND)
            return False
        if self.shared_mcp_service().authorized(
            self.headers.get("Authorization", ""),
            self.headers.get("X-Faryo-Mcp-Token", ""),
        ):
            return True
        self.write_mcp_json(self.mcp_error(None, -32001, "unauthorized"), HTTPStatus.UNAUTHORIZED)
        return False

    def csrf_token(self, username: str) -> str:
        return gateway_security.csrf_token(self.config.cookie_secret, username, self.config.auth_epoch(username))

    def require_csrf_header(self, username: str) -> bool:
        token = self.headers.get(CSRF_HEADER, "").strip()
        if token and hmac.compare_digest(token, self.csrf_token(username)):
            return True
        self.write_json({"ok": False, "error": "csrf required"}, HTTPStatus.FORBIDDEN)
        return False

    def login_rate_key(self) -> str:
        return gateway_security.login_rate_key(str(self.client_address[0]), self.headers.get("CF-Connecting-IP", ""))

    def login_rate_limited(self, key: str) -> bool:
        return LOGIN_LIMITER.limited(key)

    def record_login_failure(self, key: str) -> None:
        LOGIN_LIMITER.record_failure(key)

    def clear_login_rate(self, key: str) -> None:
        LOGIN_LIMITER.clear(key)

    def handle_login(self, parsed: Any) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(min(length, 8192)).decode("utf-8", errors="replace")
        form = parse_qs(raw)
        username = form.get("username", [""])[0].strip()
        password = form.get("password", [""])[0]
        next_target = form.get("next", [self.safe_next(parsed)])[0] or "/"
        rate_key = self.login_rate_key()
        user = self.config.user(username)
        ok = not self.login_rate_limited(rate_key) and bool(user) and bcrypt.checkpw(password.encode("utf-8"), self.config.password_hash(username))
        if not ok:
            self.record_login_failure(rate_key)
            self.write_login_page(self.safe_target(next_target), error="Invalid username or password")
            return
        self.clear_login_rate(rate_key)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Set-Cookie", self.auth_cookie(username))
        self.send_header("Set-Cookie", self.expired_cookie(LEGACY_COOKIE_NAME))
        self.send_header("Location", self.safe_target(next_target))
        self.end_headers()

    def handle_password_change(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(min(length, 8192)).decode("utf-8", errors="replace")
        form = parse_qs(raw)
        current = form.get("current_password", [""])[0]
        new_password = form.get("new_password", [""])[0]
        confirm = form.get("confirm_password", [""])[0]
        if not hmac.compare_digest(form.get("csrf", [""])[0], self.csrf_token(username)):
            self.write_password_page(error="Reload and try again")
            return
        if not bcrypt.checkpw(current.encode("utf-8"), self.config.password_hash(username)):
            self.write_password_page(error="Current password is incorrect")
            return
        if len(new_password) < 16:
            self.write_password_page(error="New password must be at least 16 characters")
            return
        if new_password != confirm:
            self.write_password_page(error="New password confirmation does not match")
            return
        self.config.set_password(username, new_password)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Set-Cookie", self.auth_cookie(username))
        self.send_header("Set-Cookie", self.expired_cookie(LEGACY_COOKIE_NAME))
        self.send_header("Location", "/?password=changed")
        self.end_headers()

    def handle_revoke_sessions(self, username: str) -> None:
        try:
            payload = self.read_json_body(4096)
            if payload.get("confirm") != "revoke":
                raise ValueError("explicit revoke confirmation is required")
            self.set_control_audit_target(username)
            self.config.revoke_sessions(username)
            self.write_json({"ok": True, "signedOut": True}, HTTPStatus.OK)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)


    def read_json_body(self, max_bytes: int = BRIDGE_PACKAGE_MAX_BYTES) -> dict[str, Any]:
        payload = self.read_json_payload(max_bytes)
        if not isinstance(payload, dict): raise ValueError("invalid JSON object")
        return payload

    def read_json_payload(self, max_bytes: int = BRIDGE_PACKAGE_MAX_BYTES) -> Any:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0: raise ValueError("empty JSON body")
        if length > max_bytes: raise ValueError("request too large")
        try: return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc: raise ValueError("invalid JSON body") from exc

    def handle_bridge_package_create(self, username: str) -> None:
        try: self.write_json({"ok": True, "package": self.config.save_bridge_package(self.read_json_body(), username)}, HTTPStatus.OK)
        except ValueError as exc: self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_bridge_package_assets(self, username: str) -> None:
        try:
            payload = self.read_json_body(); assets = self.config.bridge_asset_sources(payload); package_id = str(payload.get("package_id") or payload.get("packageId") or "")
            self.write_json({"ok": True, "package": self.config.append_bridge_package_assets(package_id, assets, username)}, HTTPStatus.OK)
        except ValueError as exc: self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_bridge_inject(self, username: str) -> None:
        try:
            payload = self.read_json_body(65536); package_id = clean_package_id(str(payload.get("package_id") or payload.get("packageId") or "")); route = str(payload.get("route") or "").strip(); session = clean_session_id(str(payload.get("session") or "")); agent_session_id = clean_agent_session_id(str(payload.get("agent_session_id") or "")); source = str(payload.get("source") or "")
            self.set_control_audit_target(session or agent_session_id or package_id or "", route=route)
            if not package_id or route not in BACKENDS or (not session and not agent_session_id): raise ValueError("package_id, route and session or agent_session_id are required")
            if agent_session_id and not source: raise ValueError("source is required with agent_session_id")
            if not self.config.allowed_route(username, route): self.write_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN); return
            package = self.config.bridge_package(package_id, username)
            if not package: self.write_json({"ok": False, "error": "package not found"}, HTTPStatus.NOT_FOUND); return
            target_session = session
            if not target_session:
                resume_response = self.owner_json_request(route, "/api/agent/resume", {"agent_session_id": agent_session_id, "source": source, "max_running": self.max_running_for(username, route)}, username)
                if not resume_response.get("ok"): self.write_json({"ok": False, "error": resume_response.get("error") or "owner resume failed"}, HTTPStatus.BAD_GATEWAY); return
                target_session = clean_session_id(str(resume_response.get("session") or ""))
                if not target_session: self.write_json({"ok": False, "error": "owner did not return target session"}, HTTPStatus.BAD_GATEWAY); return
            target_package = self.package_for_owner(route, package, username)
            response = self.owner_json_request(route, "/api/send", {"session": target_session, "text": bridge_prompt_text(target_package)}, username)
            if not response.get("ok"): self.write_json({"ok": False, "error": response.get("error") or "owner inject failed"}, HTTPStatus.BAD_GATEWAY); return
            package["status"] = "injected"; package["target"] = {"route": route, "session": target_session, "agentSessionId": agent_session_id or "", "source": source}; self.config.update_bridge_package(package)
            self.write_json({"ok": True, "redirect": f"/{route}/?session={target_session}", "package": package}, HTTPStatus.OK)
        except ValueError as exc: self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def package_for_owner(self, route: str, package: dict[str, Any], username: str) -> dict[str, Any]:
        assets = package.get("assets") if isinstance(package.get("assets"), list) else []
        if not assets:
            return package
        delivered = []
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            delivered.append(self.upload_bridge_asset(route, asset, username))
        target_package = dict(package)
        target_package["assets"] = delivered
        return target_package

    def upload_bridge_asset(self, route: str, asset: dict[str, Any], username: str) -> dict[str, Any]:
        path = Path(str(asset.get("path") or ""))
        if not path.is_file() or self.config.bridge_root not in path.resolve().parents:
            raise ValueError("bridge asset is missing")
        result = self.owner_attachment_request(route, path, str(asset.get("mime_type") or "application/octet-stream"), str(asset.get("file_name") or path.name), username)
        owner_path = str(result.get("path") or "")
        if not result.get("ok") or not owner_path:
            raise ValueError(str(result.get("error") or "owner attachment upload failed"))
        delivered = dict(asset)
        delivered["source_path"] = str(path)
        delivered["path"] = owner_path
        delivered["owner_path"] = owner_path
        return delivered

    def handle_session_history_lifecycle(self, username: str, archived: bool) -> None:
        try:
            payload = self.read_json_body(4096)
            route = str(payload.get("route") or "").strip().lower()
            agent_session_id = clean_agent_session_id(str(payload.get("agent_session_id") or payload.get("agentSessionId") or ""))
            self.set_control_audit_target(agent_session_id or "", route=route)
            if route not in BACKENDS or not agent_session_id:
                raise ValueError("route and agent_session_id are required")
            if not self.config.allowed_route(username, route):
                self.write_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            action = "archive" if archived else "unarchive"
            response = self.owner_json_request(
                route,
                f"/api/agent-session/{action}",
                {"agent_session_id": agent_session_id},
                username,
                timeout=10,
            )
            if not response.get("ok"):
                raw_status = int(response.get("httpStatus") or HTTPStatus.BAD_GATEWAY)
                try:
                    status = HTTPStatus(raw_status)
                except ValueError:
                    status = HTTPStatus.BAD_GATEWAY
                self.write_json({"ok": False, "error": str(response.get("error") or f"owner {action} failed")}, status)
                return
            self.set_control_audit_target(agent_session_id, idempotent=bool(response.get("duplicate")))
            self.write_json({
                "ok": True,
                "agentSessionId": agent_session_id,
                "archived": bool(response.get("archived")),
                "duplicate": bool(response.get("duplicate")),
            }, HTTPStatus.OK)
        except (TypeError, ValueError) as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_agent_resume(self, username: str) -> None:
        try:
            payload = self.read_json_body(65536); route = str(payload.get("route") or "").strip(); agent_session_id = clean_agent_session_id(str(payload.get("agent_session_id") or "")); source = str(payload.get("source") or "")
            self.set_control_audit_target(agent_session_id or "", route=route)
            if route not in BACKENDS or not agent_session_id or not source: raise ValueError("route, agent_session_id and source are required")
            if not self.config.allowed_route(username, route): self.write_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN); return
            response = self.owner_json_request(route, "/api/agent/resume", {"agent_session_id": agent_session_id, "source": source, "max_running": self.max_running_for(username, route)}, username, timeout=20)
            target_session = clean_session_id(str(response.get("session") or "")) if response.get("ok") else ""
            if not target_session: self.write_json({"ok": False, "error": response.get("error") or "owner resume failed"}, HTTPStatus.BAD_GATEWAY); return
            self.write_json({"ok": True, "redirect": f"/{route}/?session={target_session}", "session": target_session}, HTTPStatus.OK)
        except ValueError as exc: self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_agent_new(self, username: str) -> None:
        try:
            payload = self.read_json_body(4096); route = str(payload.get("route") or "").strip(); command = clean_agent_launch_command(str(payload.get("command") or "")); requested_cwd = str(payload.get("cwd") or "").strip().rstrip("/"); cwd_token = str(payload.get("cwd_token") or payload.get("cwdToken") or "").strip(); raw_launch_id = str(payload.get("client_launch_id") or payload.get("clientLaunchId") or "").strip(); launch_id = clean_client_launch_id(raw_launch_id)
            self.set_control_audit_target(launch_id or "", route=route)
            if route not in BACKENDS or not command: raise ValueError("route and command are required")
            if raw_launch_id and not launch_id: raise ValueError("invalid client launch id")
            if not self.config.allowed_route(username, route): self.write_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN); return
            if username != self.config.mcp_user and command != "codex": self.write_json({"ok": False, "error": "forbidden command"}, HTTPStatus.FORBIDDEN); return
            launch = {"command": command, "max_running": self.max_running_for(username, route), **({"client_launch_id": launch_id} if launch_id else {})}
            recent = self.owner_agent_sessions(route, username)
            recent_sessions = [*recent["activeSessions"], *recent["sessions"]]
            if requested_cwd:
                expected_cwd_token = owner_directory_selection_token(self.config.owner_token(route), requested_cwd)
                if not cwd_token or not hmac.compare_digest(cwd_token, expected_cwd_token):
                    raise ValueError("working directory selection is invalid or expired")
            selected_cwd = requested_cwd or select_recent_agent_cwd(recent_sessions, self.config.workspace_root(username, route))
            selected_launch = {**launch, "cwd": selected_cwd, "cwd_token": cwd_token} if selected_cwd else launch
            response = self.owner_json_request(route, "/api/agent/new", selected_launch, username, timeout=20)
            if launch_id and response.get("transportError"):
                time.sleep(0.25)
                response = self.owner_json_request(route, "/api/agent/new", selected_launch, username, timeout=20)
            if selected_cwd and not requested_cwd and not response.get("ok"):
                response = self.owner_json_request(route, "/api/agent/new", launch, username, timeout=20)
            target_session = clean_session_id(str(response.get("session") or "")) if response.get("ok") else ""
            if target_session:
                self.set_control_audit_target(target_session, idempotent=bool(response.get("duplicate")))
            if not target_session: self.write_json({"ok": False, "error": response.get("error") or "owner new session failed"}, HTTPStatus.BAD_GATEWAY); return
            self.write_json({"ok": True, "redirect": f"/{route}/?session={target_session}", "session": target_session}, HTTPStatus.OK)
        except ValueError as exc: self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def owner_headers(self, route: str, username: str) -> dict[str, str]:
        return owner_client.OwnerClient(BACKENDS, self.config, encode_label=owner_label_header_value).headers(route, username)

    def owner_json_request(self, route: str, path: str, payload: dict[str, Any] | None, username: str, method: str = "POST", timeout: float = 10, extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
        client = owner_client.OwnerClient(BACKENDS, self.config, encode_label=owner_label_header_value)
        return client.json_request(route, path, payload, username, method=method, timeout=timeout, extra_headers=extra_headers)

    def owner_attachment_request(self, route: str, path: Path, mime_type: str, filename: str, username: str) -> dict[str, Any]:
        client = owner_client.OwnerClient(BACKENDS, self.config, encode_label=owner_label_header_value)
        return client.attachment_request(route, path, mime_type, filename, username)

    def max_running_for(self, username: str, route: str) -> int:
        return self.config.max_running(route)

    def shared_workbench_service(self) -> workbench_service.WorkbenchService:
        server = getattr(self, "server", None)
        config = getattr(server, "config", None)
        return workbench_service.WorkbenchService(
            WorkbenchRuntime,
            config,
            self,
            owner_json_request_callback=self.owner_json_request,
            owner_sessions_callback=self.owner_agent_sessions,
            max_running_callback=self.max_running_for,
            backend_status_callback=backend_status,
        )

    def gateway_session_item(self, item: dict[str, Any], route: str, result: dict[str, Any], limit_reached: bool) -> dict[str, Any]:
        return self.shared_workbench_service().session_item(item, route, result, limit_reached)

    def owner_agent_sessions(self, route: str, username: str, history_page: int = 1, exact_page: bool = False, history_filters: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.shared_workbench_service().owner_sessions(route, username, history_page, exact_page, history_filters)

    def workbench_payload(self, username: str, history_page: int = 1, history_filters: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.shared_workbench_service().payload(username, history_page, history_filters)

    def write_bridge_package_asset(self, path: str, username: str) -> None:
        match = re.match(r"^/bridge/packages/([0-9]+-[a-f0-9]{8})/([^/]+)$", path)
        if not match: self.write_not_found(path); return
        if not self.config.bridge_package(match.group(1), username):
            self.write_not_found(path); return
        filename = match.group(2); asset_path = self.config.bridge_root / match.group(1) / filename
        if filename != Path(filename).name or not asset_path.is_file(): self.write_not_found(path); return
        self.write_asset(asset_path.read_bytes(), BRIDGE_SUFFIX_MIME.get(Path(filename).suffix.lower(), "application/octet-stream"), "private, no-store")

    def route_for(self, parsed: Any) -> tuple[str, str] | None:
        parts = parsed.path.split("/", 2)
        if len(parts) < 3 or parts[1] not in BACKENDS:
            return None
        route_name, tail = parts[1], parts[2]
        if tail == "":
            return (route_name, "/") if parse_qs(parsed.query).get("session") else None
        if tail.startswith("api/") or tail in OWNER_STATIC_FILES or tail.startswith(OWNER_STATIC_PREFIXES):
            return route_name, "/" + tail
        return None

    def is_api_path(self, path: str) -> bool:
        return path.startswith("/api/") or any(path.startswith(f"/{route}/api/") for route in BACKENDS)

    def proxy(self, parsed: Any, route: tuple[str, str], username: str) -> None:
        route_name, upstream_path = route
        is_api = upstream_path.startswith("/api/")
        if not self.config.allowed_route(username, route_name):
            if is_api:
                self.write_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN)
            else:
                self.write_html("Access denied for this endpoint", HTTPStatus.FORBIDDEN)
            return
        host, port, label = BACKENDS[route_name]
        if parsed.query:
            upstream_path += "?" + parsed.query
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else None
        self.set_control_audit_target(control_target_from_json(body), route=route_name)
        blocked_headers = {"host", "content-length", "x-owner-token", "x-faryo-owner-label", "x-faryo-user", "x-faryo-history-scope", "x-faryo-file-inbox-root", "x-faryo-workspace-root", "x-faryo-csrf"}
        headers = {key: value for key, value in self.headers.items() if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() not in blocked_headers}
        headers["Host"] = f"{host}:{port}"
        headers["X-Faryo-Owner-Label"] = owner_label_header_value(label)
        headers["X-Owner-Token"] = self.config.owner_token(route_name)
        headers["X-Faryo-User"] = username
        if username != self.config.mcp_user: headers["X-Faryo-History-Scope"] = "workspace"
        file_root = self.config.file_inbox_root(username, route_name)
        if file_root:
            headers["X-Faryo-File-Inbox-Root"] = file_root
        workspace_root = self.config.workspace_root(username, route_name)
        if workspace_root:
            headers["X-Faryo-Workspace-Root"] = workspace_root
        if body is not None:
            headers["Content-Length"] = str(len(body))
        conn = None
        try:
            conn = http.client.HTTPConnection(host, port, timeout=20)
            conn.request(self.command, upstream_path, body=body, headers=headers)
            resp = conn.getresponse()
        except (OSError, UnicodeError):
            if conn:
                conn.close()
            if is_api:
                self.write_json({"ok": False, "error": "upstream unavailable"}, HTTPStatus.BAD_GATEWAY)
            else:
                self.write_html("Upstream owner is unavailable", HTTPStatus.BAD_GATEWAY)
            return
        try:
            response_headers = resp.getheaders()
            content_type = next((value for key, value in response_headers if key.lower() == "content-type"), "")
            is_event_stream = content_type.lower().startswith("text/event-stream")
            if is_event_stream:
                self.send_response(resp.status, resp.reason)
                for key, value in response_headers:
                    lower = key.lower()
                    if lower in HOP_BY_HOP_HEADERS or lower in UPSTREAM_SECURITY_HEADERS or lower in {"cache-control", "content-length"}:
                        continue
                    self.send_header(key, value)
                self.send_header("Cache-Control", "no-store, no-transform")
                self.end_headers()
                while True:
                    try:
                        chunk = resp.readline()
                    except (OSError, TimeoutError):
                        break
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, TimeoutError):
                        break
                return
            data = resp.read()
            try:
                result = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                result = {}
            if isinstance(result, dict):
                self.set_control_audit_target(
                    str(result.get("session") or ""),
                    idempotent=bool(result.get("duplicate") or result.get("idempotent")),
                )
            self.send_response(resp.status, resp.reason)
            for key, value in response_headers:
                lower = key.lower()
                if lower in HOP_BY_HOP_HEADERS or lower in UPSTREAM_SECURITY_HEADERS or lower == "content-length":
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.write_bytes(data)
        finally:
            conn.close()

    def serve_portal(self, username: str) -> None:
        self.write_page(portal_html(username, self.config.user_routes(username)))

    def is_authenticated(self) -> bool:
        return self.current_username() is not None

    def current_username(self) -> str | None:
        codec = gateway_security.SessionCookieCodec(
            self.config.cookie_secret,
            name=COOKIE_NAME,
            max_age=COOKIE_MAX_AGE,
            same_site=COOKIE_SAME_SITE,
        )
        return codec.username(self.headers.get("Cookie", ""), self.config.users, self.config.auth_epoch)

    def auth_cookie(self, username: str) -> str:
        codec = gateway_security.SessionCookieCodec(
            self.config.cookie_secret,
            name=COOKIE_NAME,
            max_age=COOKIE_MAX_AGE,
            same_site=COOKIE_SAME_SITE,
        )
        return codec.issue(username, self.config.auth_epoch(username))

    def expired_cookie(self, name: str = COOKIE_NAME) -> str:
        codec = gateway_security.SessionCookieCodec(
            self.config.cookie_secret,
            name=COOKIE_NAME,
            max_age=COOKIE_MAX_AGE,
            same_site=COOKIE_SAME_SITE,
        )
        return codec.expire(name)

    def safe_next(self, parsed: Any) -> str:
        return self.safe_target(parse_qs(parsed.query).get("next", ["/"])[0])

    def safe_target(self, value: str) -> str:
        return gateway_security.safe_target(value)

    def request_target(self) -> str:
        return self.path if self.path.startswith("/") and not self.path.startswith("//") else "/"

    def redirect(self, target: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", self.safe_target(target))
        self.end_headers()

    def write_not_found(self, path: str) -> None:
        if self.is_api_path(path):
            self.write_json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def write_login_page(self, next_target: str, error: str = "") -> None:
        self.write_page(login_html(next_target, error, self.config.icp_record))

    def write_password_page(self, error: str = "") -> None:
        username = self.current_username() or ""
        self.write_page(password_html(self.csrf_token(username) if username else "", error, self.config.icp_record))

    def write_page(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        nonce = secrets.token_urlsafe(18)
        self._csp_nonce = nonce
        body = html.replace(CSP_NONCE_PLACEHOLDER, nonce).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.write_bytes(body)

    def write_asset(self, body: bytes, content_type: str, cache: str = "public, max-age=86400") -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.write_bytes(body)

    def write_icon(self, filename: str) -> None:
        if filename not in {"pwa-light-192.png", "pwa-light-512.png", "favicon.png", "favicon.ico", "faryo-mark.png"}:
            self.write_not_found("/icons/" + filename)
            return
        path = STATIC_DIR / "icons" / filename
        if not path.is_file():
            self.write_not_found("/icons/" + filename)
            return
        content_type = "image/x-icon" if filename.endswith(".ico") else "image/png"
        self.write_asset(path.read_bytes(), content_type)

    def write_html(self, message: str, status: HTTPStatus) -> None:
        self.write_page(f"<!doctype html><meta charset='utf-8'><title>{status.value}</title><p>{html_escape(message)}</p>", status)

    def write_json(self, data: dict[str, Any], status: HTTPStatus) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.write_bytes(body)

    def write_bytes(self, body: bytes) -> bool:
        try:
            self.wfile.write(body)
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

def portal_html(username: str, routes: list[str]) -> str:
    safe_user = html_escape(username)
    safe_routes = [route for route in routes if route in BACKENDS]
    chips = []
    for route in safe_routes:
        _host, _port, label = BACKENDS[route]
        chips.append(f'<div class="route-chip" id="route-{route}"><span class="dot"></span><strong>{html_escape(label)}</strong><span class="route-state">…</span></div>')
    chips_html = "\n".join(chips) or '<div class="empty-state">No endpoints available</div>'
    labels_json = json.dumps({route: BACKENDS[route][2] for route in safe_routes}, ensure_ascii=False, separators=(",", ":"))
    labels_json = labels_json.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>Faryo</title><meta name="theme-color" content="#F6F7F9" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#0F1115" media="(prefers-color-scheme: dark)"><link rel="manifest" href="/manifest.json"><link rel="icon" href="/icons/favicon.png?v=faryo-ui-1" type="image/png"><link rel="apple-touch-icon" href="/icons/pwa-light-192.png"><script src="/appearance.js?v=unified-2"></script><link rel="stylesheet" href="/appearance.css?v=unified-2"><link rel="stylesheet" href="/workbench.css?v=faryo-gateway-2">
</head><body><div class="shell">
<header><a class="brand" href="/" aria-label="Faryo home"><img class="brand-logo" src="/icons/faryo-mark.png?v=faryo-ui-1" alt=""><div><h1>Faryo</h1><div class="subtitle">{safe_user} · Carry work forward</div></div></a><div class="settings" id="settings"><button class="settings-trigger" type="button" aria-label="Settings"><span class="settings-icon">⚙</span></button><div class="settings-menu" aria-label="Settings panel"><button id="installApp" class="settings-row install-row" type="button" hidden><span><strong>Install app</strong><small>Add Faryo to home screen</small></span><em>↗</em></button><div class="menu-title">Appearance</div><button id="themeBtn" class="settings-row appearance-btn" type="button"><span><strong>Theme</strong><small>System</small></span><em>↻</em></button><button id="fontBtn" class="settings-row appearance-btn" type="button"><span><strong>Font</strong><small>Default</small></span><em>↻</em></button><button id="sizeBtn" class="settings-row appearance-btn" type="button"><span><strong>Size</strong><small>Normal</small></span><em>↻</em></button><div class="menu-title">Attention</div><button id="attentionCenter" class="settings-row" type="button"><span><strong>Attention</strong><small id="attentionSummary">Nothing needs attention</small></span><em id="attentionCount">0</em></button><button id="notificationControl" class="settings-row" type="button"><span><strong>Notifications</strong><small id="notificationState">Off · page-open only</small></span><em>◉</em></button><div class="menu-title">Security</div><button id="securityActivity" class="settings-row" type="button"><span><strong>Security activity</strong><small>Body-free control audit</small></span><em>›</em></button><button id="revokeSessions" class="settings-row danger-row" type="button"><span><strong>Revoke signed-in devices</strong><small>Keep Codex and tmux running</small></span><em>!</em></button><div class="menu-title">Account</div><a class="settings-row" href="/password"><span><strong>Change password</strong></span><em>›</em></a><a class="settings-row" href="/logout"><span><strong>Sign out this device</strong></span><em>›</em></a></div></div></header>
<nav class="routes" aria-label="Endpoint status">{chips_html}</nav><div class="handoff-strip"><section class="handoff" id="handoffBox" aria-label="Files to session"><div class="handoff-head"><div><div class="eyebrow">Transfer</div><h2>Files to session <span class="count" id="packageCount">· Empty</span></h2></div><button class="mini-btn primary-btn" id="newPackage" type="button">Choose files</button></div><input id="packageInput" type="file" accept="image/*,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.md,.txt,.csv,.json,.rtf" multiple hidden><input id="packageAssetInput" type="file" accept="image/*,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.md,.txt,.csv,.json,.rtf" multiple hidden><div class="package-list" id="packageList"><div class="empty-state">Choose files, then send them to a session.</div></div></section><section class="new-session-panel" aria-labelledby="newSessionTitle"><div class="new-session-head"><div class="eyebrow">Launch</div><h2 id="newSessionTitle">New session</h2></div><div class="new-session-slot" id="newSessionSlot"><div class="empty-state">Loading launchers…</div></div></section></div>
<main><section class="session-section active-section" aria-labelledby="activeSessionsTitle"><div class="section-head"><h2 id="activeSessionsTitle">Active Sessions</h2><span class="count" id="activeSessionCount">Loading</span></div><section class="sessions" id="activeSessionList"><div class="empty-state">Loading active sessions...</div></section></section><section class="session-section history-section" aria-labelledby="sessionHistoryTitle"><div class="section-head"><h2 id="sessionHistoryTitle">Session History</h2><span class="count" id="historyCount">Loading</span></div><div class="history-tools"><form class="history-search" id="historySearchForm" role="search"><span aria-hidden="true">⌕</span><label class="visually-hidden" for="historySearchInput">Search session title or folder</label><input id="historySearchInput" type="search" inputmode="search" autocomplete="off" spellcheck="false" maxlength="96" placeholder="Search title or folder"><button class="history-search-clear" id="historySearchClear" type="button" aria-label="Clear history search" hidden>×</button></form><div class="history-filter-row" aria-label="Session history filters"><button class="history-filter-chip" type="button" data-history-period="all" aria-pressed="true">All time</button><button class="history-filter-chip" type="button" data-history-period="today" aria-pressed="false">Today</button><button class="history-filter-chip" type="button" data-history-period="7d" aria-pressed="false">7 days</button><button class="history-filter-chip" type="button" data-history-period="30d" aria-pressed="false">30 days</button><span class="history-filter-separator" aria-hidden="true"></span><button class="history-filter-chip" type="button" data-history-archive="active" aria-pressed="true">Current</button><button class="history-filter-chip" type="button" data-history-archive="archived" aria-pressed="false">Archived</button><button class="history-filter-chip" type="button" data-history-archive="all" aria-pressed="false">Any status</button></div></div><section class="sessions history-list" id="sessionList"><div class="empty-state">Loading history...</div></section><nav class="history-pager" aria-label="Session history pages"><button class="mini-btn" id="historyPrev" type="button">Prev</button><form class="history-jump" id="historyJump"><label for="historyPageInput">Page</label><input class="history-page-input" id="historyPageInput" type="number" min="1" max="1" step="1" inputmode="numeric" value="1" aria-label="History page"><span>of <span id="historyPageTotal">1</span></span><button class="mini-btn" type="submit">Go</button></form><button class="mini-btn" id="historyNext" type="button">Next</button></nav></section></main>
</div><div class="modal" id="modal"><div class="sheet"><div class="sheet-heading"><div class="sheet-heading-copy"><h3 id="modalTitle"></h3><p id="modalBody"></p></div></div><div id="directoryToolbar" class="directory-toolbar" hidden><nav id="directoryBreadcrumb" class="directory-breadcrumb" aria-label="Current folder"></nav><label class="directory-search"><span class="visually-hidden">Filter folders</span><span aria-hidden="true">⌕</span><input id="directorySearch" type="search" inputmode="search" autocomplete="off" spellcheck="false" placeholder="Filter folders"></label></div><div class="choice-list" id="modalChoices"></div><div class="modal-actions" id="modalActions"></div></div></div><script id="faryoRouteLabels" type="application/json" nonce="{CSP_NONCE_PLACEHOLDER}">{labels_json}</script><script src="/workbench.js?v=faryo-gateway-2"></script></body></html>'''


AUTH_CSS = """*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:var(--bg);color:var(--text);font-family:var(--app-font)}main{width:min(100%,420px)}.auth-brand{display:flex;align-items:center;gap:12px;margin-bottom:8px}.auth-logo{width:48px;height:48px;border-radius:13px;flex:0 0 auto}h1{margin:0 0 8px;font-size:26px;letter-spacing:0}p{margin:0 0 22px;color:var(--muted);line-height:1.5}label{display:block;margin:12px 0 7px;color:var(--muted);font-size:14px}input{width:100%;height:52px;border:1px solid var(--line);border-radius:8px;padding:0 13px;background:var(--panel);color:var(--text);font:inherit;outline:none}input:focus{border-color:var(--accent)}.password-row{position:relative}.password-row input{padding-right:58px}.toggle{position:absolute;right:6px;top:6px;display:grid;place-items:center;width:40px;height:40px;min-height:40px;border:0;border-radius:8px;background:var(--toggle-bg);color:var(--text)}.toggle svg{width:21px;height:21px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.toggle .eye-off,.toggle.is-visible .eye{display:none}.toggle.is-visible .eye-off{display:block}.submit{width:100%;height:52px;margin-top:18px;border:0;border-radius:8px;background:var(--accent);color:var(--on-accent);font-weight:700;font-size:16px}.secondary{display:block;margin-top:14px;color:var(--muted);text-align:center;text-decoration:none}.error{min-height:20px;margin-top:12px;color:var(--danger);font-size:14px}.icp{margin:26px 0 0;text-align:center;font-size:13px}.icp a{color:var(--muted);text-decoration:none}"""
AUTH_SCRIPT = """document.querySelectorAll('.password-row').forEach((row)=>{const input=row.querySelector('input');const toggle=row.querySelector('button');toggle.addEventListener('click',()=>{const visible=input.type==='text';input.type=visible?'password':'text';toggle.classList.toggle('is-visible',!visible);toggle.setAttribute('aria-label',visible?'Show password':'Hide password');toggle.title=visible?'Show password':'Hide password';});});"""
EYE_BUTTON = """<button class="toggle" type="button" aria-label="Show password" title="Show password"><svg class="eye" viewBox="0 0 24 24"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="3"/></svg><svg class="eye-off" viewBox="0 0 24 24"><path d="M3 3l18 18"/><path d="M10.7 5.2A10.8 10.8 0 0 1 12 5c6.5 0 10 7 10 7a17.7 17.7 0 0 1-3.2 4.1"/><path d="M6.6 6.6C3.6 8.6 2 12 2 12s3.5 7 10 7a10.5 10.5 0 0 0 4.2-.9"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg></button>"""


def password_field(field_id: str, name: str, label: str, autocomplete: str, minlength: int | None = None) -> str:
    min_attr = f' minlength="{minlength}"' if minlength else ""
    return f"""<label for="{field_id}">{label}</label><div class="password-row"><input id="{field_id}" name="{name}" type="password" autocomplete="{autocomplete}" autocapitalize="none" spellcheck="false"{min_attr} required>{EYE_BUTTON}</div>"""


def icp_footer(record: str) -> str:
    if not record:
        return ""
    return f'<p class="icp"><a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">{html_escape(record)}</a></p>'


def auth_page(title: str, heading: str, intro: str, action: str, autocomplete: str, body: str, error: str, csrf: str = "", icp: str = "") -> str:
    csrf_input = f'<input type="hidden" name="csrf" value="{html_escape(csrf)}">' if csrf else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>{title}</title><meta name="theme-color" content="#F6F7F9" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#0F1115" media="(prefers-color-scheme: dark)"><link rel="icon" href="/icons/favicon.png?v=faryo-ui-1" type="image/png"><link rel="apple-touch-icon" href="/icons/pwa-light-192.png"><script src="/appearance.js?v=unified-2"></script><link rel="stylesheet" href="/appearance.css?v=unified-2"><style nonce="{CSP_NONCE_PLACEHOLDER}">{AUTH_CSS}</style></head>
<body><main><div class="auth-brand"><img class="auth-logo" src="/icons/faryo-mark.png?v=faryo-ui-1" alt=""><div><h1>{heading}</h1><p>{intro}</p></div></div><form method="post" action="{action}" autocomplete="{autocomplete}">{csrf_input}{body}<div class="error">{html_escape(error)}</div></form>{icp_footer(icp)}</main><script nonce="{CSP_NONCE_PLACEHOLDER}">{AUTH_SCRIPT}</script></body></html>"""


def login_html(next_target: str, error: str = "", icp: str = "") -> str:
    body = (
        f'<input type="hidden" name="next" value="{html_escape(next_target)}">'
        '<label for="username">Username</label><input id="username" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required>'
        + password_field("password", "password", "Password", "current-password")
        + '<button class="submit" type="submit">Sign in</button>'
    )
    return auth_page("Faryo Sign In", "Faryo", "Enter your gateway username and password.", "/login", "on", body, error, icp=icp)


def password_html(csrf: str = "", error: str = "", icp: str = "") -> str:
    body = (
        password_field("current_password", "current_password", "Current password", "current-password")
        + password_field("new_password", "new_password", "New password", "new-password", 16)
        + password_field("confirm_password", "confirm_password", "Confirm new password", "new-password", 16)
        + '<button class="submit" type="submit">Save password</button><a class="secondary" href="/">Back to Faryo</a>'
    )
    return auth_page("Faryo Change Password", "Change password", "Update the gateway password. Changes take effect immediately.", "/password", "off", body, error, csrf, icp)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--auth-config", required=True)
    parser.add_argument("--owner-env", required=True)
    parser.add_argument("--portal-dir", required=True)
    parser.add_argument("--secret-file", required=True)
    args = parser.parse_args()

    server = ReusableThreadingHTTPServer((args.host, args.port), GatewayHandler)
    server.config = GatewayConfig(  # type: ignore[attr-defined]
        Path(args.auth_config),
        Path(args.owner_env),
        Path(args.portal_dir),
        Path(args.secret_file),
    )
    print(f"Faryo Gateway listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
