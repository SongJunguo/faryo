#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

import bcrypt

ROOT = Path(__file__).resolve().parents[1]
FARYO_HOME = Path(os.environ.get("FARYO_HOME", str(Path.home() / ".faryo"))).expanduser()
ENV_FILE = Path(
    os.environ.get("FARYO_GATEWAY_ENV")
    or os.environ.get("FARYO_ENV_FILE")
    or FARYO_HOME / "gateway" / "config" / "faryo.env"
).expanduser()
AUTH_FILE = Path(
    os.environ.get("GATEWAY_AUTH_CONFIG")
    or FARYO_HOME / "gateway" / "config" / "gateway-auth.json"
).expanduser()
ROUTES = ("hp", "txy", "pc")


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


def route_value(values: dict[str, str], route: str, key: str, default: str) -> str:
    return values.get(f"FARYO_{route.upper()}_{key}") or values.get(f"FARYO_DEFAULT_{key}") or default


def path_value(value: str) -> str:
    return str(Path(os.path.expandvars(value)).expanduser())


def gateway_password(values: dict[str, str]) -> str:
    value = values.get("FARYO_GATEWAY_PASSWORD", "")
    if value:
        return value
    password_file = values.get("FARYO_GATEWAY_PASSWORD_FILE", "")
    if password_file:
        password = Path(path_value(password_file)).read_text(encoding="utf-8").strip()
        if password:
            return password
    raise ValueError("missing FARYO_GATEWAY_PASSWORD or FARYO_GATEWAY_PASSWORD_FILE")


def configured_routes(values: dict[str, str]) -> list[str]:
    raw = values.get("FARYO_GATEWAY_ROUTES", ",".join(ROUTES))
    routes: list[str] = []
    unknown: list[str] = []
    for item in raw.split(","):
        route = item.strip().lower()
        if not route:
            continue
        if route not in ROUTES:
            unknown.append(route)
        elif route not in routes:
            routes.append(route)
    if unknown:
        raise ValueError("unsupported FARYO_GATEWAY_ROUTES: " + ", ".join(unknown))
    return routes


def main() -> None:
    values = read_env(ENV_FILE)
    username = values["FARYO_GATEWAY_USER"]
    password = gateway_password(values).encode("utf-8")
    routes = configured_routes(values)
    if not routes:
        raise ValueError("FARYO_GATEWAY_ROUTES has no valid route")
    workspace = path_value(values.get("FARYO_DEFAULT_WORKSPACE") or str(Path.home() / ".faryo" / "workspaces" / "default"))
    file_inbox = path_value(values.get("FARYO_DEFAULT_FILE_INBOX") or str(Path.home() / ".faryo" / "owner" / "data" / "inbox"))
    payload = {
        "users": {
            username: {
                "bcrypt_hash": bcrypt.hashpw(password, bcrypt.gensalt()).decode("utf-8"),
                "auth_epoch": 0,
                "routes": routes,
                "default_route": "txy" if "txy" in routes else routes[0],
                "workspace_roots": {route: path_value(route_value(values, route, "WORKSPACE", workspace)) for route in routes},
                "file_inbox_roots": {route: path_value(route_value(values, route, "FILE_INBOX", file_inbox)) for route in routes},
            }
        }
    }
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTH_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    AUTH_FILE.chmod(0o600)
    print(f"wrote {AUTH_FILE}")


if __name__ == "__main__":
    main()
