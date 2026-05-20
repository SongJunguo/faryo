#!/usr/bin/env bash
set -euo pipefail

gateway_url="${FARYO_GATEWAY_HEALTH_URL:-http://127.0.0.1:8780/login}"
owner_url="${FARYO_OWNER_HEALTH_URL:-http://127.0.0.1:8765/health}"

check_url() {
  local label="$1"
  local url="$2"
  if curl --noproxy '*' -fsS -o /dev/null --max-time 8 "$url"; then
    printf '%s OK %s\n' "$label" "$url"
  else
    printf '%s FAIL %s\n' "$label" "$url" >&2
    return 1
  fi
}

check_url "gateway" "$gateway_url"
check_url "owner" "$owner_url"

printf 'processes:\n'
pgrep -af 'faryo|local-tmux-owner|gcp-gateway|python3 server.py' || true

if command -v tmux >/dev/null 2>&1; then
  owner_cwd="$(tmux display-message -p -t local-tmux-owner '#{pane_current_path}' 2>/dev/null || true)"
  if [[ -n "$owner_cwd" ]]; then
    printf 'owner tmux cwd: %s\n' "$owner_cwd"
  fi
fi
