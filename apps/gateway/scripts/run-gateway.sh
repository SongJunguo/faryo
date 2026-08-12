#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env

FARYO_HOME="${FARYO_HOME:-$HOME/.faryo}"
GATEWAY_HOST="${GATEWAY_HOST:-127.0.0.1}"
GATEWAY_PORT="${GATEWAY_PORT:-8780}"
GATEWAY_AUTH_CONFIG="${GATEWAY_AUTH_CONFIG:-$FARYO_HOME/gateway/config/gateway-auth.json}"
GATEWAY_SECRET_FILE="${GATEWAY_SECRET_FILE:-$FARYO_HOME/gateway/state/gateway-cookie-secret}"
PORTAL_DIR="${PORTAL_DIR:-$FARYO_HOME/gateway/portal}"
FARYO_PYTHON="${FARYO_PYTHON:-python3}"

exec "$FARYO_PYTHON" "$FARYO_GATEWAY_ROOT/server/server.py" \
  --host "$GATEWAY_HOST" \
  --port "$GATEWAY_PORT" \
  --auth-config "$GATEWAY_AUTH_CONFIG" \
  --owner-env "$ENV_FILE" \
  --portal-dir "$PORTAL_DIR" \
  --secret-file "$GATEWAY_SECRET_FILE"
