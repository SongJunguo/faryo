#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FARYO_GATEWAY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FARYO_HOME="${FARYO_HOME:-$HOME/.faryo}"
OWNER_ENV="${FARYO_OWNER_ENV:-$FARYO_HOME/owner/config/faryo.env}"
GATEWAY_ENV="${FARYO_GATEWAY_ENV:-$FARYO_HOME/gateway/config/faryo.env}"
GATEWAY_AUTH_CONFIG="${GATEWAY_AUTH_CONFIG:-$FARYO_HOME/gateway/config/gateway-auth.json}"
FARYO_GATEWAY_ROUTE="${FARYO_GATEWAY_ROUTE:-txy}"
FARYO_PYTHON="${FARYO_PYTHON:-python3}"
FARYO_GATEWAY_WORKSPACE_ROOT="${FARYO_GATEWAY_WORKSPACE_ROOT:-}"
FARYO_GATEWAY_RESET_AUTH="${FARYO_GATEWAY_RESET_AUTH:-0}"

case "$FARYO_GATEWAY_ROUTE" in
  hp|txy|pc) ;;
  *) echo "unsupported FARYO_GATEWAY_ROUTE: $FARYO_GATEWAY_ROUTE" >&2; exit 2 ;;
esac

if [[ ! -f "$OWNER_ENV" ]]; then
  echo "missing Owner environment: $OWNER_ENV" >&2
  exit 2
fi
if ! "$FARYO_PYTHON" -c 'import bcrypt' >/dev/null 2>&1; then
  echo "Gateway Python cannot import bcrypt: $FARYO_PYTHON" >&2
  exit 2
fi

case "${FARYO_GATEWAY_RESET_AUTH,,}" in
  1|true|yes) GENERATE_GATEWAY_AUTH=1 ;;
  0|false|no) [[ -f "$GATEWAY_AUTH_CONFIG" ]] && GENERATE_GATEWAY_AUTH=0 || GENERATE_GATEWAY_AUTH=1 ;;
  *) echo "FARYO_GATEWAY_RESET_AUTH must be 0 or 1" >&2; exit 2 ;;
esac

export FARYO_HOME OWNER_ENV GATEWAY_ENV GATEWAY_AUTH_CONFIG FARYO_GATEWAY_ROUTE FARYO_PYTHON FARYO_GATEWAY_WORKSPACE_ROOT GENERATE_GATEWAY_AUTH FARYO_GATEWAY_RESET_AUTH
"$FARYO_PYTHON" - <<'PY'
import os
import secrets
import shlex
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        try:
            parsed = shlex.split(raw, posix=True)
        except ValueError:
            parsed = []
        values[key] = parsed[0] if parsed else raw.strip().strip("'\"")
    return values


def render(key: str, value: str) -> str:
    return f"{key}={shlex.quote(str(value))}"


owner_env = Path(os.environ["OWNER_ENV"]).expanduser()
gateway_env = Path(os.environ["GATEWAY_ENV"]).expanduser()
auth_file = Path(os.environ["GATEWAY_AUTH_CONFIG"]).expanduser()
route = os.environ["FARYO_GATEWAY_ROUTE"]
owner = read_env(owner_env)
existing = read_env(gateway_env) if gateway_env.exists() else {}
owner_token = owner.get("FARYO_OWNER_TOKEN", "")
if not owner_token:
    raise ValueError("Owner environment has no FARYO_OWNER_TOKEN")

gateway_env.parent.mkdir(parents=True, exist_ok=True)
auth_file.parent.mkdir(parents=True, exist_ok=True)
password_file = gateway_env.parent / "initial-password"
reset_auth = os.environ["FARYO_GATEWAY_RESET_AUTH"].lower() in {"1", "true", "yes"}
generate_auth = os.environ["GENERATE_GATEWAY_AUTH"] == "1"
if reset_auth or (generate_auth and not password_file.exists()):
    password_file.write_text(secrets.token_urlsafe(24) + "\n", encoding="utf-8")
if password_file.exists():
    password_file.chmod(0o600)

workspace = (
    os.environ.get("FARYO_GATEWAY_WORKSPACE_ROOT")
    or owner.get("FARYO_PROJECT_WORKBENCH_PROJECTS_ROOT")
    or str(Path.home() / "brain" / "projects")
)
inbox = owner.get("FARYO_OWNER_INBOX_DIR") or str(Path.home() / ".faryo" / "owner" / "data" / "inbox")
route_upper = route.upper()
values = {
    "FARYO_GATEWAY_USER": existing.get("FARYO_GATEWAY_USER") or "faryo",
    "FARYO_PYTHON": os.environ["FARYO_PYTHON"],
    "FARYO_GATEWAY_ROUTES": route,
    f"FARYO_{route_upper}_OWNER_TOKEN": owner_token,
    f"FARYO_{route_upper}_OWNER_HOST": owner.get("FARYO_OWNER_HOST") or "127.0.0.1",
    f"FARYO_{route_upper}_OWNER_PORT": owner.get("FARYO_OWNER_PORT") or "8765",
    f"FARYO_{route_upper}_OWNER_LABEL": route_upper,
    "FARYO_DEFAULT_WORKSPACE": workspace,
    "FARYO_DEFAULT_FILE_INBOX": inbox,
    "GATEWAY_HOST": "127.0.0.1",
    "GATEWAY_PORT": existing.get("GATEWAY_PORT") or "8780",
}
if password_file.exists():
    values["FARYO_GATEWAY_PASSWORD_FILE"] = str(password_file)
for key in ("FARYO_MCP_TOKEN", "FARYO_MCP_USER", "FARYO_MCP_CORS_ORIGIN", "FARYO_ICP_RECORD"):
    if existing.get(key):
        values[key] = existing[key]

order = [
    "FARYO_GATEWAY_USER",
    "FARYO_GATEWAY_PASSWORD_FILE",
    "FARYO_PYTHON",
    "FARYO_GATEWAY_ROUTES",
    f"FARYO_{route_upper}_OWNER_TOKEN",
    f"FARYO_{route_upper}_OWNER_HOST",
    f"FARYO_{route_upper}_OWNER_PORT",
    f"FARYO_{route_upper}_OWNER_LABEL",
    "FARYO_DEFAULT_WORKSPACE",
    "FARYO_DEFAULT_FILE_INBOX",
    "GATEWAY_HOST",
    "GATEWAY_PORT",
    "FARYO_MCP_TOKEN",
    "FARYO_MCP_USER",
    "FARYO_MCP_CORS_ORIGIN",
    "FARYO_ICP_RECORD",
]
gateway_env.write_text("\n".join(render(key, values[key]) for key in order if key in values) + "\n", encoding="utf-8")
gateway_env.chmod(0o600)
PY

if [[ "$GENERATE_GATEWAY_AUTH" == "1" ]]; then
  FARYO_GATEWAY_ENV="$GATEWAY_ENV" GATEWAY_AUTH_CONFIG="$GATEWAY_AUTH_CONFIG" \
    "$FARYO_PYTHON" "$FARYO_GATEWAY_ROOT/scripts/generate-gateway-auth-config.py" >/dev/null
  printf 'generated Gateway login config: %s\n' "$GATEWAY_AUTH_CONFIG"
else
  printf 'preserved existing Gateway login config: %s\n' "$GATEWAY_AUTH_CONFIG"
fi

chmod 600 "$GATEWAY_ENV" "$GATEWAY_AUTH_CONFIG"
if [[ -f "$(dirname "$GATEWAY_ENV")/initial-password" ]]; then
  chmod 600 "$(dirname "$GATEWAY_ENV")/initial-password"
fi
printf 'initialized private Gateway config: %s\n' "$GATEWAY_ENV"
if [[ -f "$(dirname "$GATEWAY_ENV")/initial-password" ]]; then
  printf 'initial password file: %s\n' "$(dirname "$GATEWAY_ENV")/initial-password"
fi
