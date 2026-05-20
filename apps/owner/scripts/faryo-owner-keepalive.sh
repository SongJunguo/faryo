#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

apply_tmux_server_env

if curl_quiet "$(health_url)" >/dev/null 2>&1; then
  log "web owner healthy"
  exit 0
fi

log "web owner unhealthy; restarting"
"$SCRIPT_DIR/start-web-owner.sh"
