#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env

service_state() {
  local service="$1"
  local state
  state=$(systemctl --user is-active "$service" 2>/dev/null || true)
  printf '%s\n' "${state:-inactive}"
}

echo "== Faryo =="
echo "root: $FARYO_OWNER_ROOT"
echo "home: $FARYO_OWNER_DATA"
echo "inbox: $FARYO_OWNER_INBOX_DIR"
echo "artifacts: $FARYO_OWNER_ARTIFACTS_DIR"
echo "cache: $FARYO_OWNER_CACHE_DIR"
echo "logs: $FARYO_OWNER_LOGS_DIR"
echo "web:  $(web_url_public)"
echo

echo "== Web control plane =="
printf 'gcp tunnel: '
tunnel_state=$(service_state "$TUNNEL_SERVICE")
echo "$tunnel_state"
printf 'gcp tunnel remote health: '
if [[ "$tunnel_state" != "active" ]]; then
  echo "skipped ($tunnel_state)"
elif [[ "${GCP_TUNNEL_VERIFY_IN_STATUS:-0}" != "1" ]]; then
  echo "manual (run scripts/verify-gcp-reverse-tunnel.sh)"
elif "$SCRIPT_DIR/verify-gcp-reverse-tunnel.sh" >/dev/null 2>&1; then
  echo "ok"
else
  echo "failed"
fi
printf 'web keepalive timer: '; service_state "$KEEPALIVE_TIMER"
echo

echo "== tmux =="
tmux ls 2>/dev/null || echo "no tmux sessions"
if tmux has-session -t "$FARYO_OWNER_TMUX_SESSION" 2>/dev/null; then
  printf 'owner control pane: '
  tmux list-panes -t "$FARYO_OWNER_TMUX_SESSION" -F '#{pane_current_path} · #{pane_current_command}' 2>/dev/null | head -1 || true
fi
echo

echo "== Web owner =="
if ss -ltnp 2>/dev/null | grep -q ":$FARYO_OWNER_PORT"; then
  ss -ltnp 2>/dev/null | grep ":$FARYO_OWNER_PORT" || true
else
  echo "port $FARYO_OWNER_PORT: not listening"
fi
if curl_quiet "$(health_url)" >/dev/null; then
  echo "health: ok"
  tmp_status=$(mktemp)
  rm -f "$tmp_status"
else
  echo "health: failed"
fi
echo

echo "== Android ADB optional =="
if command -v adb >/dev/null 2>&1; then
  if ss -ltn 2>/dev/null | grep -q ':5037 '; then
    adb devices -l 2>/dev/null | sed -n '1,5p' || true
  else
    echo "adb server: stopped"
  fi
else
  echo "adb not found"
fi
