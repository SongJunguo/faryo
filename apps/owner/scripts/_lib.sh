#!/usr/bin/env bash
set -euo pipefail

FARYO_OWNER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FARYO_HOME="${FARYO_HOME:-$HOME/.faryo}"
ENV_FILE="${FARYO_OWNER_ENV:-${FARYO_ENV_FILE:-$FARYO_HOME/owner/config/faryo.env}}"

load_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "missing env file: $ENV_FILE" >&2
    echo "run scripts/init-owner-env.sh with FARYO_PROJECT_WORKBENCH_GATEWAY_URL" >&2
    exit 2
  fi
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  : "${FARYO_OWNER_HOST:?missing FARYO_OWNER_HOST}"
  : "${FARYO_OWNER_PORT:?missing FARYO_OWNER_PORT}"
  : "${FARYO_OWNER_TOKEN:?missing FARYO_OWNER_TOKEN}"
  : "${FARYO_OWNER_DIRECT_SESSION:=__faryo_no_default__}"
  : "${FARYO_OWNER_TMUX_SESSION:=local-tmux-owner}"
  : "${FARYO_PYTHON:=python3}"
  : "${FARYO_AGENT_SHELL:=}"
  : "${FARYO_START_DIRECTORY_ROOTS:=}"
  : "${FARYO_OWNER_LABEL:=}"
  : "${FARYO_OWNER_DATA:=$FARYO_HOME/owner/data}"
  : "${FARYO_OWNER_INBOX_DIR:=$FARYO_OWNER_DATA/inbox}"
  : "${FARYO_OWNER_ARTIFACTS_DIR:=$FARYO_OWNER_DATA/artifacts}"
  : "${FARYO_OWNER_CACHE_DIR:=$FARYO_OWNER_DATA/cache}"
  : "${FARYO_OWNER_LOGS_DIR:=$FARYO_OWNER_DATA/logs}"
  : "${FARYO_OWNER_FILE_INBOX:=$FARYO_OWNER_INBOX_DIR}"
  : "${TUNNEL_SERVICE:=faryo-gateway-tunnel.service}"
  : "${KEEPALIVE_TIMER:=faryo-owner-keepalive.timer}"
  : "${TMUX_HISTORY_LIMIT:=500}"
  : "${WEB_CAPTURE_LINES:=800}"
  mkdir -p "$FARYO_OWNER_INBOX_DIR" "$FARYO_OWNER_ARTIFACTS_DIR" "$FARYO_OWNER_CACHE_DIR" "$FARYO_OWNER_LOGS_DIR"
  normalize_runtime_env
}

append_no_proxy() {
  local entry="$1"
  case ",${NO_PROXY:-}," in
    *,"$entry",*) ;;
    *) NO_PROXY="${NO_PROXY:+$NO_PROXY,}$entry" ;;
  esac
}

normalize_runtime_env() {
  unset NO_COLOR CODEX_THREAD_ID CODEX_CI CODEX_SANDBOX_NETWORK_DISABLED
  export LANG=C.UTF-8 LC_ALL=C.UTF-8 LC_CTYPE=C.UTF-8 COLORTERM=truecolor
  if [[ -z "${TERM:-}" || "${TERM:-}" == "dumb" ]]; then
    export TERM=xterm-256color
  fi
  for entry in localhost 127.0.0.1 ::1 "*.local" 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
    append_no_proxy "$entry"
  done
  export NO_PROXY no_proxy="$NO_PROXY"
}

apply_tmux_runtime_env() {
  local scope=("$@")
  for var in NO_COLOR CODEX_THREAD_ID CODEX_CI CODEX_SANDBOX_NETWORK_DISABLED; do
    tmux set-environment "${scope[@]}" -u "$var" 2>/dev/null || true
  done
  tmux set-environment "${scope[@]}" LANG C.UTF-8 2>/dev/null || true
  tmux set-environment "${scope[@]}" LC_ALL C.UTF-8 2>/dev/null || true
  tmux set-environment "${scope[@]}" LC_CTYPE C.UTF-8 2>/dev/null || true
  tmux set-environment "${scope[@]}" COLORTERM truecolor 2>/dev/null || true
  tmux set-environment "${scope[@]}" NO_PROXY "$NO_PROXY" 2>/dev/null || true
  tmux set-environment "${scope[@]}" no_proxy "$NO_PROXY" 2>/dev/null || true
}

apply_tmux_server_env() {
  tmux has-session 2>/dev/null || return 0
  apply_tmux_runtime_env -g
}

apply_tmux_session_env() {
  local session="$1"
  tmux has-session -t "$session" 2>/dev/null || return 0
  apply_tmux_runtime_env -t "$session"
}

web_url_public() {
  printf 'http://%s:%s/?token=<private-token>\n' "$FARYO_OWNER_HOST" "$FARYO_OWNER_PORT"
}

health_url() {
  printf 'http://%s:%s/health\n' "$FARYO_OWNER_HOST" "$FARYO_OWNER_PORT"
}

api_url() {
  printf 'http://%s:%s/api/%s\n' "$FARYO_OWNER_HOST" "$FARYO_OWNER_PORT" "$1"
}

curl_quiet() {
  curl --noproxy '*' -fsS --max-time 12 "$@"
}
