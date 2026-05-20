#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env
if tmux kill-session -t "$FARYO_OWNER_TMUX_SESSION" 2>/dev/null; then
  echo "stopped: $FARYO_OWNER_TMUX_SESSION"
else
  echo "not running: $FARYO_OWNER_TMUX_SESSION"
fi
