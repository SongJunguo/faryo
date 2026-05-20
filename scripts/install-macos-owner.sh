#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS installer must be run on macOS" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FARYO_HOME="${FARYO_HOME:-$HOME/.faryo}"
FARYO_INSTALL_ROOT="${FARYO_INSTALL_ROOT:-$FARYO_HOME/runtime}"
FARYO_RUNTIME_ROOT="${FARYO_RUNTIME_ROOT:-$FARYO_INSTALL_ROOT/faryo}"
ENV_FILE="${FARYO_OWNER_ENV:-$FARYO_HOME/owner/config/faryo.env}"
PLIST_LABEL="dev.faryo.owner.keepalive"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$PLIST_LABEL.plist"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing dependency: $1" >&2
    echo "install dependencies with: brew install tmux python3" >&2
    exit 2
  fi
}

require_cmd python3
require_cmd tmux
require_cmd curl
require_cmd rsync

mkdir -p "$FARYO_RUNTIME_ROOT/apps/owner" "$FARYO_HOME/owner/config" "$FARYO_HOME/owner/data/inbox" "$FARYO_HOME/owner/data/artifacts" "$FARYO_HOME/owner/data/cache" "$FARYO_HOME/owner/data/logs" "$PLIST_DIR"

rsync -a --delete \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache/' \
  --exclude='config/faryo.env' \
  "$ROOT/apps/owner/" "$FARYO_RUNTIME_ROOT/apps/owner/"

if [[ ! -f "$ENV_FILE" ]]; then
  token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  cat > "$ENV_FILE" <<EOF
FARYO_OWNER_HOST=127.0.0.1
FARYO_OWNER_PORT=8765
FARYO_OWNER_TOKEN=$token
FARYO_OWNER_DIRECT_SESSION=__faryo_no_default__
FARYO_OWNER_TMUX_SESSION=local-tmux-owner
FARYO_OWNER_LABEL=MAC
FARYO_OWNER_DATA=$FARYO_HOME/owner/data
FARYO_OWNER_INBOX_DIR=$FARYO_HOME/owner/data/inbox
FARYO_OWNER_ARTIFACTS_DIR=$FARYO_HOME/owner/data/artifacts
FARYO_OWNER_CACHE_DIR=$FARYO_HOME/owner/data/cache
FARYO_OWNER_LOGS_DIR=$FARYO_HOME/owner/data/logs
TMUX_HISTORY_LIMIT=500
WEB_CAPTURE_LINES=800
EOF
  chmod 0600 "$ENV_FILE"
else
  echo "keep existing $ENV_FILE"
fi

python3 - "$ROOT/deploy/launchd/$PLIST_LABEL.plist" "$PLIST_PATH" "$FARYO_RUNTIME_ROOT" "$FARYO_HOME" <<'PY'
from pathlib import Path
import sys
template, dest, runtime_root, faryo_home = map(Path, sys.argv[1:])
text = template.read_text(encoding="utf-8")
text = text.replace("@FARYO_ROOT@", runtime_root.as_posix()).replace("@FARYO_HOME@", faryo_home.as_posix())
dest.write_text(text, encoding="utf-8")
PY

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"
launchctl start "$PLIST_LABEL" >/dev/null 2>&1 || true

echo "installed Faryo Owner at $FARYO_RUNTIME_ROOT"
echo "launchd plist: $PLIST_PATH"
echo "owner env: $ENV_FILE"
echo "open http://127.0.0.1:8765/?token=<owner-token>"
