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
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

import bcrypt

SHARED_DIR = Path(__file__).resolve().parents[2] / "shared"
SHARED_STATIC_DIR = SHARED_DIR / "static"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
import pd_state

COOKIE_NAME = "faryo_auth"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60
BACKENDS = {
    "hp": ("127.0.0.1", int(os.environ.get("FARYO_HP_OWNER_PORT", "18766")), "HP"),
    "pc": ("127.0.0.1", int(os.environ.get("FARYO_PC_OWNER_PORT", "18765")), "PC"),
    "gcp": ("127.0.0.1", int(os.environ.get("FARYO_GCP_OWNER_PORT", "8765")), "GCP"),
}
SESSION_POLICY = {"gcp": (3, 2), "hp": (4, 4), "pc": (4, 2)}
WORKORDER_RECEIPT_WATCH_INTERVAL_SECONDS = 20
WORKORDER_RECEIPT_WATCH_ATTEMPTS = 90
NEW_SESSION_COMMANDS = {"codex", "claude"}
HISTORY_SESSION_LIMITS = {"less": {"gcp": 3, "hp": 4, "pc": 4}, "more": {"gcp": 5, "pc": 6, "hp": 7}}
HISTORY_TOTAL_LIMITS = {"less": 10, "more": 18}
STATIC_DIR = Path(__file__).resolve().parent / "static"
FARYO_PROFILE_SOURCE = Path(__file__).resolve().parent / "faryo_profile.md"
WORKORDER_TEMPLATE_SOURCE = Path(__file__).resolve().parent / "templates" / "workorder.md"
BRIDGE_PACKAGE_MAX_BYTES = 120 * 1024 * 1024
BRIDGE_ASSET_MAX_BYTES = 20 * 1024 * 1024
BRIDGE_ASSET_LIMIT = 4
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
    "theme_color": "#F7F0E5",
    "background_color": "#F7F0E5",
    "icons": [
        {"src": "/icons/pwa-light-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icons/pwa-light-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}
PWA_SW = """self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',(event)=>{event.waitUntil(caches.keys().then((keys)=>Promise.all(keys.map((key)=>caches.delete(key)))).then(()=>self.clients.claim()));});
self.addEventListener('fetch',()=>{});
"""

OWNER_STATIC_FILES = {"appearance.css", "appearance.js", "app.js", "style.css", "index.html", "compact-rules-codex.js", "compact-rules-claude.js"}
OWNER_STATIC_PREFIXES = ("icons/", "pet/")
GATEWAY_STATIC_FILES = {
    "projects.css": "text/css; charset=utf-8",
    "projects.js": "text/javascript; charset=utf-8",
}
SHARED_STATIC_FILES = {
    "appearance.css": "text/css; charset=utf-8",
    "appearance.js": "text/javascript; charset=utf-8",
}
PROJECT_ITEM_TYPES = {"decision", "action", "watch"}
PROJECT_ITEM_TYPE_LIMIT = 10
PROJECT_BUCKETS = {"S", "A", "B"}
PROJECT_DONE_STATUSES = {"accepted", "done", "skipped", "seen", "rejected", "completed", "closed"}
PROJECT_DEFINITION_SUBMIT_STATUSES = {"submitted", "converted"}
PROJECT_ITEM_STAGES = {
    "awaiting_owner",
    "approved_for_workorder",
    "workorder_created",
    "in_progress",
    "receipt_submitted",
    "needs_fix",
    "paused",
}
PROJECT_BUCKET_ORDER = {"S": 0, "A": 1, "B": 2}

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


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
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

def clean_session_title(value: Any) -> str:
    return display_session_title(value)[:48]

def clean_re(value: str | None, pattern: str) -> str | None:
    value = (value or "").strip(); return value if re.fullmatch(pattern, value) else None


def clean_package_id(value: str | None) -> str | None: return clean_re(value, r"[0-9]+-[a-f0-9]{8}")
def clean_session_id(value: str | None) -> str | None: return clean_re(value, r"[A-Za-z0-9_.:-]{1,80}")
def clean_agent_session_id(value: str | None) -> str | None: return clean_re(value, r"[A-Za-z0-9_.:-]{1,120}")
def clean_agent_launch_command(value: str | None) -> str | None:
    command = Path(str(value or "").strip()).name.lower()
    return command if command in NEW_SESSION_COMMANDS else None


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
        self.mcp_token = (env.get("FARYO_MCP_TOKEN") or env.get("FARYO_GUARD_TOKEN") or "").strip()
        self.mcp_user = env.get("FARYO_MCP_USER", "").strip()
        self.users = self.load_users(auth)
        self.owner_tokens = self.load_owner_tokens(env)
        self.portal_dir = portal_dir
        self.cookie_secret = load_secret(secret_file)
        self.guard_token = env.get("FARYO_GUARD_TOKEN", "")
        self.bridge_root = secret_file.parent / "bridge-packages"
        self.project_workbench_index = secret_file.parent / "project-workbench.jsonl"
        self.project_downlink_root = secret_file.parent / "project-workbench-downlinks"
        self.gateway_home = secret_file.parent.parent
        self.faryo_profile_name = env.get("FARYO_CONTROLLER_CODEX_PROFILE", "faryo").strip() or "faryo"
        self.faryo_session_title = clean_session_title(env.get("FARYO_CONTROLLER_SESSION_TITLE") or "Faryo")
        self.faryo_work_root = Path(env.get("FARYO_CONTROLLER_WORK_ROOT", str(Path.home()))).expanduser()
        self.faryo_project_root = Path(env.get("FARYO_CONTROLLER_PROJECT_ROOT", str(Path.home() / ".faryo" / "projects" / "faryo"))).expanduser()
        self.faryo_code_root = Path(env.get("FARYO_CONTROLLER_CODE_ROOT", str(Path(__file__).resolve().parents[3]))).expanduser()
        self.owner_project_roots = self.load_owner_project_roots(env)
        self.faryo_codex_home = Path(env.get("CODEX_HOME") or os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")).expanduser()
        self.faryo_codex_config = self.faryo_codex_home / f"{self.faryo_profile_name}.config.toml"
        self.faryo_codex_state = self.faryo_codex_home / "state_5.sqlite"
        self.faryo_profile_runtime = self.gateway_home / "codex" / "faryo-profile.md"
        self.bridge_root.mkdir(parents=True, exist_ok=True)
        self.project_downlink_root.mkdir(parents=True, exist_ok=True)

    def install_faryo_codex_profile(self) -> None:
        self.faryo_work_root.mkdir(parents=True, exist_ok=True)
        self.faryo_project_root.mkdir(parents=True, exist_ok=True)
        self.faryo_profile_runtime.parent.mkdir(parents=True, exist_ok=True)
        self.faryo_codex_home.mkdir(parents=True, exist_ok=True)
        profile_text = FARYO_PROFILE_SOURCE.read_text(encoding="utf-8") + "\n".join([
            "",
            "## Runtime Paths",
            "",
            f"- Faryo controller work root: `{self.faryo_work_root}`",
            f"- Faryo project truth root: `{self.faryo_project_root}`",
            f"- Faryo code root: `{self.faryo_code_root}`",
            f"- Gateway workbench projection: `{self.project_workbench_index}`",
            f"- Gateway downlink packages: `{self.project_downlink_root}`",
            "",
        ])
        self.faryo_profile_runtime.write_text(profile_text, encoding="utf-8")
        config_text = "\n".join([
            "# Generated by Faryo Gateway. Do not edit here; update apps/gateway/gcp-gateway/faryo_profile.md.",
            'model = "gpt-5.5"',
            'model_reasoning_effort = "high"',
            'personality = "pragmatic"',
            'approval_policy = "on-request"',
            'sandbox_mode = "workspace-write"',
            f"model_instructions_file = {json.dumps(str(self.faryo_profile_runtime))}",
            "",
            f'[projects.{json.dumps(str(self.faryo_work_root))}]',
            'trust_level = "trusted"',
            "",
        ])
        self.faryo_codex_config.write_text(config_text, encoding="utf-8")

    def load_owner_project_roots(self, env: dict[str, str]) -> dict[str, str]:
        roots: dict[str, str] = {}
        default_root = str(Path.home() / "brain" / "projects")
        for route in BACKENDS:
            value = (
                env.get(f"FARYO_{route.upper()}_PROJECTS_ROOT")
                or env.get(f"FARYO_{route.upper()}_PROJECT_ROOT")
                or default_root
            ).strip()
            roots[route] = str(Path(value).expanduser())
        return roots

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
            routes = [route for route in payload.get("routes", list(BACKENDS)) if route in BACKENDS] or list(BACKENDS)
            default_route = str(payload.get("default_route") or (routes[0] if routes else "gcp"))
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
        assets = package.get("assets") if isinstance(package.get("assets"), list) else []
        package["assets"] = assets + self.save_bridge_assets(package_id, self.bridge_root / package_id, asset_sources[:BRIDGE_ASSET_LIMIT], len(assets) + 1)
        package["prompt"] = str(package.get("prompt") or "").strip() or self.attachment_only_prompt(str(package.get("title") or "Handoff package")); self.update_bridge_package(package); return package

    def list_bridge_packages(self, username: str, status: str | None = None) -> list[dict[str, Any]]:
        packages = [p for p in (self.bridge_package(path.parent.name, username) for path in self.bridge_root.glob("*/package.json")) if p and (not status or p.get("status") == status)]
        return sorted(packages, key=lambda item: int(item.get("updated_at") or item.get("created_at") or 0), reverse=True)

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

    def log_message(self, fmt: str, *args: Any) -> None:
        safe_path = self.path.split("?", 1)[0]
        print("[%s] %s %s" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), self.command, safe_path), flush=True)

    def do_OPTIONS(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/mcp":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", "*")
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
        if not username and parsed.path == "/api/faryo/status":
            username = self.controller_token_username()
        if parsed.path == "/login":
            if username:
                self.redirect(self.safe_next(parsed))
                return
            self.write_login_page(self.safe_next(parsed))
            return
        if parsed.path == "/favicon.ico":
            self.write_icon("favicon.ico")
            return
        if parsed.path == "/api/guard-health":
            self.write_guard_health()
            return
        if parsed.path == "/logout":
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Set-Cookie", self.expired_cookie())
            self.send_header("Location", "/login")
            self.end_headers()
            return
        if not username and self.is_api_path(parsed.path):
            self.write_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        if not username:
            self.redirect("/login?" + urlencode({"next": self.request_target()}))
            return
        if parsed.path == "/api/gateway-status":
            routes = self.config.user_routes(username)
            self.write_json({"ok": True, "entries": [backend_status(route) for route in routes]}, HTTPStatus.OK)
            return
        if parsed.path == "/api/workbench":
            history_mode = parse_qs(parsed.query).get("history", ["less"])[0]
            self.write_json(self.workbench_payload(username, history_mode), HTTPStatus.OK)
            return
        if parsed.path == "/api/project-workbench":
            self.write_json(self.read_project_workbench(username), HTTPStatus.OK)
            return
        if parsed.path == "/api/project-workbench/git-status":
            self.write_json({"ok": True, "statuses": self.project_git_statuses(username)}, HTTPStatus.OK)
            return
        if parsed.path == "/api/faryo/status":
            self.handle_faryo_status(username)
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
        if parsed.path == "/projects":
            self.write_static_file("projects.html", "text/html; charset=utf-8", "no-store")
            return
        if parsed.path.lstrip("/") in GATEWAY_STATIC_FILES:
            filename = parsed.path.lstrip("/")
            self.write_static_file(filename, GATEWAY_STATIC_FILES[filename], "no-store")
            return
        if parsed.path == "/":
            self.serve_portal(username)
            return
        self.write_not_found(parsed.path)

    def write_guard_health(self) -> None:
        token = self.headers.get("X-Faryo-Guard-Token", "")
        if not self.config.guard_token or not hmac.compare_digest(token, self.config.guard_token):
            self.write_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN)
            return
        gcp_status = backend_status("gcp")
        ok = gcp_status.get("state") in {"online", "slow"}
        status = HTTPStatus.OK if ok else HTTPStatus.SERVICE_UNAVAILABLE
        self.write_json({"ok": ok, "gcp": gcp_status, "updatedAt": int(time.time())}, status)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/mcp":
            self.handle_mcp_post(parsed)
            return
        if parsed.path == "/login":
            self.handle_login(parsed)
            return
        if parsed.path == "/api/project-workbench/sync":
            self.handle_project_workbench_sync()
            return
        if parsed.path == "/api/project-workbench/downlink/claim":
            self.handle_project_workbench_downlink_claim()
            return
        if parsed.path == "/api/project-workbench/downlink/ack":
            self.handle_project_workbench_downlink_ack()
            return
        controller_paths = {"/api/faryo/dispatch", "/api/faryo/start", "/api/faryo/workorder/verify"}
        flex_token_paths = {"/api/project-workbench/transition"}
        if parsed.path in controller_paths:
            username = self.controller_token_username()
        elif parsed.path in flex_token_paths:
            username = self.controller_token_username() or self.current_username()
        else:
            username = self.current_username()
        if not username:
            self.write_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        if parsed.path == "/password":
            self.handle_password_change(username)
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
        if parsed.path == "/api/project-workbench":
            self.handle_project_workbench_save()
            return
        if parsed.path == "/api/project-workbench/submit-stage":
            self.handle_project_workbench_submit(username)
            return
        if parsed.path == "/api/project-workbench/sync-project":
            self.handle_project_workbench_sync_project(username)
            return
        if parsed.path == "/api/project-workbench/transition":
            self.handle_project_workbench_transition(username)
            return
        if parsed.path == "/api/project-workbench/direction":
            self.handle_project_direction(username)
            return
        if parsed.path == "/api/project-workbench/stage-state":
            self.handle_project_stage_state(username)
            return
        if parsed.path == "/api/project-workbench/stage-dod":
            self.handle_project_stage_dod(username)
            return
        if parsed.path == "/api/project-workbench/import":
            self.handle_project_workbench_import(username)
            return
        if parsed.path == "/api/faryo/start":
            self.handle_faryo_start(username)
            return
        if parsed.path == "/api/faryo/dispatch":
            self.handle_faryo_dispatch(username)
            return
        if parsed.path == "/api/faryo/workorder/verify":
            self.handle_faryo_workorder_verify(username)
            return
        if parsed.path == "/api/agent/new":
            self.handle_agent_new(username)
            return
        if parsed.path == "/api/agent/resume":
            self.handle_agent_resume(username)
            return
        route = self.route_for(parsed)
        if route:
            self.proxy(parsed, route, username)
            return
        self.write_not_found(parsed.path)

    def handle_mcp_get(self, parsed: Any) -> None:
        if not self.require_mcp_token():
            return
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED); self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Allow", "POST, OPTIONS"); self.send_header("Cache-Control", "no-store"); self.end_headers()

    def handle_mcp_post(self, parsed: Any) -> None:
        if not self.require_mcp_token():
            return
        try: payload = self.read_json_payload(BRIDGE_PACKAGE_MAX_BYTES)
        except ValueError as exc: self.write_mcp_json(self.mcp_error(None, -32700, str(exc)), HTTPStatus.BAD_REQUEST); return
        try: response = self.mcp_response(payload)
        except ValueError as exc: self.write_mcp_json(self.mcp_error(None, -32700, str(exc)), HTTPStatus.BAD_REQUEST); return
        if response is None: self.send_response(HTTPStatus.ACCEPTED); self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers(); return
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

    def write_mcp_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8"); self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.write_bytes(body)

    def require_mcp_token(self) -> bool:
        auth = self.headers.get("Authorization", "").strip()
        token = self.headers.get("X-Faryo-Mcp-Token", "").strip()
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if self.config.mcp_token and token and hmac.compare_digest(token, self.config.mcp_token):
            return True
        self.write_mcp_json(self.mcp_error(None, -32001, "unauthorized"), HTTPStatus.UNAUTHORIZED)
        return False

    def handle_login(self, parsed: Any) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(min(length, 8192)).decode("utf-8", errors="replace")
        form = parse_qs(raw)
        username = form.get("username", [""])[0].strip()
        password = form.get("password", [""])[0]
        next_target = form.get("next", [self.safe_next(parsed)])[0] or "/"
        user = self.config.user(username)
        ok = bool(user) and bcrypt.checkpw(password.encode("utf-8"), self.config.password_hash(username))
        if not ok:
            self.write_login_page(self.safe_target(next_target), error="Invalid username or password")
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Set-Cookie", self.auth_cookie(username))
        self.send_header("Location", self.safe_target(next_target))
        self.end_headers()

    def handle_password_change(self, username: str) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(min(length, 8192)).decode("utf-8", errors="replace")
        form = parse_qs(raw)
        current = form.get("current_password", [""])[0]
        new_password = form.get("new_password", [""])[0]
        confirm = form.get("confirm_password", [""])[0]
        if not bcrypt.checkpw(current.encode("utf-8"), self.config.password_hash(username)):
            self.write_password_page(error="Current password is incorrect")
            return
        if len(new_password) < 12:
            self.write_password_page(error="New password must be at least 12 characters")
            return
        if new_password != confirm:
            self.write_password_page(error="New password confirmation does not match")
            return
        self.config.set_password(username, new_password)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Set-Cookie", self.auth_cookie(username))
        self.send_header("Location", "/?password=changed")
        self.end_headers()


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

    def read_project_workbench(self, username: str) -> dict[str, Any]:
        return {"ok": True, "workbench": self.project_workbench_payload(username)}

    def project_workbench_payload(self, username: str | None = None) -> dict[str, Any]:
        return {"projects": self.read_project_rows()}

    def project_git_statuses(self, username: str) -> dict[str, dict[str, Any] | None]:
        return {row["id"]: self.project_git_status(username, row) for row in self.read_project_rows()}

    def project_git_status(self, username: str, row: dict[str, Any]) -> dict[str, Any] | None:
        route = self.clean_owner_route(row.get("owner_route"))
        if not route or not self.config.allowed_route(username, route):
            return None
        for cwd in self.project_worker_cwd_candidates(row)[:3]:
            result = self.owner_json_request(route, "/api/project-workbench/git-status", {"project_root": cwd}, username, timeout=1.5)
            if result.get("ok"):
                status = result.get("gitStatus")
                return status if isinstance(status, dict) else None
        return None

    def handle_project_workbench_save(self) -> None:
        try:
            payload = self.read_json_body(128 * 1024)
            self.project_rows_from_payload(payload, truth=False, overview=True)
            self.write_json({"ok": True, "workbench": self.project_workbench_payload()}, HTTPStatus.OK)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_project_workbench_sync_project(self, username: str) -> None:
        try:
            payload = self.read_json_body(512 * 1024)
            scope = self.project_downlink_scope(payload)
            rows = self.project_rows_from_payload(payload, write=False, truth=True, overview=False)
            target_rows, downlink = self.sync_project_downlinks(username, rows, payload, scope)
            if scope == "definition" and target_rows:
                rows = self.rows_with_definition_sync(rows, target_rows, downlink)
                self.write_project_rows(rows)
            elif downlink.get("status") == "applied":
                self.write_project_rows(rows)
            self.write_json({
                "ok": True,
                "workbench": self.project_workbench_payload(),
                "downlink": downlink,
            }, HTTPStatus.OK)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_project_workbench_submit(self, username: str) -> None:
        try:
            payload = self.read_json_body(64 * 1024)
            rows = self.read_project_rows()
            scope = "project" if payload.get("submit_scope") == "project" else "global"
            active_rows = self.active_project_rows(rows)
            prompt_rows = self.project_submit_target_rows(rows, payload) if scope == "project" else active_rows
            if scope == "project" and not prompt_rows:
                raise ValueError("notify_project_ids must target at least one active project")
            unsynced = [row["id"] for row in prompt_rows if row.get("definition_sync", {}).get("status") != "applied"]
            if unsynced:
                raise ValueError("definition sync must be applied: " + ", ".join(unsynced))
            faryo = self.wake_faryo_after_project_submit(username, prompt_rows, scope)
            if not faryo.get("ok"):
                self.write_json({"ok": False, "error": faryo.get("error") or "faryo controller wake failed", "faryo": faryo}, HTTPStatus.BAD_GATEWAY)
                return
            target_ids = {row["id"] for row in prompt_rows}
            for index, row in enumerate(rows):
                if row["id"] in target_ids:
                    rows[index] = self.clean_project_row({**row, "definition_submit": self.project_definition_submit(row, "submitted")}, int(row.get("rank") or index + 1))
            self.write_project_rows(rows)
            self.write_json({
                "ok": True,
                "workbench": self.project_workbench_payload(),
                "faryo": faryo,
            }, HTTPStatus.OK)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def project_rows_from_payload(self, payload: dict[str, Any], write: bool = True, truth: bool = True, overview: bool = True) -> list[dict[str, Any]]:
        source = payload.get("projects")
        if not isinstance(source, list):
            raise ValueError("projects must be a list")
        rows = self.project_projection_rows_from_ui(source, truth, overview)
        if write:
            self.write_project_rows(rows)
        return rows

    def project_projection_rows_from_ui(self, source: list[Any], truth: bool = True, overview: bool = True) -> list[dict[str, Any]]:
        existing = {row["id"]: row for row in self.read_project_rows()}
        rows: list[dict[str, Any]] = []
        for index, project in enumerate(source, 1):
            if not isinstance(project, dict):
                continue
            project_id = self.project_id(project)
            previous = existing.get(project_id)
            if not previous:
                if truth:
                    rows.append(self.clean_project_row(project, index))
                continue
            row = dict(previous)
            if truth:
                for key in ("name", "brief", "current_d"):
                    if key in project:
                        row[key] = self.compact_text(project.get(key))
                if isinstance(project.get("definition"), dict):
                    row["definition"] = project["definition"]
            if overview:
                row["bucket"] = self.clean_project_bucket(project.get("bucket") or previous.get("bucket"))
                row["rank"] = self.clean_rank(project.get("rank") or index)
                if "archived" in project:
                    row["archived"] = bool(project.get("archived"))
            rows.append(self.clean_project_row(row, index))
        missing = set(existing) - {self.project_id(project) for project in source if isinstance(project, dict)}
        rows.extend(existing[project_id] for project_id in missing)
        return rows

    def project_submit_prompt(self, rows: list[dict[str, Any]], scope: str) -> str:
        projects = []
        for row in self.sorted_project_rows(self.active_project_rows(rows)):
            definition = row.get("definition") if isinstance(row.get("definition"), dict) else {}
            project = {"id": row["id"], "name": row["name"], "owner_route": row.get("owner_route") or "", "workbench_path": row.get("workbench_path") or "", "definition_hash": pd_state.project_definition_downlink_hash(row["id"], definition)}
            project.update({"brief": row.get("brief") or ""})
            project.update({key: value for key in ("current_stage_id", "current_stage_title", "stage_goal", "stage_state", "stage_dod", "stage_dod_done", "stage_out_of_scope") if (value := definition.get(key)) not in ("", [], None)})
            projects.append(project)
        payload = {"event": "project_stage_submit", "scope": scope, "projects": projects}
        return "\n".join([
            "项目阶段定义已提交，请接棒处理。",
            "只处理 payload.projects 内本次已保存的定义；先核对 definition_hash（定义哈希）与项目真值一致，异常只报阻塞。",
            "基于阶段目标和 DoD 拟定待 Owner 裁决的 item（事项），用 item_created（事项创建）写入 awaiting_owner（待裁决）；不要创建 WO（工单）或 worker（施工会话）。",
            "decision（裁决项）如需 Owner 选择，写 decision_prompt（裁决输入定义）；item_created 必须带回对应 definition_hash。",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        ])

    def wake_faryo_after_project_submit(self, username: str, rows: list[dict[str, Any]], scope: str) -> dict[str, Any]:
        result = self.ensure_faryo_controller(username, self.project_submit_prompt(rows, scope))
        return {"ok": bool(result.get("ok")), "session": result.get("session") or "", "error": result.get("error") or ""}

    def handle_project_stage_state(self, username: str) -> None:
        try:
            payload = self.read_json_body(8 * 1024)
            self.update_project_definition_row(username, payload, lambda definition: pd_state.definition_with_stage_state(definition, payload.get("stage_state")))
            self.write_json({"ok": True, "workbench": self.project_workbench_payload(username)}, HTTPStatus.OK)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_project_stage_dod(self, username: str) -> None:
        try:
            payload = self.read_json_body(16 * 1024)
            self.update_project_definition_row(username, payload, lambda definition: pd_state.definition_with_stage_dod_update(definition, payload))
            self.write_json({"ok": True, "workbench": self.project_workbench_payload(username)}, HTTPStatus.OK)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_project_direction(self, username: str) -> None:
        try:
            payload = self.read_json_body(16 * 1024)
            project_id = self.project_id({"id": payload.get("project_id")})
            rows = self.read_project_rows()
            for index, row in enumerate(rows):
                if row["id"] != project_id:
                    continue
                route = self.clean_owner_route(row.get("owner_route"))
                if not route or not self.config.allowed_route(username, route):
                    raise ValueError("project route is not allowed")
                updated = dict(row)
                if "brief" in payload:
                    updated["brief"] = self.compact_text(payload.get("brief"))
                if "stage_goal" in payload:
                    stage_goal = self.compact_text(payload.get("stage_goal"))
                    if not stage_goal:
                        raise ValueError("stage_goal is required")
                    definition = pd_state.clean_project_definition(row.get("definition"))
                    definition["stage_goal"] = stage_goal
                    updated["current_d"] = stage_goal
                    updated["definition"] = definition
                rows[index] = self.clean_project_row(updated, int(row.get("rank") or index + 1))
                self.write_project_rows(rows)
                self.write_json({"ok": True, "workbench": self.project_workbench_payload(username)}, HTTPStatus.OK)
                return
            raise ValueError("project not found")
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def update_project_definition_row(self, username: str, payload: dict[str, Any], update: Callable[[dict[str, Any]], dict[str, Any]]) -> tuple[dict[str, Any], str]:
        project_id = self.project_id({"id": payload.get("project_id")})
        rows = self.read_project_rows()
        for index, row in enumerate(rows):
            if row["id"] != project_id:
                continue
            route = self.clean_owner_route(row.get("owner_route"))
            if not route or not self.config.allowed_route(username, route):
                raise ValueError("project route is not allowed")
            updated = dict(row)
            updated["definition"] = update(pd_state.clean_project_definition(row.get("definition")))
            rows[index] = self.clean_project_row(updated, int(row.get("rank") or index + 1))
            self.write_project_rows(rows)
            return rows[index], route
        raise ValueError("project not found")

    def handle_project_workbench_import(self, username: str) -> None:
        try:
            payload = self.read_json_body(64 * 1024)
            owner_route = self.clean_owner_route(payload.get("owner_route") or payload.get("owner"))
            project_root = self.compact_text(payload.get("project_root") or payload.get("path"))
            if not owner_route:
                raise ValueError("owner_route is required")
            if not project_root:
                raise ValueError("project_root is required")
            result = self.owner_json_request(owner_route, "/api/project-workbench/import", {"project_root": project_root}, username, timeout=15)
            if not result.get("ok"):
                raise ValueError(self.compact_text(result.get("error")) or "import failed")
            project = result.get("project")
            if not isinstance(project, dict):
                raise ValueError("owner returned no project")
            row = self.merge_project_import(project, owner_route)
            self.write_json({"ok": True, "project": row, "workbench": self.project_workbench_payload()}, HTTPStatus.OK)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_project_workbench_sync(self) -> None:
        if not self.require_project_sync_owner():
            return
        try:
            payload = self.read_json_body(512 * 1024)
            source = payload.get("projects")
            if not isinstance(source, list):
                raise ValueError("projects must be a list")
            mode = self.compact_text(payload.get("mode")) or "merge"
            rows = self.project_sync_rows([project for project in source if isinstance(project, dict)], self.project_sync_owner_route(), mode)
            self.write_project_rows(rows)
            self.write_json({"ok": True, "workbench": self.project_workbench_payload()}, HTTPStatus.OK)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def require_project_sync_owner(self) -> bool:
        if self.project_sync_owner_route():
            return True
        self.write_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN)
        return False

    def project_sync_owner_route(self) -> str:
        owner_label = self.headers.get("X-Faryo-Owner-Label", "").strip().lower()
        owner_route = owner_label if owner_label in BACKENDS else ""
        owner_token = self.headers.get("X-Owner-Token", "")
        if owner_route and hmac.compare_digest(owner_token, self.config.owner_token(owner_route)):
            return owner_route
        return ""

    def handle_project_workbench_downlink_claim(self) -> None:
        if not self.require_project_sync_owner():
            return
        try:
            payload = self.read_json_body(64 * 1024)
            package = self.project_downlink_package(str(payload.get("package_id") or ""))
            if not package:
                raise ValueError("downlink package not found")
            if package.get("target") != self.project_sync_owner_route():
                self.write_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            self.write_json({"ok": True, "package": package}, HTTPStatus.OK)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_project_workbench_downlink_ack(self) -> None:
        if not self.require_project_sync_owner():
            return
        try:
            payload = self.read_json_body(64 * 1024)
            package_id = str(payload.get("package_id") or "")
            package = self.project_downlink_package(package_id)
            if not package:
                raise ValueError("downlink package not found")
            if package.get("target") != self.project_sync_owner_route():
                self.write_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return
            ack_ok = bool(payload.get("ok"))
            status = str(payload.get("status") or ("applied" if ack_ok else "failed")).strip() or "failed"
            message = self.compact_text(payload.get("message"))
            hash_error = self.project_downlink_hash_error(package, payload) if ack_ok else ""
            if hash_error:
                ack_ok = False
                status = "failed"
                message = hash_error
            applied_count = payload.get("applied")
            package["status"] = status
            package["ack"] = {
                "ok": ack_ok,
                "status": status,
                "message": message,
                "applied": applied_count if ack_ok and isinstance(applied_count, int) else 0,
                "updated_at": now_ts(),
            }
            if ack_ok:
                package["notice"] = {"ok": True, "updated_at": now_ts()}
            self.write_project_downlink_package(package)
            self.write_json({"ok": True, "package": {"id": package["id"], "status": package["status"]}}, HTTPStatus.OK)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def project_sync_rows(self, source: list[dict[str, Any]], owner_route: str, mode: str = "merge") -> list[dict[str, Any]]:
        if mode not in {"merge", "replace_owner"}:
            raise ValueError("invalid project sync mode")
        existing_rows = self.read_project_rows()
        existing = {row.get("id"): row for row in existing_rows}
        incoming_ids = {self.project_id(project) for project in source}
        if mode == "replace_owner":
            rows = [row for row in existing_rows if row.get("owner_route") != owner_route]
        else:
            rows = [row for row in existing_rows if row.get("id") not in incoming_ids]
        for index, project in enumerate(source, 1):
            project_id = self.project_id(project)
            previous = existing.get(project_id) or {}
            row = dict(project)
            if not row.get("bucket"):
                row["bucket"] = previous.get("bucket") or "B"
            if not row.get("rank"):
                row["rank"] = previous.get("rank") or index
            if not row.get("path"):
                row["path"] = previous.get("path") or ""
            if not row.get("owner_route"):
                row["owner_route"] = previous.get("owner_route") or owner_route
            if not row.get("workbench_path"):
                row["workbench_path"] = previous.get("workbench_path") or row.get("path") or ""
            if not row.get("code_root"):
                row["code_root"] = previous.get("code_root") or ""
            if "definition" not in row and isinstance(previous.get("definition"), dict):
                row["definition"] = previous["definition"]
                if isinstance(previous.get("definition_sync"), dict):
                    row["definition_sync"] = previous["definition_sync"]
            elif isinstance(project.get("definition"), dict):
                if isinstance(previous.get("definition_sync"), dict):
                    row["definition_sync"] = previous["definition_sync"]
                else:
                    row["definition_sync"] = self.project_definition_sync(row, "pending")
            if isinstance(previous.get("definition_submit"), dict) and "definition_submit" not in row:
                row["definition_submit"] = previous["definition_submit"]
            row.setdefault("archived", previous.get("archived"))
            rows.append(self.clean_project_row(row, index))
        return rows

    def merge_project_import(self, project: dict[str, Any], owner_route: str) -> dict[str, Any]:
        rows = self.read_project_rows()
        project_id = self.project_id(project)
        previous = next((row for row in rows if row.get("id") == project_id), {})
        merged = dict(previous)
        merged.update(project)
        merged["owner_route"] = owner_route
        if not merged.get("bucket"):
            merged["bucket"] = previous.get("bucket") or "B"
        if not merged.get("rank"):
            merged["rank"] = previous.get("rank") or len(rows) + 1
        if isinstance(project.get("definition"), dict):
            if isinstance(previous.get("definition_sync"), dict):
                merged["definition_sync"] = previous["definition_sync"]
            else:
                merged["definition_sync"] = self.project_definition_sync(merged, "pending")
        row = self.clean_project_row(merged, int(merged.get("rank") or len(rows) + 1))
        self.write_project_rows([item for item in rows if item.get("id") != row["id"]] + [row])
        return row

    def project_downlink_target_rows(self, rows: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_ids = payload.get("downlink_project_ids")
        if raw_ids is None:
            return []
        return self.project_rows_by_ids(rows, raw_ids, "downlink_project_ids")

    def project_submit_target_rows(self, rows: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_ids = payload.get("notify_project_ids")
        if raw_ids is None:
            return []
        return self.project_rows_by_ids(rows, raw_ids, "notify_project_ids")

    def project_rows_by_ids(self, rows: list[dict[str, Any]], raw_ids: Any, field: str) -> list[dict[str, Any]]:
        if not isinstance(raw_ids, list):
            raise ValueError(f"{field} must be a list")
        ids = {self.project_id({"id": item}) for item in raw_ids if str(item or "").strip()}
        if not ids:
            return []
        by_id = {row["id"]: row for row in rows}
        missing = sorted(ids - set(by_id))
        if missing:
            raise ValueError(f"unknown {field}: " + ", ".join(missing))
        return [row for row in self.sorted_project_rows(rows) if row["id"] in ids and not row.get("archived")]

    def active_project_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [row for row in rows if not row.get("archived")]

    def sync_project_downlinks(self, username: str, rows: list[dict[str, Any]], payload: dict[str, Any], scope: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        target_rows = self.project_downlink_target_rows(rows, payload)
        if not target_rows:
            return [], {"status": "skipped"}
        packages = self.save_project_downlinks(target_rows, username, scope)
        notices = [self.notify_project_downlink(package, username) for package in packages]
        return target_rows, self.project_downlink_response(packages, notices)

    def project_downlink_scope(self, payload: dict[str, Any]) -> str:
        scope = self.compact_text(payload.get("downlink_scope")) or "project"
        if scope not in {"project", "definition"}:
            raise ValueError("invalid downlink_scope")
        return scope

    def save_project_downlinks(self, rows: list[dict[str, Any]], username: str, scope: str) -> list[dict[str, Any]]:
        packages = []
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            owner_route = str(row.get("owner_route") or "").strip()
            if owner_route not in BACKENDS:
                raise ValueError(f"project {row['id']} has no valid owner_route")
            grouped.setdefault(owner_route, []).append(row)
        for owner_route, owner_rows in sorted(grouped.items()):
            packages.append(self.save_project_downlink(owner_route, owner_rows, username, scope))
        return packages

    def save_project_downlink(self, owner_route: str, rows: list[dict[str, Any]], username: str, scope: str) -> dict[str, Any]:
        package = {
            "id": f"pwb-{int(time.time())}-{secrets.token_hex(4)}",
            "type": "project-workbench",
            "scope": scope,
            "target": owner_route,
            "status": "pending",
            "created_at": now_ts(),
            "created_by": username,
            "projects": [self.project_downlink_project(row, scope) for row in self.sorted_project_rows(rows)],
        }
        self.write_project_downlink_package(package)
        return package

    def notify_project_downlink(self, package: dict[str, Any], username: str) -> dict[str, Any]:
        owner_route = str(package.get("target") or "")
        notice = self.owner_json_request(owner_route, "/api/project-workbench/downlink/apply", {"gateway_url": self.public_base_url(), "package_id": package["id"]}, username, timeout=15)
        current = self.project_downlink_package(str(package["id"])) or package
        if notice.get("ok"):
            current["status"] = str(notice.get("status") or "applied")
            current["notice"] = {"ok": True, "updated_at": now_ts()}
        else:
            current["status"] = "failed"
            current["notice"] = {"ok": False, "error": self.compact_text(notice.get("error")), "updated_at": now_ts()}
        self.write_project_downlink_package(current)
        return {"ok": bool(notice.get("ok")), "status": current.get("status") or "failed", "error": notice.get("error")}

    def project_downlink_response(self, packages: list[dict[str, Any]], notices: list[dict[str, Any]]) -> dict[str, Any]:
        statuses = [str(notice.get("status") or package.get("status") or "") for package, notice in zip(packages, notices)]
        if any(status == "failed" for status in statuses):
            status = "failed"
        elif statuses and all(status == "applied" for status in statuses):
            status = "applied"
        else:
            status = "pending"
        return {
            "status": status,
            "packages": [{"package_id": package["id"], "target": package["target"], "status": notice.get("status") or package.get("status")} for package, notice in zip(packages, notices)],
        }

    def rows_with_definition_sync(self, rows: list[dict[str, Any]], target_rows: list[dict[str, Any]], downlink: dict[str, Any]) -> list[dict[str, Any]]:
        target_ids = {row["id"] for row in target_rows}
        status = self.clean_definition_sync_status(downlink.get("status"))
        updated_rows = []
        for index, row in enumerate(rows, 1):
            if row["id"] in target_ids:
                updated = dict(row)
                updated["definition_sync"] = self.project_definition_sync(row, status)
                row = self.clean_project_row(updated, int(row.get("rank") or index))
            updated_rows.append(row)
        return updated_rows

    def project_downlink_hash_error(self, package: dict[str, Any], payload: dict[str, Any]) -> str:
        actual = payload.get("hashes")
        if not isinstance(actual, dict):
            return "missing downlink hashes"
        expected = {}
        for project in package.get("projects") if isinstance(package.get("projects"), list) else []:
            if isinstance(project, dict):
                project_id = self.project_id(project)
                expected[project_id] = self.compact_text(project.get("hash"))
        if not expected:
            return "downlink package has no hash"
        mismatched = [project_id for project_id, digest in expected.items() if not digest or actual.get(project_id) != digest]
        return "downlink hash mismatch: " + ", ".join(mismatched) if mismatched else ""

    def project_downlink_package(self, package_id: str) -> dict[str, Any] | None:
        clean_id = re.sub(r"[^A-Za-z0-9._-]", "", package_id)
        if not clean_id:
            return None
        path = self.config.project_downlink_root / clean_id / "package.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def write_project_downlink_package(self, package: dict[str, Any]) -> None:
        package_id = re.sub(r"[^A-Za-z0-9._-]", "", str(package.get("id") or ""))
        if not package_id:
            raise ValueError("invalid downlink package id")
        path = self.config.project_downlink_root / package_id / "package.json"
        self.write_atomic_text(path, json.dumps(package, ensure_ascii=False, indent=2) + "\n")

    def project_workbench_truth_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "brief": row["brief"],
            "current_d": row["current_d"],
            "items": row["items"],
        }

    def project_truth_row(self, row: dict[str, Any]) -> dict[str, Any]:
        truth = self.project_workbench_truth_row(row)
        if isinstance(row.get("definition"), dict):
            definition = pd_state.clean_project_definition(row.get("definition"))
            if definition:
                truth["definition"] = definition
        return truth

    def project_downlink_project(self, row: dict[str, Any], scope: str = "project") -> dict[str, Any]:
        if scope == "definition":
            definition = pd_state.project_definition_hash_payload(row.get("definition"))
            if not definition:
                raise ValueError(f"project {row['id']} has no definition")
            project = {
                "id": row["id"],
                "name": row["name"],
                "brief": row["brief"],
                "current_d": row["current_d"],
                "definition": definition,
                "workbench_path": row.get("workbench_path") or row.get("path") or "",
            }
            project["hash"] = pd_state.project_definition_downlink_hash(row["id"], definition)
            return project
        project = self.project_truth_row(row)
        project["workbench_path"] = row.get("workbench_path") or row.get("path") or ""
        project["hash"] = self.project_downlink_hash(project)
        return project

    def project_workbench_hash(self, project: dict[str, Any]) -> str:
        truth = self.project_workbench_truth_row(project)
        body = json.dumps(truth, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(body).hexdigest()

    def project_downlink_hash(self, project: dict[str, Any]) -> str:
        truth = self.project_truth_row(project)
        if isinstance(truth.get("definition"), dict):
            definition = pd_state.project_definition_hash_payload(truth.get("definition"))
            if definition:
                truth["definition"] = definition
            else:
                truth.pop("definition", None)
        body = json.dumps(truth, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(body).hexdigest()

    def clean_definition_sync_status(self, status: Any) -> str:
        value = self.compact_text(status)
        return value if value in {"applied", "failed", "pending"} else "pending"

    def project_definition_sync(self, row: dict[str, Any], status: Any) -> dict[str, Any]:
        return {
            "status": self.clean_definition_sync_status(status),
            "hash": pd_state.project_definition_downlink_hash(self.project_id(row), row.get("definition")),
            "updated_at": now_ts(),
        }

    def project_definition_submit(self, row: dict[str, Any], status: Any) -> dict[str, Any]:
        status = self.compact_text(status)
        return {
            "status": status if status in PROJECT_DEFINITION_SUBMIT_STATUSES else "",
            "hash": pd_state.project_definition_downlink_hash(self.project_id(row), row.get("definition")),
            "updated_at": now_ts(),
        }

    def clean_project_definition_sync(self, source: dict[str, Any], project_id: str, definition: dict[str, Any]) -> dict[str, Any]:
        sync = source.get("definition_sync")
        if not isinstance(sync, dict):
            return {}
        expected_hash = pd_state.project_definition_downlink_hash(project_id, definition)
        if self.compact_text(sync.get("hash")) != expected_hash:
            return {"status": "pending", "hash": expected_hash}
        clean = {"status": self.clean_definition_sync_status(sync.get("status")), "hash": expected_hash}
        if isinstance(sync.get("updated_at"), int):
            clean["updated_at"] = sync["updated_at"]
        return clean

    def read_project_rows(self) -> list[dict[str, Any]]:
        rows = []
        try:
            lines = self.config.project_workbench_index.read_text(encoding="utf-8").splitlines()
        except OSError:
            return rows
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            rows.append(self.clean_project_row(row, len(rows) + 1))
        return self.sorted_project_rows(rows)

    def write_project_rows(self, rows: list[dict[str, Any]]) -> None:
        self.config.project_workbench_index.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in self.sorted_project_rows(rows)]
        self.write_atomic_text(self.config.project_workbench_index, "\n".join(lines) + ("\n" if lines else ""))

    def sorted_project_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(rows, key=lambda row: (PROJECT_BUCKET_ORDER.get(str(row.get("bucket")), 9), int(row.get("rank") or 9999), str(row.get("id"))))

    def clean_project_row(self, source: dict[str, Any], rank: int) -> dict[str, Any]:
        project_id = self.project_id(source)
        row = {
            "id": project_id,
            "path": self.compact_text(source.get("path")),
            "owner_route": self.clean_owner_route(source.get("owner_route")),
            "workbench_path": self.compact_text(source.get("workbench_path") or source.get("path")),
            "code_root": self.compact_text(source.get("code_root")),
            "archived": bool(source.get("archived")),
            "bucket": self.clean_project_bucket(source.get("bucket")),
            "rank": self.clean_rank(source.get("rank") or rank),
            "name": self.compact_text(source.get("name") or project_id),
            "brief": self.compact_text(source.get("brief")),
            "current_d": self.compact_text(source.get("current_d")),
            "items": self.clean_project_items(source.get("items")),
        }
        if isinstance(source.get("definition"), dict):
            definition = pd_state.clean_project_definition(source.get("definition"))
            if definition:
                row["definition"] = definition
                definition_sync = self.clean_project_definition_sync(source, project_id, definition)
                if definition_sync:
                    row["definition_sync"] = definition_sync
                submit = source.get("definition_submit")
                status = self.compact_text(submit.get("status")) if isinstance(submit, dict) else ""
                expected_hash = pd_state.project_definition_downlink_hash(project_id, definition)
                if status in PROJECT_DEFINITION_SUBMIT_STATUSES and self.compact_text(submit.get("hash")) == expected_hash:
                    row["definition_submit"] = {"status": status, "hash": expected_hash}
                    if isinstance(submit.get("updated_at"), int):
                        row["definition_submit"]["updated_at"] = submit["updated_at"]
        return row

    def clean_project_items(self, items: Any) -> list[dict[str, Any]]:
        source = items if isinstance(items, list) else []
        clean_items = []
        counts = {item_type: 0 for item_type in PROJECT_ITEM_TYPES}
        for index, item in enumerate(source, 1):
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip()
            title = self.compact_text(item.get("title"))
            if item_type not in PROJECT_ITEM_TYPES or not title:
                continue
            status = str(item.get("status") or "open").strip()
            if status in PROJECT_DONE_STATUSES:
                continue
            stage = self.compact_text(item.get("stage"))
            if stage not in PROJECT_ITEM_STAGES:
                stage = {"in_progress": "in_progress", "review": "receipt_submitted", "paused": "paused"}.get(status, "awaiting_owner")
            if counts[item_type] >= PROJECT_ITEM_TYPE_LIMIT:
                continue
            counts[item_type] += 1
            clean = {
                "id": str(item.get("id") or f"item-{index}").strip(),
                "type": item_type,
                "title": title,
                "body": self.compact_text(item.get("body")),
                "recommendation": self.compact_text(item.get("recommendation")),
                "status": status,
                "stage": stage,
            }
            for key in ("workorder_id", "worker_session", "updated_at"):
                value = self.compact_text(item.get(key))
                if value:
                    clean[key] = value
            prompt = pd_state.clean_item_decision_prompt(item.get("decision_prompt"), item_type)
            if prompt:
                clean["decision_prompt"] = prompt
            decision = pd_state.clean_owner_decision(item.get("owner_decision"))
            if decision:
                clean["owner_decision"] = decision
            clean_items.append(clean)
        return clean_items

    def project_id(self, data: dict[str, Any]) -> str:
        raw = str(data.get("id") or data.get("name") or "project").strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
        return slug or "project"

    def clean_project_bucket(self, value: Any) -> str:
        bucket = str(value or "B").strip().upper()[:1]
        return bucket if bucket in PROJECT_BUCKETS else "B"

    def clean_owner_route(self, value: Any) -> str:
        route = str(value or "").strip().lower()
        return route if route in BACKENDS else ""

    def clean_rank(self, value: Any) -> int:
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 9999

    def compact_text(self, value: Any) -> str:
        return " ".join(str(value or "").split())

    def write_atomic_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

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

    def handle_agent_resume(self, username: str) -> None:
        try:
            payload = self.read_json_body(65536); route = str(payload.get("route") or "").strip(); agent_session_id = clean_agent_session_id(str(payload.get("agent_session_id") or "")); source = str(payload.get("source") or "")
            if route not in BACKENDS or not agent_session_id or not source: raise ValueError("route, agent_session_id and source are required")
            if not self.config.allowed_route(username, route): self.write_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN); return
            response = self.owner_json_request(route, "/api/agent/resume", {"agent_session_id": agent_session_id, "source": source, "max_running": self.max_running_for(username, route)}, username)
            target_session = clean_session_id(str(response.get("session") or "")) if response.get("ok") else ""
            if not target_session: self.write_json({"ok": False, "error": response.get("error") or "owner resume failed"}, HTTPStatus.BAD_GATEWAY); return
            self.write_json({"ok": True, "redirect": f"/{route}/?session={target_session}", "session": target_session}, HTTPStatus.OK)
        except ValueError as exc: self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_agent_new(self, username: str) -> None:
        try:
            payload = self.read_json_body(4096); route = str(payload.get("route") or "").strip(); command = clean_agent_launch_command(str(payload.get("command") or ""))
            if route not in BACKENDS or not command: raise ValueError("route and command are required")
            if not self.config.allowed_route(username, route): self.write_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN); return
            if username != self.config.mcp_user and command != "codex": self.write_json({"ok": False, "error": "forbidden command"}, HTTPStatus.FORBIDDEN); return
            response = self.owner_json_request(route, "/api/agent/new", {"command": command, "max_running": self.max_running_for(username, route)}, username)
            target_session = clean_session_id(str(response.get("session") or "")) if response.get("ok") else ""
            if not target_session: self.write_json({"ok": False, "error": response.get("error") or "owner new session failed"}, HTTPStatus.BAD_GATEWAY); return
            self.write_json({"ok": True, "redirect": f"/{route}/?session={target_session}", "session": target_session}, HTTPStatus.OK)
        except ValueError as exc: self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_faryo_dispatch(self, username: str) -> None:
        try:
            payload = self.read_json_body(128 * 1024)
            project = self.dispatch_project(payload)
            if self.project_has_active_workorder(project["row"]):
                raise ValueError("project already has active workorder")
            item_ids = self.workorder_item_ids(project["row"], payload)
            route = project["owner_route"]
            owner_status = self.project_owner_workbench_status(project, username)
            prompt = str(payload.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("prompt is required")
            title = clean_session_title(payload.get("title") or f"P:{project['name']}")
            selected_cwd = owner_status["cwd"]
            launch = {"command": "codex", "cwd": selected_cwd, "title": title, "max_running": self.max_running_for(username, route)}
            response = self.owner_json_request(route, "/api/agent/new", launch, username, timeout=10, extra_headers={"X-Faryo-Workspace-Root": selected_cwd})
            session = clean_session_id(str(response.get("session") or "")) if response.get("ok") else ""
            if not session:
                self.write_json({"ok": False, "error": self.compact_text(response.get("error")) or "owner new session failed", "route": route}, HTTPStatus.BAD_GATEWAY); return
            workorder_id = self.new_workorder_id()
            workorder = self.owner_json_request(route, "/api/workorder/create", {
                "project_root": selected_cwd,
                "workorder_id": workorder_id,
                "content": self.render_workorder(project, selected_cwd, workorder_id, prompt, item_ids, owner_status["hash"]),
            }, username, timeout=10)
            if not workorder.get("ok"):
                self.owner_json_request(route, "/api/session/close", {"session": session}, username, timeout=4)
                self.write_json({"ok": False, "error": workorder.get("error") or "owner workorder create failed", "route": route, "session": session}, HTTPStatus.BAD_GATEWAY); return
            transitioned = self.owner_json_request(route, "/api/workbench/transition", {
                "project_root": selected_cwd,
                "event_type": "workorder_created",
                "item_ids": item_ids,
                "workorder_id": workorder_id,
                "actor": "faryo-controller",
                "source": "faryo-dispatch",
                "summary": f"Faryo created workorder {workorder_id}.",
            }, username, timeout=10)
            if not transitioned.get("ok"):
                self.owner_json_request(route, "/api/session/close", {"session": session}, username, timeout=4)
                self.write_json({"ok": False, "error": transitioned.get("error") or "owner transition failed", "route": route, "session": session}, HTTPStatus.BAD_GATEWAY); return
            projected = self.update_projection_from_owner_project(project["id"], transitioned.get("project"))
            if projected:
                project["row"] = projected
            workorder["item_ids"] = item_ids
            sent = self.owner_json_request(route, "/api/send", {"session": session, "text": self.workorder_dispatch_prompt(project, workorder)}, username, timeout=10)
            if not sent.get("ok"):
                self.rollback_failed_dispatch(username, route, selected_cwd, project["id"], item_ids, workorder_id, "Worker prompt send failed; returned items to approved workorder queue.")
                self.owner_json_request(route, "/api/session/close", {"session": session}, username, timeout=4)
                self.write_json({"ok": False, "error": sent.get("error") or "owner send failed", "route": route, "session": session}, HTTPStatus.BAD_GATEWAY); return
            started = self.owner_json_request(route, "/api/workbench/transition", {
                "project_root": selected_cwd,
                "event_type": "worker_started",
                "item_ids": item_ids,
                "workorder_id": workorder_id,
                "worker_session": session,
                "actor": "faryo-controller",
                "source": "faryo-dispatch",
                "summary": f"Worker session {session} started for workorder {workorder_id}.",
            }, username, timeout=10)
            if not started.get("ok"):
                self.rollback_failed_dispatch(username, route, selected_cwd, project["id"], item_ids, workorder_id, "Worker start transition failed; returned items to approved workorder queue.")
                self.owner_json_request(route, "/api/session/close", {"session": session}, username, timeout=4)
                self.write_json({"ok": False, "error": started.get("error") or "owner worker-start transition failed", "route": route, "session": session}, HTTPStatus.BAD_GATEWAY); return
            projected = self.update_projection_from_owner_project(project["id"], started.get("project"))
            if projected:
                project["row"] = projected
            self.start_workorder_receipt_watch(username, route, selected_cwd, project, workorder, session)
            self.write_json({"ok": True, "route": route, "session": session, "title": title, "cwd": selected_cwd, "workorder": workorder, "redirect": f"/{route}/?session={session}"}, HTTPStatus.OK)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_faryo_workorder_verify(self, username: str) -> None:
        try:
            payload = self.read_json_body(4096)
            project = self.dispatch_project(payload)
            workorder_id = self.compact_text(payload.get("workorder_id") or payload.get("workorderId"))
            if not workorder_id:
                raise ValueError("workorder_id is required")
            if self.compact_text(payload.get("result")) not in {"pass", "fail"}:
                raise ValueError("result must be pass or fail")
            result = self.verify_project_workorder_result(username, project, workorder_id, payload, actor="faryo-controller")
            self.write_json(result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_GATEWAY)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_project_workbench_transition(self, username: str) -> None:
        try:
            payload = self.read_json_body(32 * 1024)
            project = self.dispatch_project(payload)
            route = project["owner_route"]
            last_error = ""
            for cwd in project["cwd_candidates"]:
                result = self.owner_json_request(route, "/api/workbench/transition", {**payload, "project_root": cwd}, username, timeout=10)
                if result.get("ok"):
                    updated = self.update_projection_from_owner_project(project["id"], result.get("project"))
                    submitted = self.update_definition_submit_from_transition(project["id"], payload)
                    if submitted:
                        updated = submitted
                    self.write_json({"ok": True, "transition": result, "project": updated, "workbench": self.project_workbench_payload()}, HTTPStatus.OK)
                    return
                last_error = self.compact_text(result.get("error")) or "owner transition failed"
            self.write_json({"ok": False, "error": last_error, "route": route}, HTTPStatus.BAD_GATEWAY)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def update_projection_from_owner_project(self, project_id: str, owner_project: Any) -> dict[str, Any] | None:
        if not isinstance(owner_project, dict):
            return None
        rows = self.read_project_rows()
        changed = False
        updated_row = None
        for row in rows:
            if row["id"] != project_id:
                continue
            for key in ("name", "brief", "current_d", "items"):
                if key in owner_project:
                    row[key] = owner_project[key]
            updated_row = self.clean_project_row(row, int(row.get("rank") or 9999))
            row.update(updated_row)
            changed = True
            break
        if changed:
            self.write_project_rows(rows)
        return updated_row

    def update_definition_submit_from_transition(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self.compact_text(payload.get("event_type") or payload.get("eventType")) != "item_created":
            return None
        definition_hash = self.compact_text(payload.get("definition_hash") or payload.get("definitionHash"))
        if not definition_hash:
            return None
        rows = self.read_project_rows()
        for index, row in enumerate(rows):
            if row["id"] != project_id:
                continue
            expected_hash = pd_state.project_definition_downlink_hash(project_id, row.get("definition"))
            if definition_hash != expected_hash:
                return None
            updated = dict(row)
            updated["definition_submit"] = self.project_definition_submit(row, "converted")
            rows[index] = self.clean_project_row(updated, int(row.get("rank") or index + 1))
            self.write_project_rows(rows)
            return rows[index]
        return None

    def dispatch_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id = self.project_id({"id": payload.get("project_id") or payload.get("projectId") or payload.get("id") or ""})
        if not project_id or project_id == "project":
            raise ValueError("project_id is required")
        row = next((item for item in self.read_project_rows() if item["id"] == project_id), None)
        if not row:
            raise ValueError("project not found")
        if row.get("archived"):
            raise ValueError("project is archived")
        route = row.get("owner_route") or ""
        name = row.get("name") or row["id"]
        if route not in BACKENDS:
            raise ValueError("project owner_route is invalid")
        cwd_candidates = self.project_worker_cwd_candidates(row)
        if not cwd_candidates:
            raise ValueError("project cwd is missing")
        return {"id": project_id, "name": name, "owner_route": route, "cwd_candidates": cwd_candidates, "row": row}

    def workorder_dispatch_prompt(self, project: dict[str, Any], workorder: dict[str, Any]) -> str:
        path = self.compact_text(workorder.get("path"))
        relative_path = self.compact_text(workorder.get("relative_path"))
        workorder_id = self.compact_text(workorder.get("id"))
        item_ids = workorder.get("item_ids") if isinstance(workorder.get("item_ids"), list) else []
        item_line = "覆盖事项：" + ", ".join(f"`{self.compact_text(item_id)}`" for item_id in item_ids if self.compact_text(item_id)) + "。"
        return "\n".join([
            f"执行 Faryo 工单 `{workorder_id}`。",
            f"项目：`{project['id']}`；Owner route（归属端路由）：`{project['owner_route']}`。",
            f"工单路径：`{path}`" + (f"（相对路径：`{relative_path}`）" if relative_path else "") + "。",
            item_line,
            "先读取工单和 `00-system/workbench.json`，按绑定 item（事项）核对 action（执行项）、decision（裁决项）和 watch（说明项）；decision/watch 只作为本轮上下文，执行范围只限 action。",
            "不要直接手写 `workbench.json` 或 `workbench.history.jsonl`；Receipt（回执）提交后由主控做业务验收，通过时再由状态机写入历史。",
            "未写 Receipt 不得声称完成；若发现新事项，只在回执中提出，不要绕过状态机写入。",
        ])

    def workorder_item_ids(self, row: dict[str, Any], payload: dict[str, Any]) -> list[str]:
        values = payload.get("item_ids")
        if not isinstance(values, list):
            raise ValueError("item_ids is required")
        requested: list[str] = []
        for value in values:
            item_id = self.compact_text(value)
            if item_id and item_id not in requested:
                requested.append(item_id)
        if not requested:
            raise ValueError("item_ids is required")
        approved: dict[str, str] = {}
        for item in row.get("items") if isinstance(row.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            item_id = self.compact_text(item.get("id"))
            item_type = self.compact_text(item.get("type"))
            stage = self.compact_text(item.get("stage"))
            if item_id and stage == "approved_for_workorder":
                approved[item_id] = item_type
        invalid = [item_id for item_id in requested if item_id not in approved]
        if invalid:
            raise ValueError("item_ids must target approved items: " + ", ".join(invalid))
        if not any(approved.get(item_id) == "action" for item_id in requested):
            raise ValueError("item_ids must include at least one approved action item")
        return requested

    def project_has_active_workorder(self, row: dict[str, Any]) -> bool:
        for item in row.get("items") if isinstance(row.get("items"), list) else []:
            if isinstance(item, dict) and self.compact_text(item.get("stage")) in {"workorder_created", "in_progress", "receipt_submitted", "needs_fix"}:
                return True
        return False

    def rollback_failed_dispatch(self, username: str, route: str, cwd: str, project_id: str, item_ids: list[str], workorder_id: str, summary: str) -> None:
        result = self.owner_json_request(route, "/api/workbench/transition", {
            "project_root": cwd,
            "event_type": "workorder_dispatch_failed",
            "item_ids": item_ids,
            "workorder_id": workorder_id,
            "actor": "faryo-controller",
            "source": "faryo-dispatch",
            "summary": summary,
        }, username, timeout=10)
        if result.get("ok"):
            self.update_projection_from_owner_project(project_id, result.get("project"))

    def project_owner_workbench_status(self, project: dict[str, Any], username: str) -> dict[str, str]:
        expected = self.project_workbench_hash(project["row"])
        route = project["owner_route"]
        last_error = ""
        for cwd in project["cwd_candidates"]:
            result = self.owner_json_request(route, "/api/workbench/status", {"project_root": cwd}, username, timeout=10)
            if not result.get("ok"):
                last_error = self.compact_text(result.get("error")) or "owner workbench status failed"
                continue
            actual = self.compact_text(result.get("workbenchHash"))
            if actual == expected:
                return {"cwd": cwd, "hash": actual}
            last_error = f"project truth hash mismatch: {project['id']}"
        raise ValueError(last_error or "owner workbench status failed")

    def new_workorder_id(self) -> str:
        return f"wo-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{secrets.token_hex(4)}"

    def render_workorder(self, project: dict[str, Any], cwd: str, workorder_id: str, prompt: str, item_ids: list[str], workbench_hash: str) -> str:
        row = project["row"]
        items = row.get("items") if isinstance(row.get("items"), list) else []
        selected_ids = set(item_ids)
        item_lines = []
        type_labels = {"action": "action（执行项）", "decision": "decision（裁决项）", "watch": "watch（说明项）"}
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = self.compact_text(item.get("id"))
            if item_id not in selected_ids:
                continue
            title = self.compact_text(item.get("title"))
            if title:
                item_type = self.compact_text(item.get("type"))
                item_lines.append(f"- `{item_id}` [{type_labels.get(item_type, item_type or 'item（事项）')}] {title}")
        values = {
            "workorder_id": workorder_id,
            "project_id": project["id"],
            "project_name": project["name"],
            "owner_route": project["owner_route"],
            "project_root": cwd,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "workbench_hash": workbench_hash,
            "active_items": "\n".join(item_lines),
            "task": prompt,
        }
        template = WORKORDER_TEMPLATE_SOURCE.read_text(encoding="utf-8")
        for key, value in values.items():
            template = template.replace("{{" + key + "}}", str(value))
        return template

    def faryo_receipt_notice(self, project_id: str, project_name: str, route: str, workorder_id: str, worker_session: str, result: dict[str, Any]) -> str:
        status = "Receipt（回执）已提交，主控现在做业务验收。" if result.get("ok") else f"Receipt（回执）提交状态迁移失败：{self.compact_text(result.get('error')) or 'unknown error'}。"
        return "\n".join([
            status,
            f"项目：`{project_id}` / {project_name}；Owner route（归属端路由）：`{route}`。",
            f"工单：`{workorder_id}`；worker session（施工会话）：`{worker_session or 'unknown'}`。",
            f"业务验收通过：调用 Gateway `/api/faryo/workorder/verify`，payload（请求体）：`{{\"project_id\":\"{project_id}\",\"workorder_id\":\"{workorder_id}\",\"result\":\"pass\"}}`。",
            f"业务验收不通过：调用同一接口并传 `{{\"project_id\":\"{project_id}\",\"workorder_id\":\"{workorder_id}\",\"result\":\"fail\"}}`，再向该 worker session（施工会话）发纠偏指令；不要重复创建 WO（工单）或 worker（施工会话）。",
        ])

    def start_workorder_receipt_watch(self, username: str, route: str, cwd: str, project: dict[str, Any], workorder: dict[str, Any], worker_session: str) -> None:
        workorder_id = self.compact_text(workorder.get("id"))
        if not workorder_id:
            return
        args = (username, route, cwd, project["id"], project["name"], workorder_id, worker_session)
        threading.Thread(target=self.watch_workorder_receipt, args=args, daemon=True, name=f"faryo-wo-watch-{workorder_id[-8:]}").start()

    def watch_workorder_receipt(self, username: str, route: str, cwd: str, project_id: str, project_name: str, workorder_id: str, worker_session: str) -> None:
        for _attempt in range(WORKORDER_RECEIPT_WATCH_ATTEMPTS):
            time.sleep(WORKORDER_RECEIPT_WATCH_INTERVAL_SECONDS)
            status = self.owner_json_request(route, "/api/workorder/status", {"project_root": cwd, "workorder_id": workorder_id}, username, timeout=6)
            if not status.get("ok") or not status.get("receiptReady"):
                continue
            result = self.owner_json_request(route, "/api/workbench/transition", {
                "project_root": cwd,
                "event_type": "worker_receipt_submitted",
                "item_ids": status.get("itemIds"),
                "workorder_id": workorder_id,
                "actor": "project-worker",
                "source": "workorder-watch",
                "summary": "Workorder receipt submitted for controller review.",
            }, username, timeout=10)
            if result.get("ok"):
                self.update_projection_from_owner_project(project_id, result.get("project"))
            self.ensure_faryo_controller(username, self.faryo_receipt_notice(project_id, project_name, route, workorder_id, worker_session, result))
            return

    def verify_project_workorder_result(self, username: str, project: dict[str, Any], workorder_id: str, source: dict[str, Any], actor: str = "faryo-controller") -> dict[str, Any]:
        route = project["owner_route"]
        last_error = ""
        for cwd in project["cwd_candidates"]:
            payload = {"project_root": cwd, "workorder_id": workorder_id, "actor": actor, "result": self.compact_text(source.get("result"))}
            for key in ("summary", "evidence"):
                if source.get(key):
                    payload[key] = self.compact_text(source.get(key))
            result = self.owner_json_request(route, "/api/workorder/verify", payload, username, timeout=10)
            if result.get("ok"):
                projected = self.update_projection_from_owner_project(project["id"], result.get("project"))
                if projected:
                    project["row"] = projected
                projection_synced = self.project_workbench_hash(project["row"]) == self.compact_text(result.get("workbenchHash"))
                result["projectionSynced"] = projection_synced
                result["closed"] = bool(result.get("closed") and projection_synced)
                result["needsFix"] = bool(result.get("needsFix") and projection_synced)
                result.update({"route": route, "project_id": project["id"], "cwd": cwd})
                return result
            last_error = self.compact_text(result.get("error")) or "owner verify failed"
        return {"ok": False, "error": last_error, "route": route, "project_id": project["id"]}

    def project_worker_cwd_candidates(self, row: dict[str, Any]) -> list[str]:
        marker = "/00-system/workbench.json"
        path = self.compact_text(row.get("path"))
        workbench = self.compact_text(row.get("workbench_path"))
        code_root = self.compact_text(row.get("code_root"))
        candidates: list[str] = []

        def add(value: Any) -> None:
            candidate = self.compact_text(value)
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        if code_root.startswith("/"):
            add(code_root)
        if workbench.endswith(marker):
            add(workbench[: -len(marker)])
        if path.endswith(marker):
            add(path[: -len(marker)])
        if path.startswith("/"):
            add(path)
        if workbench.startswith("/"):
            add(str(Path(workbench).parent.parent))
        root = self.config.owner_project_roots.get(self.compact_text(row.get("owner_route")), "")
        for segment in self.project_dir_segments(row):
            add(str(Path(root) / segment))
        return candidates

    def project_dir_segments(self, row: dict[str, Any]) -> list[str]:
        name = self.compact_text(row.get("name"))
        values = [name, self.compact_text(row.get("id")), name.lower() if name else ""]
        segments: list[str] = []
        for value in values:
            segment = self.compact_text(value)
            if not segment or segment in {".", ".."} or "/" in segment or "\\" in segment or "\x00" in segment:
                continue
            if segment not in segments:
                segments.append(segment)
        return segments

    def handle_faryo_status(self, username: str) -> None:
        if not self.config.allowed_route(username, "gcp"):
            self.write_json({"ok": False, "error": "forbidden"}, HTTPStatus.FORBIDDEN)
            return
        sessions = self.live_faryo_sessions(username)
        session = sessions[0] if len(sessions) == 1 else ""
        self.write_json({
            "ok": True,
            "route": "gcp",
            "session": session,
            "running": bool(session),
            "conflict": len(sessions) > 1,
            "sessions": sessions,
            "redirect": f"/gcp/?session={session}" if session else "",
            "updatedAt": now_ts(),
        }, HTTPStatus.OK)

    def handle_faryo_start(self, username: str) -> None:
        try:
            result = self.ensure_faryo_controller(username, self.faryo_start_prompt())
            if not result.get("ok"):
                status = HTTPStatus.CONFLICT if result.get("sessions") else HTTPStatus.BAD_GATEWAY
                if result.get("error") == "forbidden":
                    status = HTTPStatus.FORBIDDEN
                self.write_json(result, status)
                return
            self.write_json(result, HTTPStatus.OK)
        except ValueError as exc:
            self.write_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def ensure_faryo_controller(self, username: str, prompt: str = "") -> dict[str, Any]:
        if not self.config.allowed_route(username, "gcp"):
            return {"ok": False, "error": "forbidden"}
        session = self.faryo_session_name(username)
        self.config.install_faryo_codex_profile()
        sessions = self.live_faryo_sessions(username)
        if len(sessions) > 1:
            return {"ok": False, "error": "multiple Faryo profile sessions are running; close extras first", "sessions": sessions}
        started = False
        if sessions:
            session = sessions[0]
        elif self.tmux_session_exists(session):
            if not self.kill_tmux_session(session):
                return {"ok": False, "error": "failed to reset stale Faryo session", "session": session}
            self.start_faryo_session(session, username, self.latest_faryo_thread_id(), prompt)
            started = True
        else:
            self.start_faryo_session(session, username, self.latest_faryo_thread_id(), prompt)
            started = True
        if not self.faryo_controller_ready(username, session):
            return {"ok": False, "error": "Faryo controller did not become ready", "session": session}
        if prompt and not started:
            sent = self.owner_json_request("gcp", "/api/send", {"session": session, "text": prompt}, username, timeout=6)
            if not sent.get("ok"):
                return {"ok": False, "error": self.compact_text(sent.get("error")) or "failed to send prompt to Faryo", "session": session}
        return {"ok": True, "redirect": f"/gcp/?session={session}", "session": session}

    def faryo_start_prompt(self) -> str:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return ""
        payload = self.read_json_body(65536)
        return str(payload.get("prompt") or "").strip()

    def faryo_session_name(self, username: str) -> str:
        return "faryo-main"

    def latest_faryo_thread_id(self) -> str:
        if not self.config.faryo_codex_state.is_file(): return ""
        sql = "SELECT id, rollout_path FROM threads WHERE source = 'cli' AND thread_source = 'user' AND COALESCE(archived, 0) = 0 AND cwd = ? ORDER BY updated_at DESC LIMIT 20"
        try:
            conn = sqlite3.connect(f"file:{self.config.faryo_codex_state.as_posix()}?mode=ro", uri=True, timeout=1); rows = conn.execute(sql, (str(self.config.faryo_work_root),)).fetchall(); conn.close()
        except sqlite3.Error:
            return ""
        return next((clean_agent_session_id(str(thread_id)) or "" for thread_id, rollout_path in rows if self.faryo_profile_rollout(rollout_path)), "")

    def faryo_profile_rollout(self, rollout_path: Any) -> bool:
        try:
            first_line = next(line for line in Path(str(rollout_path or "")).expanduser().read_text(encoding="utf-8").splitlines() if line.strip())
            instructions = (((json.loads(first_line).get("payload") or {}).get("base_instructions") or {}).get("text") or "").strip()
            profile_source = FARYO_PROFILE_SOURCE.read_text(encoding="utf-8").strip()
        except (OSError, StopIteration, json.JSONDecodeError):
            return False
        return bool(profile_source and instructions.startswith(profile_source[: min(240, len(profile_source))]))

    def tmux_session_exists(self, session: str) -> bool:
        try: return subprocess.run(["tmux", "has-session", "-t", session], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=2, check=False).returncode == 0
        except subprocess.TimeoutExpired: return False

    def kill_tmux_session(self, session: str) -> bool:
        try: result = subprocess.run(["tmux", "kill-session", "-t", session], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=3, check=False)
        except subprocess.TimeoutExpired: return False
        return result.returncode == 0 or not self.tmux_session_exists(session)

    def faryo_controller_ready(self, username: str, session: str, timeout: float = 15) -> bool:
        deadline = time.monotonic() + timeout; path = "/api/status?" + urlencode({"session": session})
        while time.monotonic() < deadline:
            status = self.owner_json_request("gcp", path, None, username, method="GET", timeout=3)
            if status.get("ok") and status.get("agentProfile") == "codex": return True
            time.sleep(0.5)
        return False

    def tmux_sessions(self) -> list[str]:
        try:
            result = subprocess.run(["tmux", "list-sessions", "-F", "#{session_name}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=2, check=False)
        except subprocess.TimeoutExpired:
            return []
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def tmux_session_option(self, session: str, key: str, value: str | None = None) -> str:
        if value is not None:
            subprocess.run(["tmux", "set-option", "-q", "-t", session, key, value], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=2, check=False)
            return value
        try:
            result = subprocess.run(["tmux", "show-options", "-qv", "-t", session, key], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", timeout=2, check=False)
        except subprocess.TimeoutExpired:
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    def mark_faryo_session(self, session: str, username: str, thread_id: str = "") -> None:
        self.tmux_session_option(session, "@faryo_agent_source", "codex-cli")
        self.tmux_session_option(session, "@faryo_session_title", self.config.faryo_session_title)
        self.tmux_session_option(session, "@faryo_controller_profile", self.config.faryo_profile_name)
        if self.config.faryo_code_root.is_dir():
            self.tmux_session_option(session, "@faryo_git_root", str(self.config.faryo_code_root))
        if thread_id:
            self.tmux_session_option(session, "@faryo_agent_session_id", thread_id)

    def live_faryo_sessions(self, username: str) -> list[str]:
        sessions = []
        for session in self.tmux_sessions():
            if self.tmux_session_option(session, "@faryo_controller_profile") == self.config.faryo_profile_name:
                sessions.append(session)
        return sorted(set(sessions))

    def start_faryo_session(self, session: str, username: str, thread_id: str = "", prompt: str = "") -> None:
        codex = shutil.which("codex") or "codex"
        shell = shutil.which("zsh") or "/usr/bin/zsh"
        initial_prompt = prompt or "启动 Faryo 主控。先读取项目工作台投影和 Faryo 运行真值，给出当前项目优先级、需要用户裁决的事项，并等待用户下一步指令。"
        if thread_id:
            command = shlex.join([codex, "resume", "--profile-v2", self.config.faryo_profile_name, "--cd", str(self.config.faryo_work_root), thread_id, initial_prompt])
        else:
            command = shlex.join([codex, "--profile-v2", self.config.faryo_profile_name, "--cd", str(self.config.faryo_work_root), initial_prompt])
        launch = f"{command}; exec {shlex.quote(shell)} -l"
        try:
            result = subprocess.run(
                ["tmux", "new-session", "-d", "-s", session, "-c", str(self.config.faryo_work_root), shell, "-lc", launch],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("timed out starting Faryo") from exc
        if result.returncode != 0:
            raise ValueError(result.stderr.strip() or "failed to start Faryo")
        self.mark_faryo_session(session, username, thread_id)

    def owner_headers(self, route: str, username: str) -> dict[str, str]:
        host, port, label = BACKENDS[route]; headers = {"Host": f"{host}:{port}", "X-Faryo-Owner-Label": label, "X-Owner-Token": self.config.owner_token(route), "X-Faryo-User": username}
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
        except OSError as exc: return {"ok": False, "error": str(exc)}
        finally: conn.close()
        try: result = json.loads(data.decode("utf-8"))
        except Exception: result = {"ok": False, "error": f"owner returned HTTP {resp.status}"}
        if resp.status >= 400 and isinstance(result, dict): result["ok"] = False
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
        if resp.status >= 400 and isinstance(result, dict): result["ok"] = False
        return result if isinstance(result, dict) else {"ok": False, "error": "invalid owner response"}

    def max_running_for(self, username: str, route: str) -> int:
        return SESSION_POLICY[route][1]

    def owner_agent_sessions(self, route: str, username: str, history_mode: str = "less") -> dict[str, Any]:
        history_mode = history_mode if history_mode in HISTORY_SESSION_LIMITS else "less"
        history = HISTORY_SESSION_LIMITS[history_mode].get(route, SESSION_POLICY[route][0])
        max_running = self.max_running_for(username, route)
        result = self.owner_json_request(route, f"/api/agent-sessions?limit={history}", None, username, method="GET")
        sessions = []
        active_count = int(result.get("activeCount") or 0)
        limit_reached = active_count >= max_running
        raw_sessions = result.get("sessions", []) if result.get("ok") and isinstance(result.get("sessions"), list) else []
        for item in raw_sessions:
            if not isinstance(item, dict):
                continue
            updated_raw = item.get("updatedAt") or item.get("updated_at") or result.get("updatedAt") or ""
            tmux_session = str(item.get("tmuxSession") or item.get("session") or "")
            active = bool(tmux_session)
            cwd = str(item.get("cwd") or "")
            sessions.append({"id": str(item.get("id") or ""), "title": display_session_title(item.get("title") or item.get("label") or item.get("id") or "Untitled session"), "gitLabel": str(item.get("gitLabel") or item.get("git_label") or ""), "route": route, "routeLabel": BACKENDS[route][2], "cwd": cwd, "cwdLabel": compact_path_label(cwd), "updatedAt": display_updated_at(updated_raw), "updatedTs": float(item.get("updatedTs") or parse_updated_ts(updated_raw)), "tmuxSession": tmux_session, "active": active, "agentRunning": bool(active and item.get("agentRunning")), "limitReached": (not active and limit_reached), "source": str(item.get("source") or "")})
        return {"sessions": sessions, "activeCount": active_count, "maxRunning": max_running, "canCreate": not limit_reached}

    def workbench_payload(self, username: str, history_mode: str = "less") -> dict[str, Any]:
        history_mode = history_mode if history_mode in HISTORY_SESSION_LIMITS else "less"
        routes = self.config.user_routes(username)
        route_payloads = {route: self.owner_agent_sessions(route, username, history_mode) for route in routes}
        sessions = [item for route in routes for item in route_payloads[route]["sessions"]]
        sessions.sort(key=lambda item: float(item.get("updatedTs") or 0), reverse=True)
        entries = []
        for item in [backend_status(route) for route in routes]:
            item.update({key: route_payloads[item["id"]][key] for key in ("activeCount", "maxRunning", "canCreate")})
            entries.append(item)
        pending = self.config.list_bridge_packages(username, "pending")
        inbox = pending[:1] if pending else self.config.list_bridge_packages(username)[:1]
        return {"ok": True, "entries": entries, "sessions": sessions[:HISTORY_TOTAL_LIMITS[history_mode]], "history": {"mode": history_mode, "total": HISTORY_TOTAL_LIMITS[history_mode]}, "newSessionCommands": sorted(NEW_SESSION_COMMANDS if username == self.config.mcp_user else {"codex"}), "packages": inbox, "inbox": inbox, "updatedAt": now_ts()}

    def write_bridge_package_asset(self, path: str, username: str) -> None:
        match = re.match(r"^/bridge/packages/([0-9]+-[a-f0-9]{8})/([^/]+)$", path)
        if not match: self.write_not_found(path); return
        if not self.config.bridge_package(match.group(1), username):
            self.write_not_found(path); return
        filename = match.group(2); asset_path = self.config.bridge_root / match.group(1) / filename
        if filename != Path(filename).name or not asset_path.is_file(): self.write_not_found(path); return
        self.write_asset(asset_path.read_bytes(), BRIDGE_SUFFIX_MIME.get(Path(filename).suffix.lower(), "application/octet-stream"), "private, no-store")

    def route_for(self, parsed: Any) -> tuple[str, str] | None:
        match = re.match(r"^/(hp|pc|gcp)/(.*)$", parsed.path)
        if not match:
            return None
        route_name, tail = match.group(1), match.group(2)
        if tail == "":
            return (route_name, "/") if parse_qs(parsed.query).get("session") else None
        if tail.startswith("api/") or tail in OWNER_STATIC_FILES or tail.startswith(OWNER_STATIC_PREFIXES):
            return route_name, "/" + tail
        return None

    def is_api_path(self, path: str) -> bool:
        return path.startswith("/api/") or bool(re.match(r"^/(hp|pc|gcp)/api/", path))

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
        blocked_headers = {"host", "content-length", "x-owner-token", "x-faryo-owner-label", "x-faryo-user", "x-faryo-history-scope", "x-faryo-file-inbox-root", "x-faryo-workspace-root"}
        headers = {key: value for key, value in self.headers.items() if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() not in blocked_headers}
        headers["Host"] = f"{host}:{port}"
        headers["X-Faryo-Owner-Label"] = label
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
        except OSError:
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
            self.send_response(resp.status, resp.reason)
            for key, value in response_headers:
                lower = key.lower()
                if lower in HOP_BY_HOP_HEADERS or lower == "content-length":
                    continue
                self.send_header(key, value)
            if is_event_stream:
                self.send_header("Cache-Control", "no-store, no-transform")
                self.end_headers()
                while True:
                    chunk = resp.readline()
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, TimeoutError):
                        break
                return
            data = resp.read()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.write_bytes(data)
        finally:
            conn.close()

    def serve_portal(self, username: str) -> None:
        self.write_page(portal_html(username, self.config.user_routes(username)))

    def is_authenticated(self) -> bool:
        return self.current_username() is not None

    def controller_token_username(self) -> str | None:
        token = self.headers.get("X-Faryo-Guard-Token", "")
        if self.config.guard_token and self.config.mcp_user and hmac.compare_digest(token, self.config.guard_token):
            return self.config.mcp_user
        return None

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
        return f"{COOKIE_NAME}={payload_b64}.{sig}; Path=/; Max-Age={COOKIE_MAX_AGE}; HttpOnly; Secure; SameSite=Lax"

    def expired_cookie(self) -> str:
        return f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax"

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
        self.write_page(login_html(next_target, error))

    def write_password_page(self, error: str = "") -> None:
        self.write_page(password_html(error))

    def write_page(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = html.encode("utf-8")
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

    def write_static_file(self, filename: str, content_type: str, cache: str = "public, max-age=86400") -> None:
        path = STATIC_DIR / filename
        if filename != Path(filename).name or not path.is_file():
            self.write_not_found("/" + filename)
            return
        self.write_asset(path.read_bytes(), content_type, cache)

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
.routes{display:flex;flex-wrap:wrap;gap:8px;overflow:visible;min-height:42px;margin-bottom:10px;padding:1px}.route-chip{display:flex;align-items:center;gap:5px;white-space:nowrap;padding:7px 8px;border:1px solid var(--line);border-radius:999px;background:var(--panel);color:var(--text);text-decoration:none;font-size:12px}.dot{width:8px;height:8px;border-radius:999px;background:var(--muted)}.online .dot{background:var(--ok)}.slow .dot{background:var(--warn)}.offline .dot,.error .dot{background:var(--danger)}.handoff-strip{display:grid;grid-template-columns:minmax(0,1fr) minmax(160px,200px);gap:10px;align-items:stretch;margin-bottom:12px}.handoff{padding:9px;border:1px solid var(--line);border-radius:8px;background:var(--panel);box-shadow:var(--shadow)}.handoff.drop-ready{border-color:var(--accent2)}.handoff-head,.section-head{display:flex;align-items:center;justify-content:space-between;gap:8px}.handoff-head{margin-bottom:7px}.eyebrow{margin:0 0 2px;color:var(--accent2);font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}h2{margin:0;font-size:calc(15px + var(--font-step));line-height:1.2}.mini-btn{padding:6px 8px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--text);font:inherit;font-size:calc(12px + var(--font-step));white-space:nowrap}.primary-btn{border-color:color-mix(in srgb,var(--accent) 44%,var(--line));color:var(--accent)}.package-list{min-height:48px}.package-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;padding:8px;border:1px solid var(--line);border-radius:7px;background:var(--panel2);touch-action:none}.package-card.dragging{opacity:.55}.drag-ghost{position:fixed;z-index:9999;pointer-events:none;transform:translate(-50%,-50%);box-shadow:var(--shadow)}.package-card strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:calc(13px + var(--font-step))}.package-meta{display:block;margin-top:3px;line-height:1.35}main{display:grid;gap:8px}.sessions{display:grid;gap:8px}.session-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;width:100%;padding:11px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--text);text-decoration:none;text-align:left;font:inherit}.new-session-slot{display:grid;gap:8px}.new-session-slot .session-card{min-height:44px}.session-card>div:first-child{min-width:0}.session-card.inactive{opacity:.72}.session-card.running{border-color:color-mix(in srgb,var(--ok) 44%,var(--line))}.session-card.waiting{border-color:color-mix(in srgb,var(--accent) 48%,var(--line));background:color-mix(in srgb,var(--accent) 7%,var(--panel))}.session-card.drop-target{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 24%,transparent)}.session-title{font-size:calc(15px + var(--font-step));font-weight:760;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.session-meta{margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.arrow{color:var(--muted);font-size:20px}.modal{position:fixed;inset:0;z-index:20;display:none;place-items:end center;padding:16px;background:rgba(0,0,0,.42)}.modal.open{display:grid}.sheet{width:min(100%,420px);padding:14px;border:1px solid var(--line);border-radius:12px;background:var(--panel);box-shadow:var(--shadow)}.sheet h3{margin:0 0 6px;font-size:18px}.sheet p{margin:0 0 12px;color:var(--muted);font-size:13px;line-height:1.45}.choice-list{display:grid;gap:8px}.choice-btn{width:100%;padding:11px;border:1px solid var(--line);border-radius:8px;background:var(--panel2);color:var(--text);text-align:left;font:inherit}.choice-btn strong{display:block}.choice-btn span{display:block;margin-top:3px;color:var(--muted);font-size:12px}.choice-btn.danger{border-color:color-mix(in srgb,var(--danger) 55%,var(--line));color:var(--danger)}.choice-btn:disabled{opacity:.45}.modal-actions{display:flex;justify-content:flex-end;margin-top:10px}.empty-state{padding:10px;border:1px dashed var(--line);border-radius:7px;background:var(--panel2);color:var(--muted);font-size:12px;text-align:center}@media(max-width:620px){.handoff-strip{grid-template-columns:minmax(0,1fr) minmax(142px,38%)}.handoff{box-shadow:none}}
.modal.open.anchored{display:block}.modal.anchored .sheet{position:absolute;left:var(--sheet-left,16px);top:var(--sheet-top,16px);width:min(320px,calc(100vw - 32px))}"""
PORTAL_JS_TEMPLATE = """let installPrompt=null,lastAnchorRect=null;const HISTORY={key:'faryoHistoryDensity',values:['less','more'],labels:{less:'Less',more:'More'},totals:{less:10,more:18}};function historyValue(){const value=localStorage.getItem(HISTORY.key);return HISTORY.values.includes(value)?value:HISTORY.values[0];}function applyHistorySetting(){const value=historyValue(),btn=document.getElementById('historyBtn'),count=document.getElementById('sessionCount');if(btn){const meta=btn.querySelector('small');if(meta)meta.textContent=HISTORY.labels[value];}if(count)count.textContent=`Latest ${HISTORY.totals[value]}`;}function cycleHistory(){const values=HISTORY.values;localStorage.setItem(HISTORY.key,values[(values.indexOf(historyValue())+1)%values.length]);applyHistorySetting();refreshWorkbench().catch(()=>{});}window.FaryoAppearance?.apply();applyHistorySetting();if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});window.addEventListener('beforeinstallprompt',(event)=>{event.preventDefault();installPrompt=event;const btn=document.getElementById('installApp');if(btn)btn.hidden=false;});document.addEventListener('pointerdown',(event)=>{const el=event.target.closest('button,a,.session-card,.package-card,[role="button"]');if(!el)return;const rect=el.getBoundingClientRect();lastAnchorRect={left:rect.left,right:rect.right,top:rect.top,bottom:rect.bottom};},{capture:true,passive:true});document.addEventListener('click',(event)=>{const settings=document.getElementById('settings');if(event.target.closest('#settings>button'))settings.classList.toggle('open');else if(!event.target.closest('#settings'))settings.classList.remove('open');const appearanceBtn=event.target.closest?.('.appearance-btn');if(appearanceBtn?.id==='themeBtn'){window.FaryoAppearance?.cycle('theme');return;}if(appearanceBtn?.id==='fontBtn'){window.FaryoAppearance?.cycle('font');return;}if(appearanceBtn?.id==='sizeBtn'){window.FaryoAppearance?.cycle('size');return;}if(event.target.closest?.('#historyBtn')){cycleHistory();return;}const installBtn=event.target.closest?.('#installApp');if(installBtn&&installPrompt){installPrompt.prompt();installPrompt=null;installBtn.hidden=true;}});
const WORKBENCH_CACHE_KEY='faryoWorkbenchSnapshot';const labels=__LABELS_JS__;let draggedPackage=null;let touchDrag=null;let assetTargetPackage=null;let actionBusy=false;
function storeWorkbench(data){try{sessionStorage.setItem(WORKBENCH_CACHE_KEY,JSON.stringify({storedAt:Date.now(),data}));}catch(_error){}}
function restoreWorkbench(){try{const cached=JSON.parse(sessionStorage.getItem(WORKBENCH_CACHE_KEY)||'null');if(cached?.data)renderWorkbench(cached.data);}catch(_error){}}
function markRoutes(entries){for(const item of entries||[]){const chip=document.getElementById(`route-${item.id}`);if(!chip)continue;chip.className=`route-chip ${item.state||'error'}`;const state=chip.querySelector('.route-state');if(state){state.textContent=item.stateText||'—';state.title=item.detail||item.stateText||'';}}}
function localSessionTime(item){const ts=Number(item.updatedTs||0);if(!Number.isFinite(ts)||ts<=0)return item.updatedAt||'';const date=new Date(ts*1000),now=new Date(),sameDay=date.toDateString()===now.toDateString();return new Intl.DateTimeFormat(undefined,sameDay?{hour:'2-digit',minute:'2-digit'}:{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(date);}
function moveGhost(touch){if(!touchDrag)return;touchDrag.ghost.style.left=`${touch.clientX}px`;touchDrag.ghost.style.top=`${touch.clientY}px`;}
function clearDropTargets(){document.querySelectorAll('.session-card.drop-target').forEach(el=>el.classList.remove('drop-target'));}function childByKey(container,key){return Array.from(container.children).find(el=>el.dataset.key===key);}function cardSig(item){try{return JSON.stringify(item);}catch(_err){return '';}}function syncChildren(container,items,keyFn,renderFn,emptyText){const list=items||[];if(!list.length){if(container.dataset.empty!==emptyText){container.replaceChildren(empty(emptyText));container.dataset.empty=emptyText;}return;}container.dataset.empty='';const seen=new Set();list.forEach((item,index)=>{const key=String(keyFn(item)),sig=cardSig(item);let node=childByKey(container,key);if(!node||node.dataset.sig!==sig){const next=renderFn(item);next.dataset.key=key;next.dataset.sig=sig;if(node)node.replaceWith(next);node=next;}seen.add(key);const ref=container.children[index];if(ref!==node)container.insertBefore(node,ref||null);});Array.from(container.children).forEach(node=>{if(!seen.has(node.dataset.key||''))node.remove();});}
function packageCard(item){const card=document.createElement('div');card.className='package-card';card.draggable=item.status==='pending';card.dataset.packageId=item.id;const assets=(item.assets||[]).length,status=item.status==='pending'?'Pending':'Delivered',source=item.source||'Faryo';card.innerHTML=`<div><strong>${escapeHtml(item.title||'Untitled handoff')}</strong><span class="package-meta">${status} · ${assets} attachment${assets===1?'':'s'} · ${escapeHtml(source)}</span></div>${item.status==='pending'?'<button class="mini-btn add-asset" type="button">Add</button>':''}`;const addBtn=card.querySelector('.add-asset');addBtn?.addEventListener('click',(event)=>{event.preventDefault();event.stopPropagation();assetTargetPackage=item.id;document.getElementById('packageAssetInput')?.click();});addBtn?.addEventListener('touchstart',(event)=>event.stopPropagation(),{passive:true});card.addEventListener('dragstart',(event)=>{if(item.status!=='pending')return;draggedPackage=item.id;event.dataTransfer.setData('text/plain',item.id);card.classList.add('dragging');});card.addEventListener('dragend',()=>{draggedPackage=null;card.classList.remove('dragging');clearDropTargets();});card.addEventListener('touchstart',(event)=>{if(item.status!=='pending')return;const touch=event.touches[0];draggedPackage=item.id;card.classList.add('dragging');const ghost=card.cloneNode(true);ghost.classList.add('drag-ghost');ghost.style.width=`${card.getBoundingClientRect().width}px`;document.body.appendChild(ghost);touchDrag={ghost};moveGhost(touch);},{passive:false});card.addEventListener('touchmove',(event)=>{if(!touchDrag)return;event.preventDefault();const touch=event.touches[0];moveGhost(touch);clearDropTargets();const target=document.elementFromPoint(touch.clientX,touch.clientY)?.closest('.session-card');if(target&&target.dataset.agentSessionId)target.classList.add('drop-target');},{passive:false});card.addEventListener('touchend',async(event)=>{if(touchDrag)event.preventDefault();const touch=event.changedTouches[0];const target=document.elementFromPoint(touch.clientX,touch.clientY)?.closest('.session-card');card.classList.remove('dragging');clearDropTargets();if(touchDrag)touchDrag.ghost.remove();touchDrag=null;if(target&&target.dataset.agentSessionId)await injectPackage(item.id,target.dataset.route,target.dataset.session,target.dataset.agentSessionId,target.dataset.source);draggedPackage=null;},{passive:false});card.addEventListener('touchcancel',()=>{card.classList.remove('dragging');clearDropTargets();if(touchDrag)touchDrag.ghost.remove();touchDrag=null;draggedPackage=null;});return card;}
function placeSheet(modal){if(!lastAnchorRect){modal.classList.remove('anchored');return;}const margin=16,gap=8,sheet=modal.querySelector('.sheet'),width=Math.min(320,innerWidth-margin*2),center=(lastAnchorRect.left+lastAnchorRect.right)/2;modal.classList.add('open','anchored');const height=sheet.offsetHeight,left=innerWidth<620?(innerWidth-width)/2:Math.max(margin,Math.min(innerWidth-width-margin,center-width/2)),below=lastAnchorRect.bottom+gap,above=lastAnchorRect.top-height-gap,top=below+height+margin<=innerHeight?below:Math.max(margin,above);modal.style.setProperty('--sheet-left',`${left}px`);modal.style.setProperty('--sheet-top',`${top}px`);}
function sheet(title,body,choices){return new Promise(resolve=>{const modal=document.getElementById('modal'),list=document.getElementById('modalChoices'),actions=document.getElementById('modalActions');document.getElementById('modalTitle').textContent=title;document.getElementById('modalBody').textContent=body||'';const done=(value)=>{modal.classList.remove('open','anchored');modal.onclick=null;resolve(value);};list.replaceChildren(...(choices||[]).map(item=>{const btn=document.createElement('button');btn.type='button';btn.className=`choice-btn${item.danger?' danger':''}`;btn.disabled=!!item.disabled;btn.innerHTML=`<strong>${escapeHtml(item.label)}</strong>${item.meta?`<span>${escapeHtml(item.meta)}</span>`:''}`;btn.addEventListener('click',()=>done(item.value));return btn;}));const cancel=document.createElement('button');cancel.type='button';cancel.className='mini-btn';cancel.textContent='Cancel';cancel.addEventListener('click',()=>done(null));actions.replaceChildren(cancel);modal.onclick=(event)=>{if(event.target===modal)done(null);};placeSheet(modal);modal.classList.add('open');});}
async function notice(title,body){await sheet(title,body,[{label:'OK',value:'ok'}]);}
async function withBusy(task){if(actionBusy)return;actionBusy=true;try{return await task();}catch(error){await notice('Action failed',error.message||String(error));}finally{actionBusy=false;}}
async function selectNewRoute(entries,label){const online=(entries||[]).filter(e=>['online','slow'].includes(e.state));if(!online.length){await notice('No endpoint online','No online endpoint can start sessions.');return null;}const choices=online.map(e=>({label:e.label||labels[e.id]||e.id,meta:`${e.id} · ${e.activeCount||0}/${e.maxRunning||0}${e.canCreate?'':' · limit reached'}`,value:e.id,disabled:!e.canCreate}));const available=choices.filter(item=>!item.disabled);if(!available.length){await sheet('Agent limit reached','Close a running session first.',choices);return null;}if(online.length===1&&available.length===1)return available[0].value;return await sheet('Select endpoint',`Choose where ${label} starts.`,choices);}
function newAgentCard(item){const {entries,command,label}=item,card=document.createElement('button');card.type='button';card.className='session-card';card.innerHTML=`<div><div class="session-title">+ ${label}</div><div class="session-meta">$ ${command}</div></div><div class="arrow">›</div>`;card.addEventListener('click',()=>withBusy(async()=>{const route=await selectNewRoute(entries,label);if(!route)return;const original=card.innerHTML;card.disabled=true;card.innerHTML=`<div><div class="session-title">Starting ${label}...</div><div class="session-meta">$ ${command}</div></div><div class="arrow">↗</div>`;try{await agentNew(route,command);}finally{card.disabled=false;card.innerHTML=original;}}));return card;}
function sessionCard(item){const targetSession=item.tmuxSession||'',agentSessionId=item.id||'',source=item.source||'',active=!!targetSession,running=active&&!!item.agentRunning,blocked=!!item.limitReached;const card=document.createElement('div');card.className=`session-card${active?'':' inactive'}${running?' running':(active?' waiting':'')}`;card.dataset.route=item.route;card.dataset.session=targetSession;card.dataset.agentSessionId=agentSessionId;card.dataset.source=source;const state=active?(running?'Running':'Waiting'):(blocked?'Limit reached':'Resume'),where=item.cwdLabel||item.cwd||'',updatedAt=localSessionTime(item),agent=source==='claude-code'?'Claude':(source==='codex-cli'?'Codex':'Runtime'),title=[item.title||item.id||'Untitled session',item.gitLabel||''].filter(Boolean).join(' ');card.innerHTML=`<div><div class="session-title">${escapeHtml(title)}</div><div class="session-meta">${escapeHtml(item.routeLabel||labels[item.route]||item.route)} · ${agent}${where?` · ${escapeHtml(where)}`:''} · ${escapeHtml(updatedAt)} · ${state}</div></div><div>${active?'<button class="mini-btn close-session" type="button">Close</button>':'<span class="arrow">›</span>'}</div>`;card.title=[title,item.cwd||'',updatedAt,state].filter(Boolean).join(' · ');card.addEventListener('click',(event)=>withBusy(async()=>{if(event.target.closest('.close-session')){event.preventDefault();event.stopPropagation();await closeSession(item.route,targetSession);return;}if(active){location.href=`/${item.route}/?session=${encodeURIComponent(targetSession)}`;return;}if(!agentSessionId)return;event.preventDefault();if(blocked){await notice('Agent limit reached','Close a running session first.');return;}await resumeSession(item.route,agentSessionId,source);}));card.addEventListener('dragover',(event)=>{if(draggedPackage&&agentSessionId){event.preventDefault();card.classList.add('drop-target');}});card.addEventListener('dragleave',()=>card.classList.remove('drop-target'));card.addEventListener('drop',async(event)=>{event.preventDefault();card.classList.remove('drop-target');const packageId=event.dataTransfer.getData('text/plain')||draggedPackage;if(packageId)await injectPackage(packageId,item.route,targetSession,agentSessionId,source);});return card;}
async function agentNew(route,command){const res=await fetch('/api/agent/new',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({route,command})}),data=await res.json();if(!data.ok)throw new Error(data.error||'Failed to create session');location.href=data.redirect;}
async function resumeSession(route,agentSessionId,source){const res=await fetch('/api/agent/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({route,agent_session_id:agentSessionId,source})}),data=await res.json();if(!data.ok)throw new Error(data.error||'Failed to resume session');location.href=data.redirect||`/${route}/?session=${encodeURIComponent(data.session)}`;}
async function closeSession(route,session){const ok=await sheet('Close Session','This closes the running session. Busy sessions may refuse to close.',[{label:'Close Session',meta:session,value:'ok',danger:true}]);if(ok!=='ok')return;const res=await fetch(`/${route}/api/session/close`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session})}),data=await res.json();if(!data.ok)throw new Error(data.error||'Failed to close session');await refreshWorkbench();}
async function injectPackage(packageId,route,session,agentSessionId,source){const payload={package_id:packageId,route};if(session)payload.session=session;if(agentSessionId){payload.agent_session_id=agentSessionId;payload.source=source;}const res=await fetch('/api/bridge-inject',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),data=await res.json();if(!data.ok)throw new Error(data.error||'Failed to inject package');location.href=data.redirect||`/${route}/${session?`?session=${encodeURIComponent(session)}`:''}`;}
function renderWorkbench(data){markRoutes(data.entries||[]);const packages=data.inbox||data.packages||[],sessions=data.sessions||[],entries=data.entries||[],pkg=packages[0],packageItems=pkg?[pkg]:[],allowedCommands=new Set(data.newSessionCommands||['codex']),launchers=[{id:'new-codex',command:'codex',label:'Codex CLI',entries},{id:'new-claude',command:'claude',label:'Claude Code',entries}].filter(item=>allowedCommands.has(item.command));document.getElementById('packageCount').textContent=pkg?(pkg.status==='pending'?'· New':'· Done'):'· Empty';syncChildren(document.getElementById('packageList'),packageItems,item=>`pkg-${item.id}`,packageCard,'No handoff package');syncChildren(document.getElementById('newSessionSlot'),launchers,item=>item.id,newAgentCard,'');syncChildren(document.getElementById('sessionList'),sessions,item=>`session-${item.route}-${item.id}-${item.tmuxSession||''}`,sessionCard,'No sessions');}
async function refreshWorkbench(){const res=await fetch(`/api/workbench?history=${encodeURIComponent(historyValue())}`,{cache:'no-store'}),data=await res.json();storeWorkbench(data);renderWorkbench(data);return data;}
function empty(text){const el=document.createElement('div');el.className='empty-state';el.textContent=text;return el;}
function escapeHtml(value){return String(value).replace(/[&<>"']/g,(ch)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
function fileToAttachment(file){return new Promise((resolve,reject)=>{if(file.size>20*1024*1024){reject(new Error('Attachment must be 20 MB or smaller'));return;}const reader=new FileReader();reader.onload=()=>resolve({file_name:file.name||'attachment',mime_type:file.type||'application/octet-stream',data_url:String(reader.result||'')});reader.onerror=()=>reject(reader.error||new Error('Failed to read attachment'));reader.readAsDataURL(file);});}
async function filesToAttachments(fileList){const files=Array.from(fileList||[]).slice(0,4),attachments=[];for(const file of files)attachments.push(await fileToAttachment(file));return attachments;}
async function createPackage(files){const attachments=await filesToAttachments(files);if(!attachments.length)return;const title=attachments.length===1?attachments[0].file_name:`${attachments.length} files`;const res=await fetch('/api/bridge-packages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,source:'Manual upload',intent:'Transfer these attachments to a selected session.',attachments})}),data=await res.json();if(!data.ok)throw new Error(data.error||'Failed to create handoff package');await refreshWorkbench();}
async function appendAttachmentsToPackage(packageId,files){const attachments=await filesToAttachments(files);if(!attachments.length)return;const res=await fetch('/api/bridge-package-assets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({package_id:packageId,attachments})}),data=await res.json();if(!data.ok)throw new Error(data.error||'Failed to add attachments');await refreshWorkbench();}
document.getElementById('newPackage')?.addEventListener('click',()=>document.getElementById('packageInput')?.click());
document.getElementById('packageInput')?.addEventListener('change',async(event)=>{try{await createPackage(event.target.files);}catch(error){alert(error.message||error);}finally{event.target.value='';}});
document.getElementById('packageAssetInput')?.addEventListener('change',async(event)=>{try{if(assetTargetPackage)await appendAttachmentsToPackage(assetTargetPackage,event.target.files);}catch(error){alert(error.message||error);}finally{assetTargetPackage=null;event.target.value='';}});
const handoffBox=document.getElementById('handoffBox');handoffBox?.addEventListener('dragover',(event)=>{if(event.dataTransfer?.types?.includes('Files')){event.preventDefault();handoffBox.classList.add('drop-ready');}});handoffBox?.addEventListener('dragleave',()=>handoffBox.classList.remove('drop-ready'));handoffBox?.addEventListener('drop',async(event)=>{if(!event.dataTransfer?.files?.length)return;event.preventDefault();handoffBox.classList.remove('drop-ready');try{await createPackage(event.dataTransfer.files);}catch(error){alert(error.message||error);}});
function initialRefresh(){refreshWorkbench().catch(()=>{document.getElementById('sessionList').replaceChildren(empty('Workbench failed to load'));});}
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
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>Faryo</title><meta name="theme-color" content="#F7F0E5" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#17130F" media="(prefers-color-scheme: dark)"><link rel="manifest" href="/manifest.json"><link rel="icon" href="/icons/favicon.png?v=faryo-ui-1" type="image/png"><link rel="apple-touch-icon" href="/icons/pwa-light-192.png"><script src="/appearance.js?v=unified-1"></script><link rel="stylesheet" href="/appearance.css?v=unified-1">
<style>
{PORTAL_CSS}
</style></head><body><div class="shell">
<header><a class="brand" href="/projects" aria-label="Open project table"><img class="brand-logo" src="/icons/faryo-mark.png?v=faryo-ui-1" alt=""><div><h1>Faryo</h1><div class="subtitle">{safe_user} · Carry work forward</div></div></a><div class="settings" id="settings"><button class="settings-trigger" type="button" aria-label="Settings"><span class="settings-icon">⚙</span></button><div class="settings-menu" aria-label="Settings panel"><button id="installApp" class="settings-row install-row" type="button" hidden><span><strong>Install app</strong><small>Add Faryo to home screen</small></span><em>↗</em></button><div class="menu-title">Appearance</div><button id="themeBtn" class="settings-row appearance-btn" type="button"><span><strong>Theme</strong><small>System</small></span><em>↻</em></button><button id="fontBtn" class="settings-row appearance-btn" type="button"><span><strong>Font</strong><small>Default</small></span><em>↻</em></button><button id="sizeBtn" class="settings-row appearance-btn" type="button"><span><strong>Size</strong><small>Normal</small></span><em>↻</em></button><button id="historyBtn" class="settings-row" type="button"><span><strong>History</strong><small>Less</small></span><em>↻</em></button><div class="menu-title">Account</div><a class="settings-row" href="/password"><span><strong>Change password</strong></span><em>›</em></a><a class="settings-row" href="/logout"><span><strong>Sign out</strong></span><em>›</em></a></div></div></header>
<nav class="routes" aria-label="Endpoint status">{chips_html}</nav><div class="handoff-strip"><section class="handoff" id="handoffBox" aria-label="Handoff inbox"><div class="handoff-head"><h2>Handoff <span class="count" id="packageCount">Empty</span></h2><button class="mini-btn primary-btn" id="newPackage" type="button">Add files</button></div><input id="packageInput" type="file" accept="image/*,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.md,.txt,.csv,.json,.rtf" multiple hidden><input id="packageAssetInput" type="file" accept="image/*,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.md,.txt,.csv,.json,.rtf" multiple hidden><div class="package-list" id="packageList"><div class="empty-state">No handoff package</div></div></section><div class="new-session-slot" id="newSessionSlot"><div class="empty-state">Loading</div></div></div>
<main><div class="section-head"><h2>Session History</h2><span class="count" id="sessionCount">Latest 10</span></div><section class="sessions" id="sessionList"><div class="empty-state">Loading sessions...</div></section></main>
</div><div class="modal" id="modal"><div class="sheet"><h3 id="modalTitle"></h3><p id="modalBody"></p><div class="choice-list" id="modalChoices"></div><div class="modal-actions" id="modalActions"></div></div></div><script>
{portal_js}
</script></body></html>'''


AUTH_CSS = """*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:var(--bg);color:var(--text);font-family:var(--app-font)}main{width:min(100%,420px)}.auth-brand{display:flex;align-items:center;gap:12px;margin-bottom:8px}.auth-logo{width:48px;height:48px;border-radius:13px;flex:0 0 auto}h1{margin:0 0 8px;font-size:26px;letter-spacing:0}p{margin:0 0 22px;color:var(--muted);line-height:1.5}label{display:block;margin:12px 0 7px;color:var(--muted);font-size:14px}input{width:100%;height:52px;border:1px solid var(--line);border-radius:8px;padding:0 13px;background:var(--panel);color:var(--text);font:inherit;outline:none}input:focus{border-color:var(--accent)}.password-row{position:relative}.password-row input{padding-right:58px}.toggle{position:absolute;right:6px;top:6px;display:grid;place-items:center;width:40px;height:40px;min-height:40px;border:0;border-radius:8px;background:var(--toggle-bg);color:var(--text)}.toggle svg{width:21px;height:21px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.toggle .eye-off,.toggle.is-visible .eye{display:none}.toggle.is-visible .eye-off{display:block}.submit{width:100%;height:52px;margin-top:18px;border:0;border-radius:8px;background:var(--accent);color:var(--on-accent);font-weight:700;font-size:16px}.secondary{display:block;margin-top:14px;color:var(--muted);text-align:center;text-decoration:none}.error{min-height:20px;margin-top:12px;color:var(--danger);font-size:14px}"""
AUTH_SCRIPT = """document.querySelectorAll('.password-row').forEach((row)=>{const input=row.querySelector('input');const toggle=row.querySelector('button');toggle.addEventListener('click',()=>{const visible=input.type==='text';input.type=visible?'password':'text';toggle.classList.toggle('is-visible',!visible);toggle.setAttribute('aria-label',visible?'Show password':'Hide password');toggle.title=visible?'Show password':'Hide password';});});"""
EYE_BUTTON = """<button class="toggle" type="button" aria-label="Show password" title="Show password"><svg class="eye" viewBox="0 0 24 24"><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="3"/></svg><svg class="eye-off" viewBox="0 0 24 24"><path d="M3 3l18 18"/><path d="M10.7 5.2A10.8 10.8 0 0 1 12 5c6.5 0 10 7 10 7a17.7 17.7 0 0 1-3.2 4.1"/><path d="M6.6 6.6C3.6 8.6 2 12 2 12s3.5 7 10 7a10.5 10.5 0 0 0 4.2-.9"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg></button>"""


def password_field(field_id: str, name: str, label: str, autocomplete: str, minlength: int | None = None) -> str:
    min_attr = f' minlength="{minlength}"' if minlength else ""
    return f"""<label for="{field_id}">{label}</label><div class="password-row"><input id="{field_id}" name="{name}" type="password" autocomplete="{autocomplete}" autocapitalize="none" spellcheck="false"{min_attr} required>{EYE_BUTTON}</div>"""


def auth_page(title: str, heading: str, intro: str, action: str, autocomplete: str, body: str, error: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>{title}</title><meta name="theme-color" content="#F7F0E5" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#17130F" media="(prefers-color-scheme: dark)"><link rel="icon" href="/icons/favicon.png?v=faryo-ui-1" type="image/png"><link rel="apple-touch-icon" href="/icons/pwa-light-192.png"><script src="/appearance.js?v=unified-1"></script><link rel="stylesheet" href="/appearance.css?v=unified-1"><style>{AUTH_CSS}</style></head>
<body><main><div class="auth-brand"><img class="auth-logo" src="/icons/faryo-mark.png?v=faryo-ui-1" alt=""><div><h1>{heading}</h1><p>{intro}</p></div></div><form method="post" action="{action}" autocomplete="{autocomplete}">{body}<div class="error">{html_escape(error)}</div></form></main><script>{AUTH_SCRIPT}</script></body></html>"""


def login_html(next_target: str, error: str = "") -> str:
    body = (
        f'<input type="hidden" name="next" value="{html_escape(next_target)}">'
        '<label for="username">Username</label><input id="username" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required>'
        + password_field("password", "password", "Password", "current-password")
        + '<button class="submit" type="submit">Sign in</button>'
    )
    return auth_page("Faryo Sign In", "Faryo", "Enter your gateway username and password.", "/login", "on", body, error)


def password_html(error: str = "") -> str:
    body = (
        password_field("current_password", "current_password", "Current password", "current-password")
        + password_field("new_password", "new_password", "New password", "new-password", 12)
        + password_field("confirm_password", "confirm_password", "Confirm new password", "new-password", 12)
        + '<button class="submit" type="submit">Save password</button><a class="secondary" href="/">Back to Faryo</a>'
    )
    return auth_page("Faryo Change Password", "Change password", "Update the gateway password. Changes take effect immediately.", "/password", "off", body, error)


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
