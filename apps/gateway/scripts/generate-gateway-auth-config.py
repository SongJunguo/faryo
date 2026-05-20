#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

import bcrypt

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "config" / "faryo.env"
AUTH_FILE = ROOT / "config" / "gateway-auth.json"
ROUTES = ("hp", "gcp", "pc")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def route_value(values: dict[str, str], route: str, key: str, default: str) -> str:
    return values.get(f"FARYO_{route.upper()}_{key}") or values.get(f"FARYO_DEFAULT_{key}") or default


def path_value(value: str) -> str:
    return str(Path(os.path.expandvars(value)).expanduser())


def configured_routes(values: dict[str, str]) -> list[str]:
    raw = values.get("FARYO_GATEWAY_ROUTES", ",".join(ROUTES))
    routes = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return [route for route in ROUTES if route in routes]


def main() -> None:
    values = read_env(ENV_FILE)
    username = values["FARYO_GATEWAY_USER"]
    password = values["FARYO_GATEWAY_PASSWORD"].encode("utf-8")
    routes = configured_routes(values)
    if not routes:
        raise ValueError("FARYO_GATEWAY_ROUTES has no valid route")
    namespace = values.get("FARYO_DEFAULT_NAMESPACE") or username
    workspace = path_value(values.get("FARYO_DEFAULT_WORKSPACE") or str(Path.home() / ".faryo" / "workspaces" / "default"))
    file_inbox = path_value(values.get("FARYO_DEFAULT_FILE_INBOX") or str(Path.home() / ".faryo" / "owner" / "data" / "inbox"))
    payload = {
        "users": {
            username: {
                "bcrypt_hash": bcrypt.hashpw(password, bcrypt.gensalt()).decode("utf-8"),
                "auth_epoch": 0,
                "routes": routes,
                "default_route": "gcp" if "gcp" in routes else routes[0],
                "route_namespaces": {route: route_value(values, route, "NAMESPACE", namespace) for route in routes},
                "workspace_roots": {route: path_value(route_value(values, route, "WORKSPACE", workspace)) for route in routes},
                "file_inbox_roots": {route: path_value(route_value(values, route, "FILE_INBOX", file_inbox)) for route in routes},
            }
        }
    }
    AUTH_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    AUTH_FILE.chmod(0o600)
    print(f"wrote {AUTH_FILE}")


if __name__ == "__main__":
    main()
