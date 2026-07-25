#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env

required_env() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "$value" || "$value" == replace-* || "$value" == "<"*">" ]]; then
    printf 'missing %s in config/faryo.env\n' "$name" >&2
    exit 2
  fi
  printf '%s\n' "$value"
}

TUNNEL_HOST="$(required_env GATEWAY_TUNNEL_HOST)"
TUNNEL_USER="$(required_env GATEWAY_TUNNEL_USER)"
REMOTE_PORT="$(required_env GATEWAY_TUNNEL_REMOTE_PORT)"
REMOTE_PATH="${GATEWAY_TUNNEL_STATUS_PATH:-/health}"
ATTEMPTS="${GATEWAY_TUNNEL_VERIFY_ATTEMPTS:-12}"
SLEEP_SECONDS="${GATEWAY_TUNNEL_VERIFY_SLEEP:-1}"

SSH_OPTS=(
  -o BatchMode=yes
  -o CheckHostIP=no
  -o HashKnownHosts=no
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout=5
)
if [[ -n "${GATEWAY_TUNNEL_HOST_ALIAS:-}" ]]; then
  SSH_OPTS+=(-o HostKeyAlias="$GATEWAY_TUNNEL_HOST_ALIAS")
fi
if [[ -n "${GATEWAY_TUNNEL_KNOWN_HOSTS:-}" ]]; then
  SSH_OPTS+=(-o UserKnownHostsFile="$GATEWAY_TUNNEL_KNOWN_HOSTS")
fi
if [[ -n "${GATEWAY_TUNNEL_IDENTITY:-}" ]]; then
  SSH_OPTS+=(-i "$GATEWAY_TUNNEL_IDENTITY" -o IdentitiesOnly=yes)
fi

remote_cmd="$(printf "curl -fsS --noproxy '*' --connect-timeout 2 --max-time 5 -H %q %q" \
  "X-Owner-Token: $FARYO_OWNER_TOKEN" \
  "http://127.0.0.1:${REMOTE_PORT}${REMOTE_PATH}")"

for _ in $(seq 1 "$ATTEMPTS"); do
  if ssh "${SSH_OPTS[@]}" "${TUNNEL_USER}@${TUNNEL_HOST}" "$remote_cmd" \
    | python3 -c 'import json, sys; raise SystemExit(0 if json.load(sys.stdin).get("ok") is True else 1)'
  then
    printf 'reverse tunnel ok: 127.0.0.1:%s%s\n' "$REMOTE_PORT" "$REMOTE_PATH"
    exit 0
  fi
  sleep "$SLEEP_SECONDS"
done

printf 'reverse tunnel failed: 127.0.0.1:%s%s\n' "$REMOTE_PORT" "$REMOTE_PATH" >&2
exit 1
