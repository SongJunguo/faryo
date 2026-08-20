"""Gateway private configuration, users, route scopes, and store composition."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import shlex
import time
from typing import Any, Callable

import bcrypt

import bridge_packages
import control_audit


@dataclass(frozen=True)
class GatewayConfigRuntime:
    backends: dict[str, tuple[str, int, str]]
    load_backends: Callable[[dict[str, str]], dict[str, tuple[str, int, str]]]
    route_max_defaults: dict[str, int]
    route_max_limit: int
    clean_package_id: Callable[[str], str | None]
    normalize_bridge_asset: Callable[[Any], dict[str, Any] | None]
    bridge_asset_bytes: Callable[[dict[str, Any]], tuple[str, bytes]]
    bridge_mime_extensions: dict[str, str]
    now_ts: Callable[[], int]


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


class GatewayConfig:
    def __init__(
        self,
        auth_config: Path,
        owner_env: Path,
        portal_dir: Path,
        secret_file: Path,
        runtime: GatewayConfigRuntime,
    ) -> None:
        self.runtime = runtime
        self.auth_config = auth_config
        auth = json.loads(auth_config.read_text(encoding="utf-8"))
        env = read_env(owner_env)
        runtime.backends.clear()
        runtime.backends.update(runtime.load_backends(env))
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
        self._bridge_store = bridge_packages.BridgePackageStore(
            self.bridge_root,
            self.mcp_user,
            clean_package_id=runtime.clean_package_id,
            normalize_asset=runtime.normalize_bridge_asset,
            asset_bytes=runtime.bridge_asset_bytes,
            mime_extensions=runtime.bridge_mime_extensions,
            now_ts=runtime.now_ts,
        )
        self._control_audit_store = control_audit.ControlAuditStore(
            self.cookie_secret,
            self.control_audit_path,
            self.user_routes,
        )

    def load_owner_tokens(self, env: dict[str, str]) -> dict[str, str]:
        tokens: dict[str, str] = {}
        missing = []
        for route in self.runtime.backends:
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
        for route in self.runtime.backends:
            key = f"FARYO_{route.upper()}_MAX_RUNNING"
            raw = env.get(key, str(self.runtime.route_max_defaults[route])).strip()
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(
                    f"{key} must be an integer from 1 to {self.runtime.route_max_limit}"
                ) from exc
            if not 1 <= value <= self.runtime.route_max_limit:
                raise ValueError(f"{key} must be an integer from 1 to {self.runtime.route_max_limit}")
            limits[route] = value
        return limits

    def max_running(self, route: str) -> int:
        return self.route_max_running[route]

    def load_users(self, auth: dict[str, Any]) -> dict[str, dict[str, Any]]:
        if "users" in auth and isinstance(auth["users"], dict):
            source = auth["users"]
        else:
            username = str(auth["username"])
            source = {
                username: {
                    "bcrypt_hash": str(auth["bcrypt_hash"]),
                    "auth_epoch": int(auth.get("auth_epoch") or 0),
                    "routes": list(self.runtime.backends),
                }
            }
        users: dict[str, dict[str, Any]] = {}
        for username, payload in source.items():
            if not isinstance(payload, dict):
                continue
            name = str(username).strip()
            if not name:
                continue
            configured = payload.get("routes")
            if configured is None:
                routes = list(self.runtime.backends)
            elif isinstance(configured, list):
                routes = [route for route in configured if route in self.runtime.backends]
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
        return [route for route in user.get("routes", []) if route in self.runtime.backends]

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
        return self._control_audit_store.target_digest(value)

    def append_control_audit(self, **values: Any) -> None:
        self._control_audit_store.append(**values)

    def control_activity(self, username: str, limit: int = 30) -> list[dict[str, Any]]:
        return self._control_audit_store.activity(username, limit)

    def set_password(self, username: str, password: str) -> None:
        if username not in self.users:
            raise ValueError("unknown user")
        self.users[username]["bcrypt_hash"] = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")
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
        return self._bridge_store.asset_sources(payload)

    def save_bridge_package(self, payload: dict[str, Any], username: str) -> dict[str, Any]:
        return self._bridge_store.save(payload, username)

    def append_bridge_package_assets(
        self,
        package_id: str,
        asset_sources: list[Any],
        username: str,
    ) -> dict[str, Any]:
        return self._bridge_store.append_assets(package_id, asset_sources, username)

    def list_bridge_packages(self, username: str, status: str | None = None) -> list[dict[str, Any]]:
        return self._bridge_store.list(username, status)

    def cleanup_bridge_packages(self, current_time: int | None = None, force: bool = False) -> int:
        return self._bridge_store.cleanup(current_time, force)

    def bridge_package(self, package_id: str, username: str | None = None) -> dict[str, Any] | None:
        return self._bridge_store.get(package_id, username)

    def update_bridge_package(self, package: dict[str, Any]) -> None:
        self._bridge_store.update(package)
