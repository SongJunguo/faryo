#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env
mkdir -p "$FARYO_HOME/owner/state"

apply_tmux_server_env

tmux kill-session -t "$FARYO_OWNER_TMUX_SESSION" 2>/dev/null || true
tmux new-session -d -s "$FARYO_OWNER_TMUX_SESSION" "$FARYO_OWNER_ROOT/scripts/run-web-owner.sh"
apply_tmux_session_env "$FARYO_OWNER_TMUX_SESSION"

for _ in $(seq 1 50); do
  if curl_quiet "$(health_url)" >/dev/null 2>&1; then
    echo "started: $(web_url_public)"
    exit 0
  fi
  sleep 0.1
done

echo "failed to start web owner" >&2
tmux capture-pane -pt "$FARYO_OWNER_TMUX_SESSION" -S -80 2>/dev/null || true
exit 1
