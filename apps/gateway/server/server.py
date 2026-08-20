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
import shutil
import shlex
import socket
import sys
import threading
import time
import urllib.request
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

import bcrypt

SHARED_DIR = Path(__file__).resolve().parents[2] / "shared"
SHARED_STATIC_DIR = SHARED_DIR / "static"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))


def gateway_session_max_age(values: Any) -> int:
    raw = str(values.get("FARYO_GATEWAY_SESSION_HOURS", "12")).strip()
    try:
        hours = int(raw)
    except ValueError as exc:
        raise ValueError("FARYO_GATEWAY_SESSION_HOURS must be an integer from 1 to 168") from exc
    if not 1 <= hours <= 168:
        raise ValueError("FARYO_GATEWAY_SESSION_HOURS must be an integer from 1 to 168")
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
CONTROL_AUDIT_MAX_ROWS = 5000
CONTROL_AUDIT_RETENTION_SECONDS = 7 * 24 * 60 * 60
CONTROL_AUDIT_PRUNE_INTERVAL_SECONDS = 60 * 60
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
BRIDGE_PACKAGE_MAX_BYTES = 120 * 1024 * 1024
BRIDGE_ASSET_MAX_BYTES = 20 * 1024 * 1024
BRIDGE_ASSET_LIMIT = 4
BRIDGE_PENDING_RETENTION_SECONDS = 30 * 24 * 60 * 60
BRIDGE_DELIVERED_RETENTION_SECONDS = 7 * 24 * 60 * 60
BRIDGE_CLEANUP_INTERVAL_SECONDS = 60 * 60
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
    "description": "Faryo handoff companion for available devices and sessions",
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

OWNER_STATIC_FILES = {"appearance.css", "appearance.js", "app.js", "style.css", "index.html", "event-stream.js", "internal-annotations.js", "local-file-view.js", "stable-blocks.js", "question-navigator.js", "live-scroll.js", "compact-rules-codex.js", "codex-commands.js", "copy-fidelity.js", "clipboard-images.js"}
OWNER_STATIC_PREFIXES = ("icons/", "pet/", "vendor/katex/", "vendor/markdown-ast/")
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
LOGIN_RATE_STATE: dict[str, dict[str, Any]] = {}
LOGIN_RATE_LOCK = threading.Lock()
CSP_NONCE_PLACEHOLDER = "__FARYO_CSP_NONCE__"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        try:
            parsed = shlex.split(raw, posix=True)
        except ValueError as exc:
            raise ValueError(f"invalid shell value for {key}") from exc
        values[key] = parsed[0] if len(parsed) == 1 else raw.strip()
    return values


def load_secret(path: Path) -> bytes:
    if path.exists():
        return path.read_text(encoding="utf-8").strip().encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    path.write_text(secret + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return secret.encode("utf-8")


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


def control_result_for_status(status: int) -> str:
    if 200 <= status < 300:
        return "success"
    if status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        return "denied"
    if status in {HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.GATEWAY_TIMEOUT}:
        return "timeout"
    if status == HTTPStatus.CONFLICT:
        return "conflict"
    return "error"


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


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class GatewayConfig:
    def __init__(self, auth_config: Path, owner_env: Path, portal_dir: Path, secret_file: Path):
        self.auth_config = auth_config
        auth = json.loads(auth_config.read_text(encoding="utf-8"))
        env = read_env(owner_env)
        BACKENDS.clear()
        BACKENDS.update(load_backends(env))
        self.route_max_running = self.load_route_max_running(env)
        self.mcp_token = env.get("FARYO_MCP_TOKEN", "").strip()
        self.mcp_cors_origin = env.get("FARYO_MCP_CORS_ORIGIN", "").strip()
        self.mcp_user = env.get("FARYO_MCP_USER", "").strip()
        self.users = self.load_users(auth)
        self.owner_tokens = self.load_owner_tokens(env)
        self.portal_dir = portal_dir
        self.cookie_secret = load_secret(secret_file)
        self.icp_record = env.get("FARYO_ICP_RECORD", "").strip()
        self.bridge_root = secret_file.parent / "bridge-packages"
        self.control_audit_path = secret_file.parent / "control-audit.jsonl"
        self.bridge_root.mkdir(parents=True, exist_ok=True)
        self._bridge_cleanup_lock = threading.Lock()
        self._bridge_cleanup_at = 0.0
        self._control_audit_lock = threading.Lock()
        self._control_audit_count: int | None = None
        self._control_audit_prune_at = 0.0

    def load_owner_tokens(self, env: dict[str, str]) -> dict[str, str]:
        tokens: dict[str, str] = {}
        missing = []
        for route in BACKENDS:
            key = f"FARYO_{route.upper()}_OWNER_TOKEN"
            value = env.get(key, "").strip()
            if not value:
                missing.append(key)
                continue
            tokens[route] = value
        if missing:
            raise ValueError("missing route owner token env: " + ", ".join(missing))
        return tokens

    def load_route_max_running(self, env: dict[str, str]) -> dict[str, int]:
        limits: dict[str, int] = {}
        for route in BACKENDS:
            key = f"FARYO_{route.upper()}_MAX_RUNNING"
            raw = env.get(key, str(SESSION_MAX_RUNNING_DEFAULTS[route])).strip()
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(f"{key} must be an integer from 1 to {SESSION_MAX_RUNNING_LIMIT}") from exc
            if not 1 <= value <= SESSION_MAX_RUNNING_LIMIT:
                raise ValueError(f"{key} must be an integer from 1 to {SESSION_MAX_RUNNING_LIMIT}")
            limits[route] = value
        return limits

    def max_running(self, route: str) -> int:
        return self.route_max_running[route]

    def load_users(self, auth: dict[str, Any]) -> dict[str, dict[str, Any]]:
        if "users" in auth and isinstance(auth["users"], dict):
            source = auth["users"]
        else:
            username = str(auth["username"])
            source = {username: {"bcrypt_hash": str(auth["bcrypt_hash"]), "auth_epoch": int(auth.get("auth_epoch") or 0), "routes": list(BACKENDS)}}
        users: dict[str, dict[str, Any]] = {}
        for username, payload in source.items():
            if not isinstance(payload, dict):
                continue
            name = str(username).strip()
            if not name:
                continue
            configured = payload.get("routes")
            if configured is None:
                routes = list(BACKENDS)
            elif isinstance(configured, list):
                routes = [route for route in configured if route in BACKENDS]
            else:
                raise ValueError(f"gateway user {name!r} routes must be a list")
            if not routes:
                raise ValueError(f"gateway user {name!r} has no enabled routes")
            default_route = str(payload.get("default_route") or (routes[0] if routes else "txy"))
            if default_route not in routes and routes:
                default_route = routes[0]
            users[name] = {
                "bcrypt_hash": str(payload["bcrypt_hash"]),
                "auth_epoch": int(payload.get("auth_epoch") or 0),
                "routes": routes,
                "default_route": default_route,
                "file_inbox_roots": dict(payload.get("file_inbox_roots") or {}),
                "workspace_roots": dict(payload.get("workspace_roots") or {}),
            }
        if not users:
            raise ValueError("gateway auth config has no valid users")
        if not self.mcp_user or self.mcp_user not in users:
            self.mcp_user = next(iter(users))
        return users

    def save_users(self) -> None:
        payload = {"users": self.users}
        tmp = self.auth_config.with_name(f".{self.auth_config.name}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.auth_config)

    def user(self, username: str) -> dict[str, Any] | None:
        return self.users.get(username)

    def user_routes(self, username: str) -> list[str]:
        user = self.users.get(username) or {}
        return [route for route in user.get("routes", []) if route in BACKENDS]

    def allowed_route(self, username: str, route: str) -> bool:
        return route in self.user_routes(username)

    def password_hash(self, username: str) -> bytes:
        return str(self.users[username]["bcrypt_hash"]).encode("utf-8")

    def auth_epoch(self, username: str) -> int:
        return int(self.users[username].get("auth_epoch") or 0)

    def revoke_sessions(self, username: str) -> None:
        if username not in self.users:
            raise ValueError("unknown user")
        self.users[username]["auth_epoch"] = max(int(time.time()), self.auth_epoch(username) + 1)
        self.save_users()

    def control_target_digest(self, value: str) -> str:
        clean = str(value or "").strip()
        if not clean:
            return ""
        digest = hmac.new(self.cookie_secret, clean.encode("utf-8"), hashlib.sha256).hexdigest()
        return "t_" + digest[:16]

    def _prune_control_audit_locked(self, now: float) -> None:
        rows: list[dict[str, Any]] = []
        cutoff = now - CONTROL_AUDIT_RETENTION_SECONDS
        try:
            with self.control_audit_path.open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                        epoch = float(row.get("epoch") or 0) if isinstance(row, dict) else 0
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
                    if epoch >= cutoff:
                        rows.append(row)
        except FileNotFoundError:
            rows = []
        rows = rows[-CONTROL_AUDIT_MAX_ROWS:]
        self.control_audit_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.control_audit_path.with_name(f".{self.control_audit_path.name}.{os.getpid()}.tmp")
        tmp.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.control_audit_path)
        self._control_audit_count = len(rows)
        self._control_audit_prune_at = now + CONTROL_AUDIT_PRUNE_INTERVAL_SECONDS

    def append_control_audit(self, *, username: str, route: str, action: str, target: str, request_id: str, status: int, duration_ms: int, idempotent: bool = False) -> None:
        """Best-effort, body-free audit trail. Audit failure never blocks control."""
        try:
            now = time.time()
            row = {
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "epoch": int(now),
                "requestId": str(request_id or "")[:32],
                "user": str(username or "")[:128],
                "route": str(route or "")[:24],
                "action": str(action or "")[:32],
                "target": self.control_target_digest(target),
                "result": control_result_for_status(int(status)),
                "http": int(status),
                "durationMs": max(0, min(int(duration_ms), 3_600_000)),
                "idempotent": bool(idempotent),
            }
            encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            with self._control_audit_lock:
                self.control_audit_path.parent.mkdir(parents=True, exist_ok=True)
                if self._control_audit_count is None:
                    try:
                        with self.control_audit_path.open(encoding="utf-8", errors="replace") as stream:
                            self._control_audit_count = sum(1 for _line in stream)
                    except FileNotFoundError:
                        self._control_audit_count = 0
                descriptor = os.open(self.control_audit_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    os.chmod(self.control_audit_path, 0o600)
                    os.write(descriptor, encoded.encode("utf-8"))
                finally:
                    os.close(descriptor)
                self._control_audit_count += 1
                if self._control_audit_count > CONTROL_AUDIT_MAX_ROWS or now >= self._control_audit_prune_at:
                    self._prune_control_audit_locked(now)
        except Exception:
            return

    def control_activity(self, username: str, limit: int = 30) -> list[dict[str, Any]]:
        allowed_routes = set(self.user_routes(username))
        maximum = max(1, min(int(limit), 100))
        rows: list[dict[str, Any]] = []
        with self._control_audit_lock:
            if not self.control_audit_path.exists():
                return []
            now = time.time()
            if now >= self._control_audit_prune_at:
                self._prune_control_audit_locked(now)
            try:
                with self.control_audit_path.open(encoding="utf-8", errors="replace") as stream:
                    lines = stream.readlines()
            except FileNotFoundError:
                return []
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or row.get("user") != username or row.get("route") not in allowed_routes | {""}:
                continue
            rows.append({key: row.get(key) for key in ("time", "requestId", "route", "action", "target", "result", "http", "durationMs", "idempotent")})
            if len(rows) >= maximum:
                break
        return rows

    def set_password(self, username: str, password: str) -> None:
        if username not in self.users:
            raise ValueError("unknown user")
        self.users[username]["bcrypt_hash"] = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        self.users[username]["auth_epoch"] = int(time.time())
        self.save_users()

    def file_inbox_root(self, username: str, route: str) -> str | None:
        value = (self.users.get(username) or {}).get("file_inbox_roots", {}).get(route)
        return str(value) if value else None

    def workspace_root(self, username: str, route: str) -> str | None:
        value = (self.users.get(username) or {}).get("workspace_roots", {}).get(route)
        return str(value) if value else None

    def owner_token(self, route: str) -> str:
        return self.owner_tokens[route]


    def bridge_asset_sources(self, payload: dict[str, Any]) -> list[Any]:
        assets: list[Any] = []
        for key in ("attachments", "files", "assets", "images"):
            values = payload.get(key)
            if isinstance(values, list):
                assets.extend(values)
        for key in ("attachment", "file", "asset", "image"):
            if payload.get(key):
                assets.insert(0, payload.get(key))
        return assets[:BRIDGE_ASSET_LIMIT]

    def attachment_only_prompt(self, title: str) -> str:
        return f"# Faryo Handoff Package\nTitle: {title}\n\nReview the attached files and continue from the current session context. Use the attachment paths below as the canonical source files."

    def save_bridge_assets(self, package_id: str, package_dir: Path, asset_sources: list[Any], start_index: int = 1) -> list[dict[str, Any]]:
        assets = []
        for index, item in enumerate(asset_sources, start=start_index):
            asset = normalize_bridge_asset_payload(item)
            if not asset: raise ValueError("invalid attachment payload")
            mime_type, data = bridge_asset_bytes_from_payload(asset); file_name = f"asset-{index}{BRIDGE_MIME_EXT[mime_type]}"; path = package_dir / file_name; path.write_bytes(data)
            assets.append({"file_name": asset["file_name"], "mime_type": mime_type, "size": len(data), "path": str(path), "url": f"/bridge/packages/{package_id}/{file_name}"})
        return assets

    def user_can_access_package(self, username: str, package: dict[str, Any]) -> bool:
        owner = str(package.get("owner") or "")
        return owner == username or (not owner and username == self.mcp_user)

    def save_bridge_package(self, payload: dict[str, Any], username: str) -> dict[str, Any]:
        self.cleanup_bridge_packages()
        title = str(payload.get("title") or payload.get("topic") or "Untitled handoff").strip()[:120] or "Untitled handoff"; prompt = str(payload.get("prompt") or payload.get("instruction") or payload.get("handoff_prompt") or "").strip(); assets = self.bridge_asset_sources(payload)
        if not prompt and not assets: raise ValueError("package prompt or attachment is required")
        package_id = f"{now_ts()}-{secrets.token_hex(4)}"; package_dir = self.bridge_root / package_id; package_dir.mkdir(parents=True, exist_ok=False)
        try:
            package = {"id": package_id, "owner": username, "title": title, "source": str(payload.get("source") or "Faryo Gateway"), "intent": str(payload.get("intent") or ""), "context": str(payload.get("context") or payload.get("summary") or ""), "prompt": prompt or self.attachment_only_prompt(title), "assets": self.save_bridge_assets(package_id, package_dir, assets), "status": "pending", "created_at": now_ts(), "updated_at": now_ts()}
            (package_dir / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); return package
        except Exception:
            shutil.rmtree(package_dir, ignore_errors=True); raise

    def append_bridge_package_assets(self, package_id: str, asset_sources: list[Any], username: str) -> dict[str, Any]:
        package_id = clean_package_id(package_id) or ""; package = self.bridge_package(package_id, username)
        if not package_id: raise ValueError("invalid package id")
        if not asset_sources: raise ValueError("attachment is required")
        if not package: raise ValueError("package not found")
        if package.get("status") != "pending": raise ValueError("package is already delivered")
        assets = package.get("assets") if isinstance(package.get("assets"), list) else []
        package["assets"] = assets + self.save_bridge_assets(package_id, self.bridge_root / package_id, asset_sources[:BRIDGE_ASSET_LIMIT], len(assets) + 1)
        package["prompt"] = str(package.get("prompt") or "").strip() or self.attachment_only_prompt(str(package.get("title") or "Handoff package")); self.update_bridge_package(package); return package

    def list_bridge_packages(self, username: str, status: str | None = None) -> list[dict[str, Any]]:
        self.cleanup_bridge_packages()
        packages = [p for p in (self.bridge_package(path.parent.name, username) for path in self.bridge_root.glob("*/package.json")) if p and (not status or p.get("status") == status)]
        return sorted(packages, key=lambda item: int(item.get("updated_at") or item.get("created_at") or 0), reverse=True)

    def cleanup_bridge_packages(self, current_time: int | None = None, force: bool = False) -> int:
        now = int(current_time if current_time is not None else now_ts())
        monotonic_now = time.monotonic()
        with self._bridge_cleanup_lock:
            if not force and monotonic_now < self._bridge_cleanup_at:
                return 0
            self._bridge_cleanup_at = monotonic_now + BRIDGE_CLEANUP_INTERVAL_SECONDS
            root = self.bridge_root.resolve()
            removed = 0
            try:
                candidates = list(self.bridge_root.iterdir())
            except OSError:
                return 0
            for package_dir in candidates:
                if package_dir.is_symlink() or clean_package_id(package_dir.name) != package_dir.name:
                    continue
                try:
                    target = package_dir.resolve(strict=True)
                    if target.parent != root or not target.is_dir():
                        continue
                    package_file = target / "package.json"
                    package = json.loads(package_file.read_text(encoding="utf-8"))
                    if not isinstance(package, dict):
                        continue
                    updated = int(package.get("updated_at") or package.get("created_at") or package_file.stat().st_mtime)
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    continue
                retention = BRIDGE_PENDING_RETENTION_SECONDS if package.get("status") == "pending" else BRIDGE_DELIVERED_RETENTION_SECONDS
                if updated <= 0 or now - updated <= retention:
                    continue
                shutil.rmtree(target)
                removed += 1
            return removed

    def bridge_package(self, package_id: str, username: str | None = None) -> dict[str, Any] | None:
        path = self.bridge_root / (clean_package_id(package_id) or "") / "package.json"
        try: package = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return None
        if not isinstance(package, dict):
            return None
        if username and not self.user_can_access_package(username, package):
            return None
        return package

    def update_bridge_package(self, package: dict[str, Any]) -> None:
        package_id = clean_package_id(str(package.get("id") or ""))
        if not package_id: raise ValueError("invalid package id")
        package["updated_at"] = now_ts(); (self.bridge_root / package_id / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        script_src = "'self'" + (f" 'nonce-{nonce}'" if nonce else "")
        self.send_header(
            "Content-Security-Policy",
            "; ".join([
                "default-src 'self'",
                f"script-src {script_src}",
                "script-src-attr 'none'",
                "style-src 'self' 'unsafe-inline'",
                "img-src 'self' data: blob:",
                "font-src 'self'",
                "connect-src 'self'",
                "worker-src 'self'",
                "manifest-src 'self'",
                "object-src 'none'",
                "base-uri 'none'",
                "frame-ancestors 'none'",
                "form-action 'self'",
            ]),
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Strict-Transport-Security", "max-age=31536000")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/mcp":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_mcp_cors_headers()
            self.send_header("Access-Control-Allow-Headers", "authorization, content-type, mcp-protocol-version, mcp-session-id, x-faryo-mcp-token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

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
        if isinstance(payload, list):
            responses = []
            for item in payload:
                response = self.mcp_response(item) if isinstance(item, dict) else self.mcp_error(None, -32600, "invalid JSON-RPC message")
                if isinstance(response, list): responses.extend(response)
                elif response is not None: responses.append(response)
            return responses or None
        if not isinstance(payload, dict): return self.mcp_error(None, -32600, "invalid JSON-RPC message")
        request_id = payload.get("id"); method = str(payload.get("method") or ""); params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        if request_id is None: return None
        try:
            if method == "initialize": return self.mcp_result(request_id, {"protocolVersion": str(params.get("protocolVersion") or MCP_PROTOCOL_VERSION), "capabilities": {"tools": {"listChanged": True}}, "serverInfo": {"name": "faryo-bridge", "version": MCP_SERVER_VERSION}, "instructions": "Create Faryo handoff packages for cross-session, cross-device, or external workflow transfer."})
            if method == "tools/list": return self.mcp_result(request_id, {"tools": self.mcp_tool_descriptors()})
            if method == "resources/list": return self.mcp_result(request_id, {"resources": []})
            if method == "resources/read": return self.mcp_result(request_id, {"contents": []})
            if method == "ping": return self.mcp_result(request_id, {})
            if method == "tools/call":
                name = str(params.get("name") or ""); arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
                if name == MCP_TOOL_NAME: return self.mcp_result(request_id, self.mcp_create_handoff(arguments))
                return self.mcp_error(request_id, -32602, f"unknown tool: {name}")
            return self.mcp_error(request_id, -32601, f"method not found: {method}")
        except ValueError as exc: return self.mcp_error(request_id, -32602, str(exc))
        except Exception as exc: return self.mcp_error(request_id, -32000, str(exc))

    def mcp_result(self, request_id: Any, result: dict[str, Any]) -> dict[str, Any]: return {"jsonrpc": "2.0", "id": request_id, "result": result}
    def mcp_error(self, request_id: Any, code: int, message: str) -> dict[str, Any]: return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def mcp_tool_descriptors(self) -> list[dict[str, Any]]:
        return [
            {"name": MCP_TOOL_NAME, "title": "Create Faryo handoff package", "description": "Create a Faryo Inbox handoff package for cross-session, cross-device, or external workflow transfer. Attachments may be file objects, data_url strings, https URLs, or base64_data; do not pass local sandbox paths such as /mnt/data.", "inputSchema": MCP_TOOL_SCHEMAS[MCP_TOOL_NAME], "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}, "_meta": {"openai/fileParams": ["attachment", "attachments", "image", "images"], "openai/toolInvocation/invoking": "Creating Faryo handoff package...", "openai/toolInvocation/invoked": "Faryo handoff package created."}},
        ]

    def mcp_create_handoff(self, arguments: dict[str, Any]) -> dict[str, Any]:
        package = self.config.save_bridge_package({"title": str(arguments.get("title") or "").strip(), "source": "Faryo MCP", "intent": str(arguments.get("intent") or "").strip(), "context": str(arguments.get("context") or arguments.get("summary") or "").strip(), "prompt": str(arguments.get("prompt") or "").strip(), "attachment": arguments.get("attachment"), "attachments": arguments.get("attachments") if isinstance(arguments.get("attachments"), list) else [], "image": arguments.get("image"), "images": arguments.get("images") if isinstance(arguments.get("images"), list) else []}, self.config.mcp_user)
        structured = {"ok": True, "package_id": package["id"], "title": package["title"], "assets": package["assets"], "gateway_url": self.public_base_url() + "/"}
        return {"structuredContent": structured, "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}], "_meta": {}}

    def public_base_url(self) -> str:
        return f"{self.headers.get('X-Forwarded-Proto') or 'https'}://{self.headers.get('X-Forwarded-Host') or self.headers.get('Host') or ''}".rstrip("/")

    def mcp_cors_allowed(self) -> str:
        origin = self.headers.get("Origin", "").strip()
        return origin if origin and origin == self.config.mcp_cors_origin else ""

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
        auth = self.headers.get("Authorization", "").strip()
        token = self.headers.get("X-Faryo-Mcp-Token", "").strip()
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if self.config.mcp_token and token and hmac.compare_digest(token, self.config.mcp_token):
            return True
        self.write_mcp_json(self.mcp_error(None, -32001, "unauthorized"), HTTPStatus.UNAUTHORIZED)
        return False

    def csrf_token(self, username: str) -> str:
        message = f"{username}|{self.config.auth_epoch(username)}".encode("utf-8")
        return hmac.new(self.config.cookie_secret, message, hashlib.sha256).hexdigest()

    def require_csrf_header(self, username: str) -> bool:
        token = self.headers.get(CSRF_HEADER, "").strip()
        if token and hmac.compare_digest(token, self.csrf_token(username)):
            return True
        self.write_json({"ok": False, "error": "csrf required"}, HTTPStatus.FORBIDDEN)
        return False

    def login_rate_key(self) -> str:
        peer = str(self.client_address[0])
        try:
            peer_is_loopback = ipaddress.ip_address(peer).is_loopback
        except ValueError:
            peer_is_loopback = False
        if peer_is_loopback:
            cloudflare_ip = self.headers.get("CF-Connecting-IP", "").strip()
            try:
                return ipaddress.ip_address(cloudflare_ip).compressed
            except ValueError:
                pass
        return peer

    def login_rate_limited(self, key: str) -> bool:
        now = time.monotonic()
        with LOGIN_RATE_LOCK:
            entry = LOGIN_RATE_STATE.get(key)
            return bool(entry and entry.get("blocked_until", 0) > now)

    def record_login_failure(self, key: str) -> None:
        now = time.monotonic()
        with LOGIN_RATE_LOCK:
            entry = LOGIN_RATE_STATE.setdefault(key, {"failures": [], "blocked_until": 0.0})
            entry["failures"] = [ts for ts in entry["failures"] if now - ts < LOGIN_RATE_WINDOW_SECONDS] + [now]
            if len(entry["failures"]) >= LOGIN_RATE_MAX_FAILURES:
                entry["blocked_until"] = now + LOGIN_RATE_BLOCK_SECONDS

    def clear_login_rate(self, key: str) -> None:
        with LOGIN_RATE_LOCK:
            LOGIN_RATE_STATE.pop(key, None)

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
        host, port, label = BACKENDS[route]; headers = {"Host": f"{host}:{port}", "X-Faryo-Owner-Label": owner_label_header_value(label), "X-Owner-Token": self.config.owner_token(route), "X-Faryo-User": username}
        if username != self.config.mcp_user: headers["X-Faryo-History-Scope"] = "workspace"
        if file_root := self.config.file_inbox_root(username, route): headers["X-Faryo-File-Inbox-Root"] = file_root
        if workspace_root := self.config.workspace_root(username, route): headers["X-Faryo-Workspace-Root"] = workspace_root
        return headers

    def owner_json_request(self, route: str, path: str, payload: dict[str, Any] | None, username: str, method: str = "POST", timeout: float = 10, extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
        host, port, _label = BACKENDS[route]; headers = self.owner_headers(route, username); body = None
        if extra_headers:
            headers.update({key: value for key, value in extra_headers.items() if value})
        if payload is not None: body = json.dumps(payload, ensure_ascii=False).encode("utf-8"); headers.update({"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body))})
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try: conn.request(method, path, body=body, headers=headers); resp = conn.getresponse(); data = resp.read()
        except (OSError, UnicodeError) as exc: return {"ok": False, "error": str(exc), "retryable": True, "transportError": True}
        finally: conn.close()
        try: result = json.loads(data.decode("utf-8"))
        except Exception: result = {"ok": False, "error": f"owner returned HTTP {resp.status}"}
        if resp.status >= 400 and isinstance(result, dict): result.update({"ok": False, "httpStatus": resp.status})
        return result if isinstance(result, dict) else {"ok": False, "error": "invalid owner response"}

    def owner_attachment_request(self, route: str, path: Path, mime_type: str, filename: str, username: str) -> dict[str, Any]:
        host, port, _label = BACKENDS[route]
        boundary = "----FaryoBoundary" + secrets.token_hex(12)
        safe_name = Path(filename).name.replace('"', "_").replace("\r", "_").replace("\n", "_") or path.name
        data = path.read_bytes()
        body = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"file\"; filename=\"{safe_name}\"\r\n"
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
        headers = self.owner_headers(route, username)
        headers.update({"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))})
        conn = http.client.HTTPConnection(host, port, timeout=20)
        try:
            conn.request("POST", "/api/attachment", body=body, headers=headers); resp = conn.getresponse(); response_body = resp.read()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            conn.close()
        try:
            result = json.loads(response_body.decode("utf-8"))
        except Exception:
            result = {"ok": False, "error": f"owner returned HTTP {resp.status}"}
        if resp.status >= 400 and isinstance(result, dict): result.update({"ok": False, "httpStatus": resp.status})
        return result if isinstance(result, dict) else {"ok": False, "error": "invalid owner response"}

    def max_running_for(self, username: str, route: str) -> int:
        return self.config.max_running(route)

    def gateway_session_item(self, item: dict[str, Any], route: str, result: dict[str, Any], limit_reached: bool) -> dict[str, Any]:
        updated_raw = item.get("updatedAt") or item.get("updated_at") or result.get("updatedAt") or ""
        tmux_session = str(item.get("tmuxSession") or item.get("session") or "")
        active = bool(tmux_session)
        cwd = str(item.get("cwd") or "")
        raw_state = str(item.get("state") or "").strip().lower()
        if raw_state not in SESSION_STATES:
            raw_state = ("running" if item.get("agentRunning") else "waiting") if active else ("archived" if item.get("archived") else "resumable")
        return {
            "id": str(item.get("id") or ""),
            "title": display_session_title(item.get("title") or item.get("label") or item.get("id") or "Untitled session"),
            "gitLabel": str(item.get("gitLabel") or item.get("git_label") or ""),
            "route": route,
            "routeLabel": BACKENDS[route][2],
            "cwd": cwd,
            "cwdLabel": compact_path_label(cwd),
            "updatedAt": display_updated_at(updated_raw),
            "updatedTs": float(item.get("updatedTs") or parse_updated_ts(updated_raw)),
            "tmuxSession": tmux_session,
            "active": active,
            "managed": bool(item.get("managed")),
            "agentRunning": bool(active and item.get("agentRunning")),
            "state": raw_state,
            "archived": bool(item.get("archived")),
            "limitReached": bool(not active and limit_reached),
            "source": str(item.get("source") or ""),
        }

    def owner_agent_sessions(self, route: str, username: str, history_page: int = 1, exact_page: bool = False, history_filters: dict[str, Any] | None = None) -> dict[str, Any]:
        page = max(1, history_page)
        history_limit = HISTORY_PAGE_SIZE if exact_page else min(HISTORY_PAGE_SIZE * page, HISTORY_MAX_FETCH)
        history_offset = (page - 1) * HISTORY_PAGE_SIZE if exact_page else 0
        max_running = self.max_running_for(username, route)
        result = self.owner_json_request(route, owner_history_query(history_limit, history_offset, history_filters), None, username, method="GET")
        active_count = int(result.get("activeCount") or 0)
        limit_reached = active_count >= max_running
        raw_active = result.get("activeSessions", []) if result.get("ok") and isinstance(result.get("activeSessions"), list) else []
        raw_history = result.get("sessions", []) if result.get("ok") and isinstance(result.get("sessions"), list) else []
        active_sessions = [self.gateway_session_item(item, route, result, limit_reached) for item in raw_active if isinstance(item, dict)]
        sessions = [self.gateway_session_item(item, route, result, limit_reached) for item in raw_history if isinstance(item, dict)]
        return {
            "activeSessions": active_sessions,
            "sessions": sessions,
            "historyTotal": int(result.get("historyTotal") or len(sessions)),
            "activeCount": active_count,
            "maxRunning": max_running,
            "canCreate": not limit_reached,
        }

    def workbench_payload(self, username: str, history_page: int = 1, history_filters: dict[str, Any] | None = None) -> dict[str, Any]:
        requested_page = max(1, history_page)
        applied_filters = normalize_history_filters(history_filters)
        routes = self.config.user_routes(username)
        exact_page = len(routes) == 1
        route_payloads = {route: self.owner_agent_sessions(route, username, requested_page, exact_page, applied_filters) for route in routes}
        active_sessions = [item for route in routes for item in route_payloads[route]["activeSessions"]]
        active_sessions.sort(key=lambda item: (SESSION_STATE_PRIORITY.get(str(item.get("state") or ""), -1), float(item.get("updatedTs") or 0)), reverse=True)
        sessions = [item for route in routes for item in route_payloads[route]["sessions"]]
        sessions.sort(key=lambda item: float(item.get("updatedTs") or 0), reverse=True)
        history_total = sum(int(route_payloads[route]["historyTotal"]) for route in routes)
        total_pages = max(1, (history_total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
        page = min(requested_page, total_pages)
        if exact_page and page != requested_page:
            route = routes[0]
            route_payloads[route] = self.owner_agent_sessions(route, username, page, True, applied_filters)
            active_sessions = route_payloads[route]["activeSessions"]
            sessions = route_payloads[route]["sessions"]
        start = (page - 1) * HISTORY_PAGE_SIZE
        entries = []
        for item in [backend_status(route) for route in routes]:
            item.update({key: route_payloads[item["id"]][key] for key in ("activeCount", "maxRunning", "canCreate")})
            entries.append(item)
        cwd_choices = {}
        for route in routes:
            choice_payload = route_payloads[route]
            cwd_choices[route] = agent_cwd_choices(
                [*choice_payload["activeSessions"], *choice_payload["sessions"]],
                self.config.workspace_root(username, route),
            )
        inbox = self.config.list_bridge_packages(username, "pending")[:1]
        return {
            "ok": True,
            "entries": entries,
            "activeSessions": active_sessions,
            "sessions": sessions[:HISTORY_PAGE_SIZE] if exact_page else sessions[start:start + HISTORY_PAGE_SIZE],
            "history": {
                "page": page,
                "pageSize": HISTORY_PAGE_SIZE,
                "total": history_total,
                "totalPages": total_pages,
                "hasPrevious": page > 1,
                "hasNext": page < total_pages,
                "filter": applied_filters,
            },
            "newSessionCommands": sorted(NEW_SESSION_COMMANDS),
            "agentCwdChoices": cwd_choices,
            "packages": inbox,
            "inbox": inbox,
            "updatedAt": now_ts(),
        }

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
                    if lower in HOP_BY_HOP_HEADERS or lower in UPSTREAM_SECURITY_HEADERS or lower == "content-length":
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
        raw = self.headers.get("Cookie", "")
        if not raw:
            return None
        cookie = SimpleCookie(raw)
        morsel = cookie.get(COOKIE_NAME)
        if not morsel:
            return None
        try:
            payload_b64, sig = morsel.value.rsplit(".", 1)
            payload = base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
            expected = hmac.new(self.config.cookie_secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                return None
            parts = payload.split("|")
            if len(parts) == 3:
                username, issued_at, _nonce = parts
                cookie_epoch = 0
            elif len(parts) == 4:
                username, issued_at, epoch, _nonce = parts
                cookie_epoch = int(epoch)
            else:
                return None
            if username not in self.config.users:
                return None
            auth_epoch = self.config.auth_epoch(username)
            if auth_epoch and cookie_epoch != auth_epoch:
                return None
            if time.time() - int(issued_at) >= COOKIE_MAX_AGE:
                return None
            return username
        except Exception:
            return None

    def auth_cookie(self, username: str) -> str:
        epoch = self.config.auth_epoch(username)
        payload = f"{username}|{int(time.time())}|{epoch}|{secrets.token_urlsafe(18)}"
        payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
        sig = hmac.new(self.config.cookie_secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{COOKIE_NAME}={payload_b64}.{sig}; Path=/; Max-Age={COOKIE_MAX_AGE}; HttpOnly; Secure; SameSite={COOKIE_SAME_SITE}"

    def expired_cookie(self, name: str = COOKIE_NAME) -> str:
        return f"{name}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite={COOKIE_SAME_SITE}"

    def safe_next(self, parsed: Any) -> str:
        return self.safe_target(parse_qs(parsed.query).get("next", ["/"])[0])

    def safe_target(self, value: str) -> str:
        if not value.startswith("/") or value.startswith("//"):
            return "/"
        return value

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

PORTAL_CSS = """*{box-sizing:border-box}body{margin:0;min-height:100vh;padding:calc(env(safe-area-inset-top) + 14px) 14px calc(env(safe-area-inset-bottom) + 18px);background:var(--bg);color:var(--text);font-family:var(--app-font);font-size:calc(14px + var(--font-step));letter-spacing:0}.shell{width:min(100%,720px);margin:0 auto}header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.brand{display:flex;align-items:center;gap:10px;min-width:0;color:inherit;text-decoration:none}.brand-logo{width:38px;height:38px;border-radius:10px}h1{margin:0;font-size:24px;line-height:1.1}.subtitle,.count,.route-state,.session-meta,.package-meta{color:var(--muted);font-size:calc(12px + var(--font-step))}.subtitle{margin-top:4px}.settings{position:relative;z-index:12}.settings-trigger{position:relative;width:39px;height:39px;display:grid;place-items:center;border:1px solid color-mix(in srgb,var(--accent) 30%,var(--line));border-radius:13px;background:radial-gradient(circle at 30% 22%,color-mix(in srgb,var(--accent) 20%,transparent),transparent 42%),linear-gradient(145deg,color-mix(in srgb,var(--panel) 92%,var(--panel2)),color-mix(in srgb,var(--panel2) 84%,var(--panel)));color:var(--text);box-shadow:var(--shadow);transition:transform .18s ease,border-color .18s ease,background .18s ease}.settings-trigger:active{transform:scale(.96)}.settings.open .settings-trigger{border-color:color-mix(in srgb,var(--accent2) 52%,var(--accent));background:radial-gradient(circle at 28% 20%,color-mix(in srgb,var(--accent2) 28%,transparent),transparent 48%),linear-gradient(145deg,color-mix(in srgb,var(--panel2) 88%,var(--panel)),var(--panel))}.settings-icon{font-size:18px;line-height:1}
.settings-menu{position:absolute;right:0;top:47px;z-index:20;display:none;width:min(72vw,248px);min-width:210px;padding:10px;border:1px solid color-mix(in srgb,var(--accent) 28%,var(--line));border-radius:20px;background:linear-gradient(145deg,color-mix(in srgb,var(--panel) 94%,var(--panel2)),color-mix(in srgb,var(--panel2) 82%,var(--panel)));box-shadow:var(--shadow);backdrop-filter:blur(18px) saturate(1.18);transform-origin:calc(100% - 24px) 0;animation:settings-bloom .16s ease-out}.settings-menu::after{content:"";position:absolute;right:18px;top:-7px;width:14px;height:14px;transform:rotate(45deg);border-left:1px solid color-mix(in srgb,var(--accent) 26%,var(--line));border-top:1px solid color-mix(in srgb,var(--accent) 26%,var(--line));background:color-mix(in srgb,var(--panel) 94%,var(--panel2))}.settings.open .settings-menu{display:grid;gap:6px}.settings-menu .menu-title{padding:6px 4px 0;color:color-mix(in srgb,var(--muted) 82%,transparent);font-size:10px;font-weight:850;letter-spacing:.10em;text-transform:uppercase}.settings-row{width:100%;min-height:46px;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:8px;padding:8px 10px;border:1px solid color-mix(in srgb,var(--line) 72%,transparent);border-radius:14px;background:color-mix(in srgb,var(--panel2) 56%,transparent);color:var(--text);text-align:left;text-decoration:none;font:inherit}.settings-row:hover,.settings-row:focus-visible{border-color:color-mix(in srgb,var(--accent) 42%,var(--line));background:color-mix(in srgb,var(--panel2) 78%,transparent);outline:none}.settings-row strong{display:block;font-size:12px;line-height:1.2}.settings-row small{display:block;margin-top:2px;color:var(--muted);font-size:10px;line-height:1.2}.settings-row em{color:var(--accent2);font-size:14px;font-style:normal}.settings-row.install-row{border-color:color-mix(in srgb,var(--accent2) 42%,var(--line));background:linear-gradient(135deg,color-mix(in srgb,var(--accent2) 14%,var(--panel2)),color-mix(in srgb,var(--accent) 10%,var(--panel)))}.settings-menu [hidden]{display:none!important}@keyframes settings-bloom{from{opacity:0;transform:translateY(-4px) scale(.96)}to{opacity:1;transform:translateY(0) scale(1)}}
.routes{display:flex;flex-wrap:wrap;gap:8px;overflow:visible;min-height:42px;margin-bottom:10px;padding:1px}.route-chip{display:flex;align-items:center;gap:5px;white-space:nowrap;padding:7px 8px;border:1px solid var(--line);border-radius:999px;background:var(--panel);color:var(--text);text-decoration:none;font-size:12px}.dot{width:8px;height:8px;border-radius:999px;background:var(--muted)}.online .dot{background:var(--ok)}.slow .dot{background:var(--warn)}.offline .dot,.error .dot{background:var(--danger)}.handoff-strip{display:grid;grid-template-columns:minmax(0,1fr) minmax(160px,200px);gap:10px;align-items:stretch;margin-bottom:12px}.handoff{padding:9px;border:1px solid var(--line);border-radius:8px;background:var(--panel);box-shadow:var(--shadow)}.handoff.drop-ready{border-color:var(--accent2)}.handoff-head,.section-head{display:flex;align-items:center;justify-content:space-between;gap:8px}.handoff-head{margin-bottom:7px}.eyebrow{margin:0 0 2px;color:var(--accent2);font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}h2{margin:0;font-size:calc(15px + var(--font-step));line-height:1.2}.mini-btn{padding:6px 8px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--text);font:inherit;font-size:calc(12px + var(--font-step));white-space:nowrap}.primary-btn{border-color:color-mix(in srgb,var(--accent) 44%,var(--line));color:var(--accent)}.package-list{min-height:48px}.package-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;padding:8px;border:1px solid var(--line);border-radius:7px;background:var(--panel2);touch-action:none}.package-card.dragging{opacity:.55}.drag-ghost{position:fixed;z-index:9999;pointer-events:none;transform:translate(-50%,-50%);box-shadow:var(--shadow)}.package-card strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:calc(13px + var(--font-step))}.package-meta{display:block;margin-top:3px;line-height:1.35}main{display:grid;gap:8px}.sessions{display:grid;gap:8px}.session-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;width:100%;padding:11px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--text);text-decoration:none;text-align:left;font:inherit}.new-session-slot{display:grid;gap:8px}.new-session-slot .session-card{min-height:44px}.session-card>div:first-child{min-width:0}.session-card.inactive{opacity:.72}.session-card.running{border:2px solid var(--warn);background:color-mix(in srgb,var(--warn) 10%,var(--panel));box-shadow:inset 5px 0 0 var(--warn),0 0 0 3px color-mix(in srgb,var(--warn) 24%,transparent)}.session-card.waiting{border-color:color-mix(in srgb,var(--accent) 48%,var(--line));background:color-mix(in srgb,var(--accent) 7%,var(--panel))}.session-card.drop-target{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 24%,transparent)}.session-title{font-size:calc(15px + var(--font-step));font-weight:760;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.session-meta{margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.arrow{color:var(--muted);font-size:20px}.modal{position:fixed;inset:0;z-index:20;display:none;place-items:end center;padding:16px;background:rgba(0,0,0,.42)}.modal.open{display:grid}.sheet{width:min(100%,420px);padding:14px;border:1px solid var(--line);border-radius:12px;background:var(--panel);box-shadow:var(--shadow)}.sheet h3{margin:0 0 6px;font-size:18px}.sheet p{margin:0 0 12px;color:var(--muted);font-size:13px;line-height:1.45}.choice-list{display:grid;gap:8px}.choice-btn{width:100%;padding:11px;border:1px solid var(--line);border-radius:8px;background:var(--panel2);color:var(--text);text-align:left;font:inherit}.choice-btn strong{display:block}.choice-btn span{display:block;margin-top:3px;color:var(--muted);font-size:12px}.choice-btn.danger{border-color:color-mix(in srgb,var(--danger) 55%,var(--line));color:var(--danger)}.choice-btn:disabled{opacity:.45}.modal-actions{display:flex;justify-content:flex-end;margin-top:10px}.empty-state{padding:10px;border:1px dashed var(--line);border-radius:7px;background:var(--panel2);color:var(--muted);font-size:12px;text-align:center}@media(max-width:620px){.handoff-strip{grid-template-columns:minmax(0,1fr) minmax(142px,38%)}.handoff{box-shadow:none}}
main{gap:16px}.session-section{display:grid;gap:8px;min-width:0}.history-list{max-height:min(62vh,720px);overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;padding-right:2px}.history-pager{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:8px}.history-jump{display:flex;align-items:center;justify-content:center;gap:6px;min-width:0;color:var(--muted);font-size:calc(12px + var(--font-step))}.history-page-input{width:58px;height:34px;padding:4px 6px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--text);font:inherit;text-align:center}.history-page-input:focus{border-color:var(--accent);outline:2px solid color-mix(in srgb,var(--accent) 24%,transparent);outline-offset:1px}.history-pager button:disabled{opacity:.42}@media(max-width:620px){.history-list{max-height:58vh}}@media(max-width:420px){.history-pager{gap:5px}.history-jump{gap:4px}.history-jump>label{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.history-page-input{width:52px}.history-pager>.mini-btn{padding-inline:7px}}
.sheet{max-height:calc(100vh - 32px);display:flex;flex-direction:column}.sheet p{font:500 12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.choice-list{min-height:0;overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin}.choice-list .choice-btn:first-child{border-color:color-mix(in srgb,var(--accent) 55%,var(--line));background:color-mix(in srgb,var(--accent) 11%,var(--panel));color:var(--accent)}.choice-btn span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.modal-actions{flex:0 0 auto}@media(max-width:620px){.sheet{border-radius:18px 18px 12px 12px}}
.visually-hidden{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}.sheet-heading{display:flex;align-items:flex-start;gap:9px;min-width:0}.sheet-heading-copy{min-width:0;flex:1}.sheet-back{width:36px;min-width:36px;height:36px;display:grid;place-items:center;padding:0;border:1px solid var(--line);border-radius:10px;background:var(--panel2);color:var(--text);font:800 20px/1 var(--app-font)}.sheet-back[hidden]{display:none}.directory-toolbar{display:grid;gap:9px;margin:3px 0 10px}.directory-breadcrumb{display:flex;align-items:center;gap:2px;min-height:34px;padding:3px;border:1px solid var(--line);border-radius:10px;background:var(--panel2);overflow-x:auto;overscroll-behavior-x:contain;scrollbar-width:none}.directory-breadcrumb::-webkit-scrollbar{display:none}.directory-crumb{display:flex;align-items:center;gap:4px;min-width:max-content;padding:5px 7px;border:0;border-radius:7px;background:transparent;color:var(--muted);font:700 12px/1.2 var(--app-font)}.directory-crumb:not(:last-child)::after{content:'›';margin-left:5px;color:var(--muted)}.directory-crumb[aria-current="location"]{background:color-mix(in srgb,var(--accent) 12%,var(--panel));color:var(--accent)}.directory-search{height:40px;display:flex;align-items:center;gap:7px;padding:0 10px;border:1px solid var(--line);border-radius:10px;background:var(--panel2);color:var(--muted)}.directory-search:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 15%,transparent)}.directory-search input{min-width:0;flex:1;padding:0;border:0;outline:0;background:transparent;color:var(--text);font:inherit}.modal.directory-mode{place-items:center;padding:16px}.modal.directory-mode .sheet{width:min(680px,calc(100vw - 32px));height:min(78vh,720px);max-height:calc(100vh - 32px);padding:16px 16px 12px;border-radius:18px}.modal.directory-mode .sheet h3{margin:1px 0 2px}.modal.directory-mode .sheet p{margin:0;color:var(--muted);font:500 12px/1.35 var(--app-font)}.modal.directory-mode .choice-list{display:block;padding:0 2px 10px;overflow-y:auto}.directory-section{display:grid;gap:3px;padding:5px 0 9px}.directory-section+.directory-section{border-top:1px solid color-mix(in srgb,var(--line) 72%,transparent);padding-top:10px}.directory-section-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:2px 7px 4px;color:var(--muted);font-size:10px;font-weight:850;letter-spacing:.1em;text-transform:uppercase}.directory-more{padding:3px 5px;border:0;border-radius:6px;background:transparent;color:var(--accent);font:750 11px/1.2 var(--app-font);letter-spacing:0;text-transform:none}.directory-row{width:100%;min-height:48px;display:grid;grid-template-columns:30px minmax(0,1fr) 20px;align-items:center;gap:8px;padding:7px 8px;border:0;border-radius:10px;background:transparent;color:var(--text);text-align:left;font:inherit}.directory-row:hover,.directory-row:focus-visible{background:color-mix(in srgb,var(--accent) 10%,var(--panel2));outline:none}.directory-row-icon{width:30px;height:30px;display:grid;place-items:center;border-radius:8px;background:color-mix(in srgb,var(--accent) 9%,var(--panel2));font-size:15px}.directory-row-copy{min-width:0}.directory-row strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}.directory-row small{display:block;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font-size:10px}.directory-row-arrow{color:var(--muted);font-size:17px;text-align:center}.directory-empty{padding:22px 10px;color:var(--muted);text-align:center;font-size:12px}.modal.directory-mode .modal-actions{display:grid;grid-template-columns:auto minmax(0,1fr);gap:9px;margin:0 -2px;padding:11px 2px 0;border-top:1px solid var(--line);background:var(--panel)}.directory-primary{min-height:42px;border:1px solid color-mix(in srgb,var(--accent) 55%,var(--line));border-radius:10px;background:var(--accent);color:white;font:800 13px/1.2 var(--app-font)}.directory-cancel{min-height:42px;padding:0 13px}.directory-section[hidden],.directory-row[hidden]{display:none!important}@media(max-width:620px){.modal.directory-mode{place-items:end center;padding:0}.modal.directory-mode .sheet{width:100%;height:min(92vh,760px);height:min(92dvh,760px);max-height:none;padding:15px 13px max(10px,env(safe-area-inset-bottom));border-width:1px 0 0;border-radius:22px 22px 0 0}.modal.directory-mode .modal-actions{padding-bottom:max(2px,env(safe-area-inset-bottom))}.directory-row{min-height:50px}.directory-toolbar{margin-bottom:7px}}
.modal.open.anchored{display:block}.modal.anchored .sheet{position:absolute;left:var(--sheet-left,16px);top:var(--sheet-top,16px);width:min(320px,calc(100vw - 32px))}.new-session-panel{padding:9px;border:1px solid var(--line);border-radius:8px;background:var(--panel);box-shadow:var(--shadow)}.new-session-head{margin-bottom:7px}.launcher-card{border-color:color-mix(in srgb,var(--accent) 34%,var(--line));background:color-mix(in srgb,var(--accent) 6%,var(--panel))}.package-actions{display:flex;align-items:center;justify-content:flex-end;gap:6px}.package-card{touch-action:auto}.send-package{border-color:color-mix(in srgb,var(--accent) 48%,var(--line));background:color-mix(in srgb,var(--accent) 10%,var(--panel));color:var(--accent)}@media(max-width:620px){.handoff-strip{grid-template-columns:minmax(0,1fr)}.handoff,.new-session-panel{box-shadow:none}.new-session-slot{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:420px){.new-session-slot{grid-template-columns:minmax(0,1fr)}}"""
PORTAL_CSS += """
.directory-crumb{display:block;flex:0 0 auto;align-items:initial;gap:0;min-width:0;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.directory-crumb:not(:last-child)::after{content:' ›';margin-left:4px}
.directory-crumb-collapsed{max-width:34px}
.history-tools{display:grid;gap:8px;padding:9px;border:1px solid var(--line);border-radius:10px;background:color-mix(in srgb,var(--panel2) 64%,transparent)}
.history-search{height:40px;display:flex;align-items:center;gap:8px;padding:0 10px;border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--muted)}
.history-search:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 14%,transparent)}
.history-search input{min-width:0;flex:1;padding:0;border:0;outline:0;background:transparent;color:var(--text);font:inherit}
.history-search-clear{width:28px;height:28px;padding:0;border:0;border-radius:7px;background:transparent;color:var(--muted);font:800 16px/1 var(--app-font)}
.history-search-clear:hover,.history-search-clear:focus-visible{background:color-mix(in srgb,var(--accent) 10%,var(--panel2));color:var(--text);outline:none}
.history-filter-row{display:flex;align-items:center;gap:6px;overflow-x:auto;overscroll-behavior-x:contain;scrollbar-width:none}
.history-filter-row::-webkit-scrollbar{display:none}
.history-filter-chip{flex:0 0 auto;min-height:31px;padding:5px 9px;border:1px solid var(--line);border-radius:999px;background:var(--panel);color:var(--muted);font:750 11px/1.1 var(--app-font)}
.history-filter-chip.active{border-color:color-mix(in srgb,var(--accent) 55%,var(--line));background:color-mix(in srgb,var(--accent) 12%,var(--panel));color:var(--accent)}
.history-filter-separator{flex:0 0 auto;width:1px;height:20px;background:var(--line)}
.session-card.state-starting{border-color:color-mix(in srgb,var(--accent2) 48%,var(--line));background:color-mix(in srgb,var(--accent2) 8%,var(--panel))}
.session-card.state-exited{border-color:color-mix(in srgb,var(--danger) 42%,var(--line));background:color-mix(in srgb,var(--danger) 6%,var(--panel));opacity:.82}
.session-card.state-desktop{border-color:color-mix(in srgb,var(--muted) 42%,var(--line))}
.archive-session{color:var(--muted)}
.restore-session{border-color:color-mix(in srgb,var(--accent) 45%,var(--line));background:color-mix(in srgb,var(--accent) 9%,var(--panel));color:var(--accent)}
.settings-row.danger-row{border-color:color-mix(in srgb,var(--danger) 40%,var(--line));color:var(--danger)}
.activity-row{padding:9px 10px;border:1px solid var(--line);border-radius:9px;background:var(--panel2)}
.activity-row strong{display:block;font-size:12px;line-height:1.25}
.activity-row span{display:block;margin-top:3px;color:var(--muted);font-size:10px;line-height:1.35}
@media(max-width:620px){.directory-crumb{max-width:120px}}
"""

PORTAL_JS_TEMPLATE = """let installPrompt=null,lastAnchorRect=null,csrfToken=null;
async function readJsonResponse(response,label){const text=await response.text();let data=null;try{data=JSON.parse(text);}catch(_error){}if(!data||typeof data!=='object'||Array.isArray(data)){const normalized=text.trimStart().toLowerCase(),html=normalized.startsWith('<!doctype html')||normalized.startsWith('<html'),authPage=html&&['cloudflare access','faryo sign in','/cdn-cgi/access'].some(marker=>normalized.includes(marker)),temporary=[502,503,504].includes(response.status),message=authPage||[401,403].includes(response.status)?'Your web sign-in expired. Refresh this page and sign in again.':temporary?'Faryo is restarting or temporarily unavailable. Please retry.':html?`${label} returned a web page instead of API data. Refresh and retry.`:`${label} returned an invalid response.`;const error=new Error(message);error.status=response.status;error.retryable=temporary;throw error;}if(!response.ok||data.ok===false){const error=new Error(data.error||`${label} failed (${response.status})`);error.status=response.status;error.retryable=[502,503,504].includes(response.status);throw error;}return data;}
async function fetchJson(url,options,label){const response=await fetch(url,options);return readJsonResponse(response,label||'Request');}
async function csrfHeaders(){if(!csrfToken){const data=await fetchJson('/api/csrf',{cache:'no-store'},'Sign-in check');csrfToken=data.csrf||'';}return {'X-Faryo-Csrf':csrfToken};}
window.FaryoAppearance?.apply();if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});window.addEventListener('beforeinstallprompt',(event)=>{event.preventDefault();installPrompt=event;const btn=document.getElementById('installApp');if(btn)btn.hidden=false;});document.addEventListener('pointerdown',(event)=>{const el=event.target.closest('button,a,.session-card,.package-card,[role="button"]');if(!el)return;const rect=el.getBoundingClientRect();lastAnchorRect={left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom};},{capture:true,passive:true});document.addEventListener('click',(event)=>{const settings=document.getElementById('settings');if(event.target.closest('#settings>button'))settings.classList.toggle('open');else if(!event.target.closest('#settings'))settings.classList.remove('open');const appearanceBtn=event.target.closest?.('.appearance-btn');if(appearanceBtn?.id==='themeBtn'){window.FaryoAppearance?.cycle('theme');return;}if(appearanceBtn?.id==='fontBtn'){window.FaryoAppearance?.cycle('font');return;}if(appearanceBtn?.id==='sizeBtn'){window.FaryoAppearance?.cycle('size');return;}const installBtn=event.target.closest?.('#installApp');if(installBtn&&installPrompt){installPrompt.prompt();installPrompt=null;installBtn.hidden=true;}});
const WORKBENCH_CACHE_KEY='faryoWorkbenchSnapshot';const labels=__LABELS_JS__,initialHistoryParams=new URLSearchParams(location.search),validPeriods=new Set(['all','today','7d','30d']),validArchives=new Set(['active','archived','all']),initialPeriod=initialHistoryParams.get('period')||'all',initialArchive=initialHistoryParams.get('archive')||'active',historyFilters={q:String(initialHistoryParams.get('q')||'').trim().slice(0,96),period:validPeriods.has(initialPeriod)?initialPeriod:'all',archive:validArchives.has(initialArchive)?initialArchive:'active'};let draggedPackage=null;let assetTargetPackage=null;let handoffTargets=[];let actionBusy=false;let historyPage=Math.max(1,Number.parseInt(initialHistoryParams.get('page')||'1',10)||1),historyTotalPages=1,workbenchRequestGeneration=0,workbenchAbortController=null,historySearchTimer=null;
function historyFilterActive(){return !!historyFilters.q||historyFilters.period!=='all'||historyFilters.archive!=='active';}
function historyRequestQuery(){const params=new URLSearchParams({page:String(historyPage)});if(historyFilters.q)params.set('q',historyFilters.q);if(historyFilters.period!=='all')params.set('period',historyFilters.period);if(historyFilters.archive!=='active')params.set('archive',historyFilters.archive);return params.toString();}
function syncHistoryLocation(){const url=new URL(location.href);for(const key of['page','q','period','archive'])url.searchParams.delete(key);if(historyPage>1)url.searchParams.set('page',String(historyPage));if(historyFilters.q)url.searchParams.set('q',historyFilters.q);if(historyFilters.period!=='all')url.searchParams.set('period',historyFilters.period);if(historyFilters.archive!=='active')url.searchParams.set('archive',historyFilters.archive);history.replaceState(null,'',url);}
function storeWorkbench(data){if(historyFilterActive())return;try{sessionStorage.setItem(WORKBENCH_CACHE_KEY,JSON.stringify({storedAt:Date.now(),data}));}catch(_error){}}
function restoreWorkbench(){if(historyFilterActive()||historyPage!==1)return;try{const cached=JSON.parse(sessionStorage.getItem(WORKBENCH_CACHE_KEY)||'null');if(cached?.data)renderWorkbench(cached.data);}catch(_error){}}
function markRoutes(entries){for(const item of entries||[]){const chip=document.getElementById(`route-${item.id}`);if(!chip)continue;chip.className=`route-chip ${item.state||'error'}`;const state=chip.querySelector('.route-state');if(state){state.textContent=item.stateText||'—';state.title=item.detail||item.stateText||'';}}}
function localSessionTime(item){const ts=Number(item.updatedTs||0);if(!Number.isFinite(ts)||ts<=0)return item.updatedAt||'';const date=new Date(ts*1000),now=new Date(),sameDay=date.toDateString()===now.toDateString();return new Intl.DateTimeFormat(undefined,sameDay?{hour:'2-digit',minute:'2-digit'}:{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(date);}
function clearDropTargets(){document.querySelectorAll('.session-card.drop-target').forEach(el=>el.classList.remove('drop-target'));}function childByKey(container,key){return Array.from(container.children).find(el=>el.dataset.key===key);}function cardSig(item){try{return JSON.stringify(item);}catch(_err){return '';}}function syncChildren(container,items,keyFn,renderFn,emptyText){const list=items||[];if(!list.length){if(container.dataset.empty!==emptyText){container.replaceChildren(empty(emptyText));container.dataset.empty=emptyText;}return;}container.dataset.empty='';const seen=new Set();list.forEach((item,index)=>{const key=String(keyFn(item)),sig=cardSig(item);let node=childByKey(container,key);if(!node||node.dataset.sig!==sig){const next=renderFn(item);next.dataset.key=key;next.dataset.sig=sig;if(node)node.replaceWith(next);node=next;}seen.add(key);const ref=container.children[index];if(ref!==node)container.insertBefore(node,ref||null);});Array.from(container.children).forEach(node=>{if(!seen.has(node.dataset.key||''))node.remove();});}
function packageCard(item){const card=document.createElement('div'),pending=item.status==='pending';card.className='package-card';card.draggable=pending;card.dataset.packageId=item.id;const assets=(item.assets||[]).length,status=pending?'Ready to send':'Delivered',source=item.source||'Faryo',actions=pending?'<div class="package-actions"><button class="mini-btn add-asset" type="button">Add files</button><button class="mini-btn send-package" type="button">Send to…</button></div>':'';card.innerHTML=`<div><strong>${escapeHtml(item.title||'Untitled file package')}</strong><span class="package-meta">${status} · ${assets} file${assets===1?'':'s'} · ${escapeHtml(source)}</span></div>${actions}`;card.querySelectorAll('button').forEach(button=>button.addEventListener('pointerdown',(event)=>event.stopPropagation()));card.querySelector('.add-asset')?.addEventListener('click',(event)=>{event.preventDefault();event.stopPropagation();assetTargetPackage=item.id;document.getElementById('packageAssetInput')?.click();});card.querySelector('.send-package')?.addEventListener('click',(event)=>{event.preventDefault();event.stopPropagation();withBusy(()=>selectPackageTarget(item));});card.addEventListener('dragstart',(event)=>{if(!pending||event.target.closest?.('button')){event.preventDefault();return;}draggedPackage=item.id;event.dataTransfer.setData('text/plain',item.id);card.classList.add('dragging');});card.addEventListener('dragend',()=>{draggedPackage=null;card.classList.remove('dragging');clearDropTargets();});return card;}
function placeSheet(modal){if(!lastAnchorRect){modal.classList.remove('anchored');return;}const margin=16,gap=8,sheet=modal.querySelector('.sheet'),width=Math.min(320,innerWidth-margin*2),center=(lastAnchorRect.left+lastAnchorRect.right)/2;modal.classList.add('open','anchored');const height=sheet.offsetHeight,left=innerWidth<620?(innerWidth-width)/2:Math.max(margin,Math.min(innerWidth-width-margin,center-width/2)),below=lastAnchorRect.bottom+gap,above=lastAnchorRect.top-height-gap,top=below+height+margin<=innerHeight?below:Math.max(margin,above);modal.style.setProperty('--sheet-left',`${left}px`);modal.style.setProperty('--sheet-top',`${top}px`);}
function resetSheetMode(){const modal=document.getElementById('modal'),toolbar=document.getElementById('directoryToolbar'),breadcrumb=document.getElementById('directoryBreadcrumb'),search=document.getElementById('directorySearch');modal.classList.remove('directory-mode');toolbar.hidden=true;breadcrumb.replaceChildren();search.value='';search.oninput=null;}
function sheet(title,body,choices){return new Promise(resolve=>{const modal=document.getElementById('modal'),list=document.getElementById('modalChoices'),actions=document.getElementById('modalActions');resetSheetMode();document.getElementById('modalTitle').textContent=title;document.getElementById('modalBody').textContent=body||'';const done=(value)=>{modal.classList.remove('open','anchored');modal.onclick=null;resolve(value);};list.replaceChildren(...(choices||[]).map(item=>{const element=document.createElement(item.static?'div':'button');element.className=item.static?'activity-row':`choice-btn${item.danger?' danger':''}`;element.innerHTML=`<strong>${escapeHtml(item.label)}</strong>${item.meta?`<span>${escapeHtml(item.meta)}</span>`:''}`;if(!item.static){element.type='button';element.disabled=!!item.disabled;element.addEventListener('click',()=>done(item.value));}return element;}));const cancel=document.createElement('button');cancel.type='button';cancel.className='mini-btn';cancel.textContent='Cancel';cancel.addEventListener('click',()=>done(null));actions.replaceChildren(cancel);modal.onclick=(event)=>{if(event.target===modal)done(null);};placeSheet(modal);modal.classList.add('open');});}
async function notice(title,body){await sheet(title,body,[{label:'OK',value:'ok'}]);}
async function selectPackageTarget(item){const targets=handoffTargets.filter(target=>target.id||target.tmuxSession);if(!targets.length){await notice('No session available','Start or resume a session before sending files.');return;}const choices=targets.map((target,index)=>{const active=!!target.tmuxSession,agent=target.source==='codex-cli'?'Codex':'Runtime',route=target.routeLabel||labels[target.route]||target.route,state=active?'Active':(target.limitReached?'Limit reached':'Resume and send');return{label:target.title||target.id||'Untitled session',meta:`${route} · ${agent} · ${state}`,value:String(index),disabled:!active&&!!target.limitReached};});const selected=await sheet('Send files to a session',item.title||'Choose the destination session.',choices);if(selected===null)return;const target=targets[Number(selected)];if(target)await injectPackage(item.id,target.route,target.tmuxSession||'',target.id||'',target.source||'');}
async function withBusy(task){if(actionBusy)return;actionBusy=true;try{return await task();}catch(error){await notice('Action failed',error.message||String(error));}finally{actionBusy=false;}}
function activityTime(value){const timestamp=Date.parse(String(value||''));if(!Number.isFinite(timestamp))return 'Unknown time';const seconds=Math.max(0,Math.round((Date.now()-timestamp)/1000));if(seconds<60)return 'Just now';if(seconds<3600)return `${Math.floor(seconds/60)}m ago`;if(seconds<86400)return `${Math.floor(seconds/3600)}h ago`;return `${Math.floor(seconds/86400)}d ago`;}
async function showSecurityActivity(){document.getElementById('settings')?.classList.remove('open');const data=await fetchJson('/api/security-activity?limit=30',{cache:'no-store'},'Security activity'),entries=Array.isArray(data.entries)?data.entries:[],actionLabels={start:'Start',resume:'Resume',archive:'Archive',unarchive:'Restore',close:'Close',send:'Send',interrupt:'Interrupt',enter:'Enter',up:'Up',down:'Down','file-inject':'File transfer','revoke-sessions':'Revoke sessions'},rows=entries.map(item=>({static:true,label:`${actionLabels[item.action]||item.action||'Control'} · ${item.result||'unknown'}`,meta:[activityTime(item.time),item.route?labels[item.route]||item.route:'Gateway',item.target||'no target',item.idempotent?'idempotent retry':''].filter(Boolean).join(' · ')}));await sheet('Security activity','Recent control metadata only. Message text, titles and paths are never recorded.',rows.length?rows:[{static:true,label:'No control activity yet',meta:'Actions will appear here after you use Faryo controls.'}]);}
async function revokeSignedInDevices(){document.getElementById('settings')?.classList.remove('open');const confirmed=await sheet('Revoke signed-in devices','This invalidates every inner Faryo login for your account. It does not stop Codex or close tmux.',[{label:'Revoke all Faryo sessions',meta:'You will sign in again on this device.',value:'revoke',danger:true}]);if(confirmed!=='revoke')return;await fetchJson('/api/auth/revoke-all',{method:'POST',headers:{'Content-Type':'application/json',...(await csrfHeaders())},body:JSON.stringify({confirm:'revoke'})},'Revoke sessions');location.href='/logout';}
async function selectNewRoute(entries,label){const online=(entries||[]).filter(e=>['online','slow'].includes(e.state));if(!online.length){await notice('No endpoint online','No online endpoint can start sessions.');return null;}const choices=online.map(e=>({label:`Start on ${e.label||labels[e.id]||e.id}`,meta:`${e.activeCount||0}/${e.maxRunning||0} sessions${e.canCreate?'':' · limit reached'}`,value:e.id,disabled:!e.canCreate}));if(!choices.some(item=>!item.disabled)){await sheet('Agent limit reached','Close a running session first.',choices);return null;}return sheet(`Start ${label}`,`Choose the workstation. A new ${label} session will be created.`,choices);}
async function directoryPage(route,path){const query=path?`?path=${encodeURIComponent(path)}`:'';return fetchJson(`/${route}/api/directories${query}`,{cache:'no-store'},'Directory browser');}
function trimDirectoryPath(value){let path=String(value||'').trim();while(path.length>1&&path.endsWith('/'))path=path.slice(0,-1);return path;}
function directoryName(value){const parts=trimDirectoryPath(value).split('/').filter(Boolean);return parts[parts.length-1]||'Home';}
function directoryCanonical(value,data){const path=trimDirectoryPath(value);if(path==='~'||path.startsWith('~/')){const match=(data.roots||[]).map(item=>({...item,display:trimDirectoryPath(item.displayPath)})).filter(item=>item.path&&item.display.startsWith('~')&&(path===item.display||path.startsWith(item.display+'/'))).sort((a,b)=>b.display.length-a.display.length)[0];if(match)return trimDirectoryPath(match.path)+path.slice(match.display.length);}return path;}
function directoryBreadcrumbItems(data){const current=directoryCanonical(data.path,data),roots=(data.roots||[]).map(item=>({...item,canonical:directoryCanonical(item.path,data)})),root=roots.filter(item=>current===item.canonical||current.startsWith(item.canonical+'/')).sort((a,b)=>b.canonical.length-a.canonical.length)[0];if(!root)return[{label:data.displayPath||directoryName(current),path:data.path,current:true}];const rootLabel=String(root.displayPath||'')==='~'?'~':directoryName(root.canonical),items=[{label:rootLabel,path:root.path,current:current===root.canonical}],tail=current.slice(root.canonical.length).split('/').filter(Boolean);let cursor=root.canonical;for(const part of tail){cursor=(cursor==='/'?'':cursor)+'/'+part;items.push({label:part,path:cursor,current:cursor===current});}if(items.length>3)return[items[0],{label:'…',path:items[items.length-3].path,collapsed:true},...items.slice(-2)];return items;}
function directoryPickerModel(data,recent,query,expanded){const search=String(query||'').trim().toLowerCase(),current=directoryCanonical(data.path,data),parent=directoryCanonical(data.parent,data),roots=(data.roots||[]).map(item=>({...item,canonical:directoryCanonical(item.path,data)})),reserved=new Set([current,parent,...roots.map(item=>item.canonical)].filter(Boolean)),recentSeen=new Set(reserved),allRecent=[];for(const item of recent||[]){const value=String(item.value||item.path||''),canonical=directoryCanonical(value,data);if(!canonical||recentSeen.has(canonical))continue;recentSeen.add(canonical);allRecent.push({kind:'recent',icon:'↺',label:item.label||directoryName(canonical),meta:item.path||value,path:value});}const parentItem=data.parent?{kind:'parent',icon:'↰',label:'..',meta:'Parent folder',path:data.parent}:null,locations=roots.filter(item=>item.canonical&&item.canonical!==current&&!current.startsWith(item.canonical+'/')).map(item=>({kind:'location',icon:'⌂',label:item.displayPath||directoryName(item.canonical),meta:'Configured location',path:item.path})),folders=(data.directories||[]).filter(item=>{const canonical=directoryCanonical(item.path,data);return canonical&&!reserved.has(canonical);}).map(item=>({kind:'folder',icon:'📁',label:item.name||directoryName(item.path),meta:'',path:item.path}));const matches=item=>!search||`${item.label} ${item.meta}`.toLowerCase().includes(search),recentMatches=allRecent.filter(matches),recentVisible=(search||expanded?recentMatches:recentMatches.slice(0,4)),locationVisible=locations.filter(matches),folderVisible=[...(parentItem?[parentItem]:[]),...folders.filter(matches)];return{recent:recentVisible,locations:locationVisible,folders:folderVisible,hasMore:!search&&allRecent.length>4,total:recentVisible.length+locationVisible.length+folderVisible.length};}
function directoryRow(item,done){const button=document.createElement('button');button.type='button';button.className=`directory-row directory-row-${item.kind}`;button.innerHTML=`<span class="directory-row-icon" aria-hidden="true">${item.icon}</span><span class="directory-row-copy"><strong>${escapeHtml(item.label)}</strong>${item.meta?`<small>${escapeHtml(item.meta)}</small>`:''}</span><span class="directory-row-arrow" aria-hidden="true">›</span>`;button.addEventListener('click',()=>done({path:item.path}));return button;}
function directorySection(title,items,done,more){if(!items.length&&!more)return null;const section=document.createElement('section');section.className='directory-section';section.dataset.directorySection=title.toLowerCase();const heading=document.createElement('div');heading.className='directory-section-heading';const label=document.createElement('span');label.textContent=title;heading.appendChild(label);if(more){const button=document.createElement('button');button.type='button';button.className='directory-more';button.textContent='Show all';button.addEventListener('click',more);heading.appendChild(button);}section.append(heading,...items.map(item=>directoryRow(item,done)));return section;}
function directorySheet(data,recent,label){return new Promise(resolve=>{const modal=document.getElementById('modal'),list=document.getElementById('modalChoices'),actions=document.getElementById('modalActions'),toolbar=document.getElementById('directoryToolbar'),breadcrumb=document.getElementById('directoryBreadcrumb'),search=document.getElementById('directorySearch');resetSheetMode();modal.classList.remove('anchored');modal.classList.add('directory-mode');document.getElementById('modalTitle').textContent='Choose working directory';document.getElementById('modalBody').textContent=`Choose where this ${label} session should work.`;toolbar.hidden=false;let expanded=false;const done=value=>{modal.classList.remove('open','anchored','directory-mode');modal.onclick=null;resetSheetMode();resolve(value);},render=()=>{const model=directoryPickerModel(data,recent,search.value,expanded),nodes=[],recentSection=directorySection('Recent',model.recent,done,model.hasMore?()=>{expanded=true;render();}:null),folderSection=directorySection('Folders',model.folders,done,null),locationSection=directorySection('Locations',model.locations,done,null);for(const section of[recentSection,folderSection,locationSection])if(section)nodes.push(section);if(!model.total){const empty=document.createElement('div');empty.className='directory-empty';empty.textContent=search.value?'No matching folders':'This folder has no subfolders';nodes.push(empty);}list.replaceChildren(...nodes);};breadcrumb.replaceChildren(...directoryBreadcrumbItems(data).map(item=>{const button=document.createElement('button');button.type='button';button.className=`directory-crumb${item.collapsed?' directory-crumb-collapsed':''}`;button.textContent=item.label;if(item.current){button.disabled=true;button.setAttribute('aria-current','location');}else button.addEventListener('click',()=>done({path:item.path}));return button;}));search.oninput=render;const cancel=document.createElement('button');cancel.type='button';cancel.className='mini-btn directory-cancel';cancel.textContent='Cancel';cancel.addEventListener('click',()=>done(null));const select=document.createElement('button');select.type='button';select.className='directory-primary';select.textContent=`Start ${label} here`;select.addEventListener('click',()=>done({cwd:String(data.path||''),cwdToken:String(data.selectionToken||'')}));actions.replaceChildren(cancel,select);modal.onclick=event=>{if(event.target===modal)done(null);};render();modal.classList.add('open');requestAnimationFrame(()=>{breadcrumb.scrollLeft=breadcrumb.scrollWidth;});});}
async function selectNewCwd(route,label,cwdChoices){const recent=Array.isArray(cwdChoices?.[route])?cwdChoices[route]:[];let path=String(recent[0]?.value||''),initial=true;while(true){let data;try{data=await directoryPage(route,path);}catch(error){if(initial&&path){path='';initial=false;continue;}throw error;}initial=false;const selected=await directorySheet(data,recent,label);if(selected===null)return null;if(selected.cwd)return selected;path=String(selected.path||'');}}
function newAgentCard(item){const {entries,command,label,cwdChoices}=item,card=document.createElement('button');card.type='button';card.className='session-card launcher-card';card.innerHTML=`<div><div class="session-title">Start ${label}</div><div class="session-meta">New CLI session</div></div><div class="arrow">›</div>`;card.addEventListener('click',()=>withBusy(async()=>{const route=await selectNewRoute(entries,label);if(!route)return;const directory=await selectNewCwd(route,label,cwdChoices);if(directory===null)return;const original=card.innerHTML;card.disabled=true;card.innerHTML=`<div><div class="session-title">Starting ${label}…</div><div class="session-meta">Creating session</div></div><div class="arrow">↗</div>`;try{await agentNew(route,command,directory);}finally{card.disabled=false;card.innerHTML=original;}}));return card;}
function sessionCard(item){const targetSession=item.tmuxSession||'',agentSessionId=item.id||'',source=item.source||'',active=!!targetSession,managed=!!item.managed,archived=!active&&!!item.archived,blocked=!!item.limitReached,lifecycle=String(item.state||(active?(item.agentRunning?'running':'waiting'):(archived?'archived':'resumable'))),canReceive=!['archived','exited','starting'].includes(lifecycle);const card=document.createElement('div');card.className=`session-card state-${lifecycle}${active?'':' inactive'}${lifecycle==='running'?' running':(lifecycle==='waiting'?' waiting':'')}`;card.dataset.route=item.route;card.dataset.session=targetSession;card.dataset.agentSessionId=agentSessionId;card.dataset.source=source;card.dataset.state=lifecycle;const labelsByState={starting:'Starting',running:'Running',waiting:'Waiting',exited:'Exited',desktop:'Desktop',resumable:'Resume',archived:'Archived'},state=blocked&&lifecycle==='resumable'?'Limit reached':(labelsByState[lifecycle]||'Unknown'),ownership=active&&!managed&&lifecycle!=='desktop'?' · Desktop tmux':'',where=item.cwdLabel||item.cwd||'',updatedAt=localSessionTime(item),agent=source==='codex-cli'?'Codex':'Runtime',title=[item.title||item.id||'Untitled session',item.gitLabel||''].filter(Boolean).join(' '),historyAction=lifecycle==='resumable'?'<button class="mini-btn archive-session" type="button">Archive</button>':(lifecycle==='archived'?'<button class="mini-btn restore-session" type="button">Restore</button>':'');card.innerHTML=`<div><div class="session-title">${escapeHtml(title)}</div><div class="session-meta">${escapeHtml(item.routeLabel||labels[item.route]||item.route)} · ${agent}${ownership}${where?` · ${escapeHtml(where)}`:''} · ${escapeHtml(updatedAt)} · ${state}</div></div><div>${active&&managed?'<button class="mini-btn close-session" type="button">Close</button>':(historyAction||`<span class="arrow">${archived||lifecycle==='exited'?'—':'›'}</span>`)}</div>`;card.title=[title,item.cwd||'',updatedAt,state].filter(Boolean).join(' · ');card.addEventListener('click',(event)=>withBusy(async()=>{if(event.target.closest('.close-session')){event.preventDefault();event.stopPropagation();await closeSession(item.route,targetSession);return;}if(event.target.closest('.archive-session')){event.preventDefault();event.stopPropagation();await changeSessionArchived(item,true);return;}if(event.target.closest('.restore-session')){event.preventDefault();event.stopPropagation();await changeSessionArchived(item,false);return;}if(lifecycle==='exited'){event.preventDefault();await notice('Codex exited','Close this managed shell; the Codex thread remains available in Session History.');return;}if(active){location.href=`/${item.route}/?session=${encodeURIComponent(targetSession)}`;return;}if(!agentSessionId)return;event.preventDefault();if(archived){await notice('Archived session','Restore this thread before resuming it.');return;}if(blocked){await notice('Agent limit reached','Close a running session first.');return;}await resumeSession(item.route,agentSessionId,source);}));card.addEventListener('dragover',(event)=>{if(draggedPackage&&agentSessionId&&canReceive){event.preventDefault();card.classList.add('drop-target');}});card.addEventListener('dragleave',()=>card.classList.remove('drop-target'));card.addEventListener('drop',async(event)=>{event.preventDefault();card.classList.remove('drop-target');if(!canReceive)return;const packageId=event.dataTransfer.getData('text/plain')||draggedPackage;if(packageId)await injectPackage(packageId,item.route,targetSession,agentSessionId,source);});return card;}
function newLaunchRequestId(){return globalThis.crypto?.randomUUID?`web-${crypto.randomUUID()}`:`web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,14)}`;}
async function agentNew(route,command,directory){const payload={route,command,client_launch_id:newLaunchRequestId()};if(directory?.cwd){payload.cwd=directory.cwd;payload.cwd_token=directory.cwdToken||'';}const request=async()=>fetchJson('/api/agent/new',{method:'POST',headers:{'Content-Type':'application/json',...(await csrfHeaders())},body:JSON.stringify(payload)},'Start Codex');let data;try{data=await request();}catch(error){if(!error.retryable)throw error;await new Promise(resolve=>setTimeout(resolve,350));data=await request();}location.href=data.redirect;}
async function resumeSession(route,agentSessionId,source){const data=await fetchJson('/api/agent/resume',{method:'POST',headers:{'Content-Type':'application/json',...(await csrfHeaders())},body:JSON.stringify({route,agent_session_id:agentSessionId,source})},'Resume session');location.href=data.redirect||`/${route}/?session=${encodeURIComponent(data.session)}`;}
async function closeSession(route,session){const ok=await sheet('Close Session','This closes the running session. Busy sessions may refuse to close.',[{label:'Close Session',meta:session,value:'ok',danger:true}]);if(ok!=='ok')return;await fetchJson(`/${route}/api/session/close`,{method:'POST',headers:{'Content-Type':'application/json',...(await csrfHeaders())},body:JSON.stringify({session})},'Close session');await refreshWorkbench();}
async function changeSessionArchived(item,archived){if(!item?.route||!item?.id)return;if(archived){const confirmed=await sheet('Archive session','Move this Codex thread out of Current history. You can restore it from the Archived filter.',[{label:'Archive session',meta:'Reversible · conversation content is retained',value:'archive'}]);if(confirmed!=='archive')return;}await fetchJson(`/api/session-history/${archived?'archive':'unarchive'}`,{method:'POST',headers:{'Content-Type':'application/json',...(await csrfHeaders())},body:JSON.stringify({route:item.route,agent_session_id:item.id})},archived?'Archive session':'Restore session');await refreshWorkbench();}
async function injectPackage(packageId,route,session,agentSessionId,source){const payload={package_id:packageId,route};if(session)payload.session=session;if(agentSessionId){payload.agent_session_id=agentSessionId;payload.source=source;}const data=await fetchJson('/api/bridge-inject',{method:'POST',headers:{'Content-Type':'application/json',...(await csrfHeaders())},body:JSON.stringify(payload)},'Send files');location.href=data.redirect||`/${route}/${session?`?session=${encodeURIComponent(session)}`:''}`;}
function renderWorkbench(data){markRoutes(data.entries||[]);const packages=data.inbox||data.packages||[],rawSessions=data.sessions||[],activeSessions=Array.isArray(data.activeSessions)?data.activeSessions:rawSessions.filter(item=>item.tmuxSession),sessions=Array.isArray(data.activeSessions)?rawSessions:rawSessions.filter(item=>!item.tmuxSession),history=data.history||{},applied=history.filter||historyFilters,entries=data.entries||[],cwdChoices=data.agentCwdChoices||{},pkg=packages[0],packageItems=pkg?[pkg]:[],allowedCommands=new Set(data.newSessionCommands||['codex']),launchers=[{id:'new-codex',command:'codex',label:'Codex',entries,cwdChoices}].filter(item=>allowedCommands.has(item.command));historyFilters.q=String(applied.q||'').slice(0,96);historyFilters.period=validPeriods.has(applied.period)?applied.period:'all';historyFilters.archive=validArchives.has(applied.archive)?applied.archive:'active';const seenTargets=new Set();handoffTargets=[...activeSessions,...sessions].filter(item=>{const key=`${item.route}:${item.id||item.tmuxSession||''}`;if(item.archived||!item.route||seenTargets.has(key))return false;seenTargets.add(key);return true;});historyPage=Math.max(1,Number(history.page||historyPage||1));historyTotalPages=Math.max(1,Number(history.totalPages||1));const historyPageInput=document.getElementById('historyPageInput'),historySearchInput=document.getElementById('historySearchInput'),historySearchClear=document.getElementById('historySearchClear');if(historyPageInput){historyPageInput.max=String(historyTotalPages);if(document.activeElement!==historyPageInput)historyPageInput.value=String(historyPage);}if(historySearchInput&&document.activeElement!==historySearchInput)historySearchInput.value=historyFilters.q;if(historySearchClear)historySearchClear.hidden=!historyFilters.q;document.querySelectorAll('[data-history-period]').forEach(button=>{const active=button.dataset.historyPeriod===historyFilters.period;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});document.querySelectorAll('[data-history-archive]').forEach(button=>{const active=button.dataset.historyArchive===historyFilters.archive;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});document.getElementById('packageCount').textContent=pkg?(pkg.status==='pending'?'· Ready':'· Sent'):'· Empty';document.getElementById('activeSessionCount').textContent=`${activeSessions.length} live`;document.getElementById('historyCount').textContent=historyFilterActive()?`${Number(history.total??sessions.length)} matches`:`${Number(history.total??sessions.length)} total`;document.getElementById('historyPageTotal').textContent=String(historyTotalPages);document.getElementById('historyPrev').disabled=history.hasPrevious===false||historyPage<=1;document.getElementById('historyNext').disabled=history.hasNext===false||historyPage>=historyTotalPages;syncChildren(document.getElementById('packageList'),packageItems,item=>`pkg-${item.id}`,packageCard,'Choose files, then send them to a session.');syncChildren(document.getElementById('newSessionSlot'),launchers,item=>item.id,newAgentCard,'No launchers available');syncChildren(document.getElementById('activeSessionList'),activeSessions,item=>`active-${item.route}-${item.tmuxSession||item.id}`,sessionCard,'No active agent sessions');syncChildren(document.getElementById('sessionList'),sessions,item=>`session-${item.route}-${item.id}`,sessionCard,historyFilterActive()?'No sessions match these filters':'No session history');syncHistoryLocation();}
async function refreshWorkbench(){const requestedPage=historyPage,generation=++workbenchRequestGeneration;workbenchAbortController?.abort();const controller=new AbortController();workbenchAbortController=controller;let data;try{data=await fetchJson(`/api/workbench?${historyRequestQuery()}`,{cache:'no-store',signal:controller.signal},'Workbench');}catch(error){if(error?.name==='AbortError')return null;throw error;}finally{if(workbenchAbortController===controller)workbenchAbortController=null;}if(generation!==workbenchRequestGeneration||requestedPage!==historyPage)return data;storeWorkbench(data);renderWorkbench(data);return data;}
async function goToHistoryPage(value){const previous=historyPage,raw=String(value??'').trim(),requested=Number(raw),next=raw&&Number.isInteger(requested)?Math.min(historyTotalPages,Math.max(1,requested)):previous,input=document.getElementById('historyPageInput');if(next===previous){if(input)input.value=String(previous);return;}historyPage=next;if(input)input.value=String(next);try{await refreshWorkbench();document.getElementById('sessionList')?.scrollTo({top:0,behavior:'smooth'});}catch(error){historyPage=previous;if(input)input.value=String(previous);throw error;}}
async function changeHistoryPage(delta){return goToHistoryPage(historyPage+delta);}
function applyHistoryFilter(kind,value){if(kind==='q')historyFilters.q=String(value||'').trim().slice(0,96);else if(kind==='period'&&validPeriods.has(value))historyFilters.period=value;else if(kind==='archive'&&validArchives.has(value))historyFilters.archive=value;historyPage=1;syncHistoryLocation();return refreshWorkbench();}
function scheduleHistorySearch(value){clearTimeout(historySearchTimer);historySearchTimer=setTimeout(()=>{applyHistoryFilter('q',value).catch(()=>{});},250);}
function empty(text){const el=document.createElement('div');el.className='empty-state';el.textContent=text;return el;}
function escapeHtml(value){return String(value).replace(/[&<>"']/g,(ch)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
function fileToAttachment(file){return new Promise((resolve,reject)=>{if(file.size>20*1024*1024){reject(new Error('Attachment must be 20 MB or smaller'));return;}const reader=new FileReader();reader.onload=()=>resolve({file_name:file.name||'attachment',mime_type:file.type||'application/octet-stream',data_url:String(reader.result||'')});reader.onerror=()=>reject(reader.error||new Error('Failed to read attachment'));reader.readAsDataURL(file);});}
async function filesToAttachments(fileList){const files=Array.from(fileList||[]).slice(0,4),attachments=[];for(const file of files)attachments.push(await fileToAttachment(file));return attachments;}
async function createPackage(files){const attachments=await filesToAttachments(files);if(!attachments.length)return;const title=attachments.length===1?attachments[0].file_name:`${attachments.length} files`;await fetchJson('/api/bridge-packages',{method:'POST',headers:{'Content-Type':'application/json',...(await csrfHeaders())},body:JSON.stringify({title,source:'Manual upload',intent:'Send these files to a selected session.',attachments})},'Add files');await refreshWorkbench();}
async function appendAttachmentsToPackage(packageId,files){const attachments=await filesToAttachments(files);if(!attachments.length)return;await fetchJson('/api/bridge-package-assets',{method:'POST',headers:{'Content-Type':'application/json',...(await csrfHeaders())},body:JSON.stringify({package_id:packageId,attachments})},'Add files');await refreshWorkbench();}
document.getElementById('newPackage')?.addEventListener('click',()=>document.getElementById('packageInput')?.click());
document.getElementById('securityActivity')?.addEventListener('click',()=>withBusy(showSecurityActivity));
document.getElementById('revokeSessions')?.addEventListener('click',()=>withBusy(revokeSignedInDevices));
const historySearchInput=document.getElementById('historySearchInput');if(historySearchInput){historySearchInput.value=historyFilters.q;historySearchInput.addEventListener('input',event=>{document.getElementById('historySearchClear').hidden=!event.target.value;scheduleHistorySearch(event.target.value);});}
document.getElementById('historySearchForm')?.addEventListener('submit',event=>{event.preventDefault();clearTimeout(historySearchTimer);applyHistoryFilter('q',historySearchInput?.value||'').catch(()=>{});});
document.getElementById('historySearchClear')?.addEventListener('click',()=>{clearTimeout(historySearchTimer);if(historySearchInput)historySearchInput.value='';applyHistoryFilter('q','').catch(()=>{});historySearchInput?.focus();});
document.querySelectorAll('[data-history-period]').forEach(button=>button.addEventListener('click',()=>applyHistoryFilter('period',button.dataset.historyPeriod).catch(()=>{})));
document.querySelectorAll('[data-history-archive]').forEach(button=>button.addEventListener('click',()=>applyHistoryFilter('archive',button.dataset.historyArchive).catch(()=>{})));
document.getElementById('historyPrev')?.addEventListener('click',()=>withBusy(()=>changeHistoryPage(-1)));
document.getElementById('historyNext')?.addEventListener('click',()=>withBusy(()=>changeHistoryPage(1)));
document.getElementById('historyJump')?.addEventListener('submit',(event)=>{event.preventDefault();const input=document.getElementById('historyPageInput');withBusy(()=>goToHistoryPage(input?.value));});
document.getElementById('packageInput')?.addEventListener('change',async(event)=>{const files=Array.from(event.target.files||[]),button=document.getElementById('newPackage'),label=button?.textContent||'Choose files';event.target.value='';if(!files.length)return;if(button){button.disabled=true;button.textContent='Adding…';}try{await withBusy(()=>createPackage(files));}finally{if(button){button.disabled=false;button.textContent=label;}}});
document.getElementById('packageAssetInput')?.addEventListener('change',async(event)=>{const files=Array.from(event.target.files||[]),packageId=assetTargetPackage;assetTargetPackage=null;event.target.value='';if(packageId&&files.length)await withBusy(()=>appendAttachmentsToPackage(packageId,files));});
const handoffBox=document.getElementById('handoffBox');handoffBox?.addEventListener('dragover',(event)=>{if(event.dataTransfer?.types?.includes('Files')){event.preventDefault();handoffBox.classList.add('drop-ready');}});handoffBox?.addEventListener('dragleave',()=>handoffBox.classList.remove('drop-ready'));handoffBox?.addEventListener('drop',(event)=>{if(!event.dataTransfer?.files?.length)return;event.preventDefault();handoffBox.classList.remove('drop-ready');const files=Array.from(event.dataTransfer.files);withBusy(()=>createPackage(files));});
function initialRefresh(){refreshWorkbench().catch(()=>{document.getElementById('activeSessionList').replaceChildren(empty('Workbench failed to load'));document.getElementById('sessionList').replaceChildren(empty('Workbench failed to load'));});}
function scheduleInitialRefresh(){const run=()=>requestAnimationFrame(()=>setTimeout(initialRefresh,180));if(document.readyState==='complete')run();else window.addEventListener('load',run,{once:true});}
restoreWorkbench();
scheduleInitialRefresh();
setInterval(()=>{if(!document.hidden)refreshWorkbench().catch(()=>{});},15000);"""


def portal_html(username: str, routes: list[str]) -> str:
    safe_user = html_escape(username)
    safe_routes = [route for route in routes if route in BACKENDS]
    chips = []
    for route in safe_routes:
        _host, _port, label = BACKENDS[route]
        chips.append(f'<div class="route-chip" id="route-{route}"><span class="dot"></span><strong>{html_escape(label)}</strong><span class="route-state">…</span></div>')
    chips_html = "\n".join(chips) or '<div class="empty-state">No endpoints available</div>'
    labels_js = "{" + ",".join(f"{json.dumps(route)}:{json.dumps(BACKENDS[route][2], ensure_ascii=False)}" for route in safe_routes) + "}"
    portal_js = PORTAL_JS_TEMPLATE.replace("__LABELS_JS__", labels_js)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>Faryo</title><meta name="theme-color" content="#F6F7F9" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#0F1115" media="(prefers-color-scheme: dark)"><link rel="manifest" href="/manifest.json"><link rel="icon" href="/icons/favicon.png?v=faryo-ui-1" type="image/png"><link rel="apple-touch-icon" href="/icons/pwa-light-192.png"><script src="/appearance.js?v=unified-2"></script><link rel="stylesheet" href="/appearance.css?v=unified-2">
<style nonce="{CSP_NONCE_PLACEHOLDER}">
{PORTAL_CSS}
</style></head><body><div class="shell">
<header><a class="brand" href="/" aria-label="Faryo home"><img class="brand-logo" src="/icons/faryo-mark.png?v=faryo-ui-1" alt=""><div><h1>Faryo</h1><div class="subtitle">{safe_user} · Carry work forward</div></div></a><div class="settings" id="settings"><button class="settings-trigger" type="button" aria-label="Settings"><span class="settings-icon">⚙</span></button><div class="settings-menu" aria-label="Settings panel"><button id="installApp" class="settings-row install-row" type="button" hidden><span><strong>Install app</strong><small>Add Faryo to home screen</small></span><em>↗</em></button><div class="menu-title">Appearance</div><button id="themeBtn" class="settings-row appearance-btn" type="button"><span><strong>Theme</strong><small>System</small></span><em>↻</em></button><button id="fontBtn" class="settings-row appearance-btn" type="button"><span><strong>Font</strong><small>Default</small></span><em>↻</em></button><button id="sizeBtn" class="settings-row appearance-btn" type="button"><span><strong>Size</strong><small>Normal</small></span><em>↻</em></button><div class="menu-title">Security</div><button id="securityActivity" class="settings-row" type="button"><span><strong>Security activity</strong><small>Body-free control audit</small></span><em>›</em></button><button id="revokeSessions" class="settings-row danger-row" type="button"><span><strong>Revoke signed-in devices</strong><small>Keep Codex and tmux running</small></span><em>!</em></button><div class="menu-title">Account</div><a class="settings-row" href="/password"><span><strong>Change password</strong></span><em>›</em></a><a class="settings-row" href="/logout"><span><strong>Sign out this device</strong></span><em>›</em></a></div></div></header>
<nav class="routes" aria-label="Endpoint status">{chips_html}</nav><div class="handoff-strip"><section class="handoff" id="handoffBox" aria-label="Files to session"><div class="handoff-head"><div><div class="eyebrow">Transfer</div><h2>Files to session <span class="count" id="packageCount">· Empty</span></h2></div><button class="mini-btn primary-btn" id="newPackage" type="button">Choose files</button></div><input id="packageInput" type="file" accept="image/*,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.md,.txt,.csv,.json,.rtf" multiple hidden><input id="packageAssetInput" type="file" accept="image/*,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.md,.txt,.csv,.json,.rtf" multiple hidden><div class="package-list" id="packageList"><div class="empty-state">Choose files, then send them to a session.</div></div></section><section class="new-session-panel" aria-labelledby="newSessionTitle"><div class="new-session-head"><div class="eyebrow">Launch</div><h2 id="newSessionTitle">New session</h2></div><div class="new-session-slot" id="newSessionSlot"><div class="empty-state">Loading launchers…</div></div></section></div>
<main><section class="session-section active-section" aria-labelledby="activeSessionsTitle"><div class="section-head"><h2 id="activeSessionsTitle">Active Sessions</h2><span class="count" id="activeSessionCount">Loading</span></div><section class="sessions" id="activeSessionList"><div class="empty-state">Loading active sessions...</div></section></section><section class="session-section history-section" aria-labelledby="sessionHistoryTitle"><div class="section-head"><h2 id="sessionHistoryTitle">Session History</h2><span class="count" id="historyCount">Loading</span></div><div class="history-tools"><form class="history-search" id="historySearchForm" role="search"><span aria-hidden="true">⌕</span><label class="visually-hidden" for="historySearchInput">Search session title or folder</label><input id="historySearchInput" type="search" inputmode="search" autocomplete="off" spellcheck="false" maxlength="96" placeholder="Search title or folder"><button class="history-search-clear" id="historySearchClear" type="button" aria-label="Clear history search" hidden>×</button></form><div class="history-filter-row" aria-label="Session history filters"><button class="history-filter-chip" type="button" data-history-period="all" aria-pressed="true">All time</button><button class="history-filter-chip" type="button" data-history-period="today" aria-pressed="false">Today</button><button class="history-filter-chip" type="button" data-history-period="7d" aria-pressed="false">7 days</button><button class="history-filter-chip" type="button" data-history-period="30d" aria-pressed="false">30 days</button><span class="history-filter-separator" aria-hidden="true"></span><button class="history-filter-chip" type="button" data-history-archive="active" aria-pressed="true">Current</button><button class="history-filter-chip" type="button" data-history-archive="archived" aria-pressed="false">Archived</button><button class="history-filter-chip" type="button" data-history-archive="all" aria-pressed="false">Any status</button></div></div><section class="sessions history-list" id="sessionList"><div class="empty-state">Loading history...</div></section><nav class="history-pager" aria-label="Session history pages"><button class="mini-btn" id="historyPrev" type="button">Prev</button><form class="history-jump" id="historyJump"><label for="historyPageInput">Page</label><input class="history-page-input" id="historyPageInput" type="number" min="1" max="1" step="1" inputmode="numeric" value="1" aria-label="History page"><span>of <span id="historyPageTotal">1</span></span><button class="mini-btn" type="submit">Go</button></form><button class="mini-btn" id="historyNext" type="button">Next</button></nav></section></main>
</div><div class="modal" id="modal"><div class="sheet"><div class="sheet-heading"><div class="sheet-heading-copy"><h3 id="modalTitle"></h3><p id="modalBody"></p></div></div><div id="directoryToolbar" class="directory-toolbar" hidden><nav id="directoryBreadcrumb" class="directory-breadcrumb" aria-label="Current folder"></nav><label class="directory-search"><span class="visually-hidden">Filter folders</span><span aria-hidden="true">⌕</span><input id="directorySearch" type="search" inputmode="search" autocomplete="off" spellcheck="false" placeholder="Filter folders"></label></div><div class="choice-list" id="modalChoices"></div><div class="modal-actions" id="modalActions"></div></div></div><script nonce="{CSP_NONCE_PLACEHOLDER}">
{portal_js}
</script></body></html>'''


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
