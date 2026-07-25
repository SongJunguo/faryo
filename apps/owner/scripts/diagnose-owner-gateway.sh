#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FARYO_HOME="${FARYO_HOME:-$HOME/.faryo}"
ENV_FILE="${FARYO_OWNER_ENV:-${FARYO_ENV_FILE:-$FARYO_HOME/owner/config/faryo.env}}"
GATEWAY_ENV_FILE="${FARYO_GATEWAY_ENV:-$FARYO_HOME/gateway/config/faryo.env}"
GATEWAY_AUTH_FILE="${FARYO_GATEWAY_AUTH:-$FARYO_HOME/gateway/config/gateway-auth.json}"

status() {
  printf '%-28s %s\n' "$1" "$2"
}

load_owner_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    status "owner env" "missing: $ENV_FILE"
    exit 2
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  : "${FARYO_OWNER_HOST:=127.0.0.1}"
  : "${FARYO_OWNER_PORT:=8765}"
  : "${FARYO_OWNER_DIRECT_SESSION:=__faryo_no_default__}"
  : "${TUNNEL_SERVICE:=faryo-gateway-tunnel.service}"
}

json_field() {
  python3 - "$1" "$2" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
value = payload
for part in sys.argv[2].split('.'):
    value = value.get(part) if isinstance(value, dict) else None
print("" if value is None else value)
PY
}

owner_url() {
  printf 'http://%s:%s/%s' "$FARYO_OWNER_HOST" "$FARYO_OWNER_PORT" "$1"
}

curl_owner() {
  curl --noproxy '*' -fsS --connect-timeout 2 --max-time 5 "$@"
}

check_local_owner() {
  status "owner env" "$ENV_FILE"
  if [[ -z "${FARYO_OWNER_TOKEN:-}" || "${FARYO_OWNER_TOKEN:-}" == replace-* ]]; then
    status "owner token" "missing"
  else
    status "owner token" "configured"
  fi

  if curl_owner "$(owner_url health)" >/dev/null 2>&1; then
    status "local owner health" "ok"
  else
    status "local owner health" "failed"
    return 0
  fi

  if [[ -z "${FARYO_OWNER_TOKEN:-}" || "${FARYO_OWNER_TOKEN:-}" == replace-* ]]; then
    return 0
  fi
  if runtime=$(curl_owner -H "X-Owner-Token: $FARYO_OWNER_TOKEN" "$(owner_url api/status)" 2>/dev/null); then
    status "releaseVersion" "$(json_field "$runtime" releaseVersion)"
    OWNER_LABEL_SEEN="$(json_field "$runtime" ownerLabel)"
    status "owner label" "${OWNER_LABEL_SEEN:-unknown}"
    status "active session" "$(json_field "$runtime" session)"
    status "tmux target" "$(json_field "$runtime" tmuxAlive)"
  else
    status "owner api/status" "failed"
  fi
}

check_capture() {
  local session="${FARYO_OWNER_DIRECT_SESSION:-}"
  if [[ -z "$session" || "$session" == "__faryo_no_default__" ]]; then
    status "session capture" "skipped: no direct session"
    return 0
  fi
  if [[ -z "${FARYO_OWNER_TOKEN:-}" || "${FARYO_OWNER_TOKEN:-}" == replace-* ]]; then
    status "session capture" "skipped: missing token"
    return 0
  fi
  if curl_owner -H "X-Owner-Token: $FARYO_OWNER_TOKEN" "$(owner_url "api/capture?session=$session&lines=2")" >/dev/null 2>&1; then
    status "session capture" "ok: $session"
  else
    status "session capture" "failed: $session"
  fi
}

check_reverse_tunnel() {
  if command -v systemctl >/dev/null 2>&1; then
    state=$(systemctl --user is-active "$TUNNEL_SERVICE" 2>/dev/null || true)
    status "reverse tunnel service" "${state:-inactive} ($TUNNEL_SERVICE)"
  else
    status "reverse tunnel service" "skipped: systemctl not found"
  fi
  if [[ -n "${GATEWAY_TUNNEL_HOST:-}" && -n "${GATEWAY_TUNNEL_USER:-}" && -n "${GATEWAY_TUNNEL_REMOTE_PORT:-}" ]]; then
    status "reverse tunnel remote" "configured: 127.0.0.1:$GATEWAY_TUNNEL_REMOTE_PORT"
  else
    status "reverse tunnel remote" "skipped: tunnel env incomplete"
  fi
}

check_gateway_config() {
  if [[ ! -f "$GATEWAY_ENV_FILE" ]]; then
    status "gateway env" "not found on this host"
    return 0
  fi
  status "gateway env" "$GATEWAY_ENV_FILE"
  python3 - "$GATEWAY_ENV_FILE" "$GATEWAY_AUTH_FILE" "${OWNER_LABEL_SEEN:-${FARYO_OWNER_LABEL:-}}" <<'PY'
import json
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
auth_path = Path(sys.argv[2])
owner_label = sys.argv[3]
values = {}
for line in env_path.read_text(encoding="utf-8").splitlines():
    if line and not line.lstrip().startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        values[key] = value.strip().strip("'\"")
routes = [item.strip().lower() for item in values.get("FARYO_GATEWAY_ROUTES", "hp,txy,pc").split(",") if item.strip()]
print(f"gateway routes              {','.join(routes) or 'missing'}")
route = owner_label.lower()
if route in routes:
    token_key = f"FARYO_{route.upper()}_OWNER_TOKEN"
    token_state = "configured" if values.get(token_key) and not values[token_key].startswith("replace-") else "missing"
    print(f"owner route config          {route}: {token_state}")
elif owner_label:
    print(f"owner route config          missing for owner label: {owner_label}")
else:
    print("owner route config          unknown: owner label missing")
if auth_path.is_file():
    try:
        users = json.loads(auth_path.read_text(encoding="utf-8")).get("users", {})
        allowed = sorted({route for user in users.values() for route in user.get("routes", [])})
        print(f"gateway auth routes         {','.join(allowed) or 'missing'}")
    except Exception as exc:
        print(f"gateway auth routes         unreadable: {exc}")
else:
    print("gateway auth routes         auth file not found")
PY
}

load_owner_env
echo "== Faryo owner/gateway diagnostic =="
check_local_owner
check_capture
check_reverse_tunnel
check_gateway_config
