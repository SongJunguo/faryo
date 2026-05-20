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

GCP_HOST="$(required_env GCP_TUNNEL_HOST)"
GCP_USER="$(required_env GCP_TUNNEL_USER)"
REMOTE_PORT="$(required_env GCP_TUNNEL_REMOTE_PORT)"
REMOTE_PATH="${GCP_TUNNEL_STATUS_PATH:-/health}"
ATTEMPTS="${GCP_TUNNEL_VERIFY_ATTEMPTS:-12}"
SLEEP_SECONDS="${GCP_TUNNEL_VERIFY_SLEEP:-1}"
EXPECTED_OWNER_LABEL="${GCP_TUNNEL_EXPECTED_OWNER_LABEL:-}"
EXPECTED_SESSION="${GCP_TUNNEL_EXPECTED_SESSION:-}"

SSH_OPTS=(
  -o BatchMode=yes
  -o CheckHostIP=no
  -o HashKnownHosts=no
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout=5
)
if [[ -n "${GCP_TUNNEL_HOST_ALIAS:-}" ]]; then
  SSH_OPTS+=(-o HostKeyAlias="$GCP_TUNNEL_HOST_ALIAS")
fi
if [[ -n "${GCP_TUNNEL_KNOWN_HOSTS:-}" ]]; then
  SSH_OPTS+=(-o UserKnownHostsFile="$GCP_TUNNEL_KNOWN_HOSTS")
fi
if [[ -n "${GCP_TUNNEL_IDENTITY:-}" ]]; then
  SSH_OPTS+=(-i "$GCP_TUNNEL_IDENTITY" -o IdentitiesOnly=yes)
fi

remote_cmd="$(printf "curl -fsS --noproxy '*' --connect-timeout 2 --max-time 5 -H %q %q" \
  "X-Owner-Token: $FARYO_OWNER_TOKEN" \
  "http://127.0.0.1:${REMOTE_PORT}${REMOTE_PATH}")"
tmp_status="$(mktemp)"
trap 'rm -f "$tmp_status"' EXIT

for _ in $(seq 1 "$ATTEMPTS"); do
  if ssh "${SSH_OPTS[@]}" "${GCP_USER}@${GCP_HOST}" "$remote_cmd" > "$tmp_status" \
    && EXPECTED_OWNER_LABEL="$EXPECTED_OWNER_LABEL" EXPECTED_SESSION="$EXPECTED_SESSION" python3 - "$tmp_status" <<'PY'
import json
import os
import sys
with open(sys.argv[1], encoding="utf-8") as fh:
    payload = json.load(fh)
if payload.get("ok") is not True:
    raise SystemExit(1)
expected_owner_label = os.environ.get("EXPECTED_OWNER_LABEL") or ""
if expected_owner_label and payload.get("ownerLabel") != expected_owner_label:
    raise SystemExit(1)
expected_session = os.environ.get("EXPECTED_SESSION") or ""
if expected_session and payload.get("session") != expected_session:
    raise SystemExit(1)
PY
  then
    printf 'gcp reverse tunnel ok: 127.0.0.1:%s%s\n' "$REMOTE_PORT" "$REMOTE_PATH"
    exit 0
  fi
  sleep "$SLEEP_SECONDS"
done

printf 'gcp reverse tunnel failed: 127.0.0.1:%s%s ownerLabel=%s session=%s\n' \
  "$REMOTE_PORT" "$REMOTE_PATH" "$EXPECTED_OWNER_LABEL" "$EXPECTED_SESSION" >&2
exit 1
