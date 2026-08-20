#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  apps/owner/scripts/init-owner-env.sh

Creates or updates ~/.faryo/owner/config/faryo.env with the maintained Codex
Owner runtime settings. Existing tokens are preserved. Retired project-workbench
keys are removed; their allowed roots migrate to FARYO_START_DIRECTORY_ROOTS
when no explicit directory roots exist.
USAGE
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
# shellcheck source=../../../scripts/runtime-env.sh
source "$REPO_ROOT/scripts/runtime-env.sh"
FARYO_HOME="${FARYO_HOME:-$HOME/.faryo}"
ENV_FILE="${FARYO_OWNER_ENV:-${FARYO_ENV_FILE:-$FARYO_HOME/owner/config/faryo.env}}"

mkdir -p "$(dirname "$ENV_FILE")" "$FARYO_HOME/owner/data/inbox" "$FARYO_HOME/owner/data/artifacts" "$FARYO_HOME/owner/data/cache" "$FARYO_HOME/owner/data/logs"

export FARYO_HOME ENV_FILE
export FARYO_OWNER_HOST="${FARYO_OWNER_HOST:-127.0.0.1}"
export FARYO_OWNER_PORT="${FARYO_OWNER_PORT:-8765}"
export FARYO_OWNER_LABEL="${FARYO_OWNER_LABEL:-}"
export FARYO_OWNER_DIRECT_SESSION="${FARYO_OWNER_DIRECT_SESSION:-__faryo_no_default__}"
export FARYO_OWNER_TMUX_SESSION="${FARYO_OWNER_TMUX_SESSION:-local-tmux-owner}"
export FARYO_PYTHON="$(faryo_resolve_python)"
export FARYO_CODEX_BIN="${FARYO_CODEX_BIN:-}"
export FARYO_AGENT_SHELL="${FARYO_AGENT_SHELL:-}"
export FARYO_START_DIRECTORY_ROOTS="${FARYO_START_DIRECTORY_ROOTS:-}"

"$FARYO_PYTHON" - <<'PY'
import os
import re
import secrets
import shlex
from pathlib import Path

KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
ORDER = [
    "FARYO_OWNER_HOST",
    "FARYO_OWNER_PORT",
    "FARYO_OWNER_TOKEN",
    "FARYO_OWNER_DIRECT_SESSION",
    "FARYO_OWNER_TMUX_SESSION",
    "FARYO_PYTHON",
    "FARYO_CODEX_BIN",
    "FARYO_AGENT_SHELL",
    "FARYO_START_DIRECTORY_ROOTS",
    "FARYO_OWNER_LABEL",
    "FARYO_OWNER_DATA",
    "FARYO_OWNER_INBOX_DIR",
    "FARYO_OWNER_ARTIFACTS_DIR",
    "FARYO_OWNER_CACHE_DIR",
    "FARYO_OWNER_LOGS_DIR",
    "TMUX_HISTORY_LIMIT",
    "WEB_CAPTURE_LINES",
]
RETIRED_KEYS = {
    "FARYO_PROJECT_WORKBENCH_ENABLE",
    "FARYO_PROJECT_WORKBENCH_GATEWAY_URL",
    "FARYO_PROJECT_WORKBENCH_SYNC_URL",
    "FARYO_PROJECT_WORKBENCH_SYNC_OWNER_LABEL",
    "FARYO_PROJECT_WORKBENCH_ROOTS",
    "FARYO_PROJECT_WORKBENCH_PROJECTS_ROOT",
    "FARYO_PROJECT_WORKBENCH_ALLOWED_ROOTS",
}

def parse_value(raw):
    try:
        parsed = shlex.split(raw, posix=True)
    except ValueError:
        return raw.strip().strip("'\"")
    return parsed[0] if parsed else ""

def render(key, value):
    return f"{key}={shlex.quote(str(value))}"

env_file = Path(os.environ["ENV_FILE"]).expanduser()
existing = {}
raw_values = {}
lines = []
if env_file.exists():
    lines = env_file.read_text(encoding="utf-8").splitlines()
    for line in lines:
        match = KEY_RE.match(line.strip())
        if match:
            raw_values[match.group(1)] = match.group(2)
            existing[match.group(1)] = parse_value(match.group(2))

faryo_home = os.environ["FARYO_HOME"]
rotate_token = os.environ.get("FARYO_OWNER_TOKEN_ROTATE") == "1"
owner_data = existing.get("FARYO_OWNER_DATA") or f"{faryo_home}/owner/data"
label = (
    os.environ.get("FARYO_OWNER_LABEL")
    or existing.get("FARYO_OWNER_LABEL")
    or "LOCAL"
)
if not existing.get("FARYO_OWNER_LABEL"):
    existing["FARYO_OWNER_LABEL"] = label
values = {
    "FARYO_OWNER_HOST": existing.get("FARYO_OWNER_HOST") or os.environ["FARYO_OWNER_HOST"],
    "FARYO_OWNER_PORT": existing.get("FARYO_OWNER_PORT") or os.environ["FARYO_OWNER_PORT"],
    "FARYO_OWNER_TOKEN": secrets.token_urlsafe(32) if rotate_token else (existing.get("FARYO_OWNER_TOKEN") or secrets.token_urlsafe(32)),
    "FARYO_OWNER_DIRECT_SESSION": existing.get("FARYO_OWNER_DIRECT_SESSION") or os.environ["FARYO_OWNER_DIRECT_SESSION"],
    "FARYO_OWNER_TMUX_SESSION": existing.get("FARYO_OWNER_TMUX_SESSION") or os.environ["FARYO_OWNER_TMUX_SESSION"],
    "FARYO_PYTHON": existing.get("FARYO_PYTHON") or os.environ["FARYO_PYTHON"],
    "FARYO_CODEX_BIN": existing.get("FARYO_CODEX_BIN") or os.environ["FARYO_CODEX_BIN"],
    "FARYO_AGENT_SHELL": existing.get("FARYO_AGENT_SHELL") or os.environ["FARYO_AGENT_SHELL"],
    "FARYO_START_DIRECTORY_ROOTS": existing.get("FARYO_START_DIRECTORY_ROOTS") or os.environ["FARYO_START_DIRECTORY_ROOTS"] or existing.get("FARYO_PROJECT_WORKBENCH_ALLOWED_ROOTS", ""),
    "FARYO_OWNER_LABEL": existing["FARYO_OWNER_LABEL"],
    "FARYO_OWNER_DATA": owner_data,
    "FARYO_OWNER_INBOX_DIR": existing.get("FARYO_OWNER_INBOX_DIR") or f"{owner_data}/inbox",
    "FARYO_OWNER_ARTIFACTS_DIR": existing.get("FARYO_OWNER_ARTIFACTS_DIR") or f"{owner_data}/artifacts",
    "FARYO_OWNER_CACHE_DIR": existing.get("FARYO_OWNER_CACHE_DIR") or f"{owner_data}/cache",
    "FARYO_OWNER_LOGS_DIR": existing.get("FARYO_OWNER_LOGS_DIR") or f"{owner_data}/logs",
    "TMUX_HISTORY_LIMIT": existing.get("TMUX_HISTORY_LIMIT") or "500",
    "WEB_CAPTURE_LINES": existing.get("WEB_CAPTURE_LINES") or "800",
}
force_keys = set()
if not parse_value(raw_values.get("FARYO_OWNER_LABEL", "")):
    force_keys.add("FARYO_OWNER_LABEL")
if rotate_token:
    force_keys.add("FARYO_OWNER_TOKEN")
seen = set()
updated = []
for line in lines:
    match = KEY_RE.match(line.strip())
    if match and match.group(1) in RETIRED_KEYS:
        continue
    if match and match.group(1) in values:
        key = match.group(1)
        updated.append(render(key, values[key]) if key in force_keys else line)
        seen.add(key)
    else:
        updated.append(line)
if updated and updated[-1].strip():
    updated.append("")
for key in ORDER:
    if key not in seen:
        updated.append(render(key, values[key]))
body = "\n".join(updated).rstrip() + "\n"
tmp = env_file.with_suffix(env_file.suffix + ".tmp")
tmp.write_text(body, encoding="utf-8")
tmp.chmod(0o600)
tmp.replace(env_file)
PY

echo "initialized $ENV_FILE"
