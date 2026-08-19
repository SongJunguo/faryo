#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
python_bin="${FARYO_START_PYTHON:-python3}"
suffix="$$"
port="${FARYO_START_PORT:-$((26000 + (suffix % 1000)))}"
token="anonymous-start-$suffix"
launch_id="anonymous-launch-$suffix"
temp_root="$(mktemp -d -t faryo-start-runtime.XXXXXX)"
owner_pid=''
created_session=''

cleanup() {
  if [[ -n "$owner_pid" ]]; then
    kill "$owner_pid" 2>/dev/null || true
    wait "$owner_pid" 2>/dev/null || true
  fi
  if [[ -n "$created_session" ]]; then
    tmux kill-session -t "$created_session" 2>/dev/null || true
  fi
  if [[ "$temp_root" == /tmp/faryo-start-runtime.* && -d "$temp_root" ]]; then
    find "$temp_root" -type f -delete
    find "$temp_root" -type l -delete
    find "$temp_root" -depth -type d -empty -delete
  fi
}
trap cleanup EXIT INT TERM

ln -s /bin/sh "$temp_root/codex"
before_sizes="$(tmux list-panes -a -F '#{session_name} #{window_width}x#{window_height}' | awk '$1 ~ /^codex[0-9]*$/ {print}' | sort)"

env -u SHELL -u FARYO_AGENT_SHELL \
  PATH=/usr/bin:/bin \
  FARYO_CODEX_BIN="$temp_root/codex" \
  FARYO_START_DIRECTORY_ROOTS="$temp_root" \
  FARYO_OWNER_DATA="$temp_root/data" \
  FARYO_OWNER_PANE_WIDTH=0 \
  "$python_bin" "$repo_root/apps/owner/local-tmux-owner/server.py" \
    --host 127.0.0.1 --port "$port" --token "$token" --pane-width 0 \
    >"$temp_root/owner.log" 2>&1 &
owner_pid=$!

ready=0
for _ in $(seq 1 80); do
  if curl -fsS --max-time 1 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  kill -0 "$owner_pid" 2>/dev/null || break
  sleep 0.1
done
if [[ "$ready" != 1 ]]; then
  echo 'isolated Owner did not start' >&2
  sed -n '1,100p' "$temp_root/owner.log" >&2
  exit 1
fi

response="$temp_root/start-response.json"
curl -fsS --max-time 20 \
  -H "X-Owner-Token: $token" \
  -H 'Content-Type: application/json' \
  -d "{\"command\":\"codex\",\"cwd\":\"$temp_root\",\"max_running\":0,\"client_launch_id\":\"$launch_id\"}" \
  "http://127.0.0.1:$port/api/agent/new" >"$response"
created_session="$("$python_bin" - "$response" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
session = str(data.get("session") or "")
if not data.get("ok") or not (session.startswith("faryo") and session[5:].isdigit()):
    raise SystemExit(1)
print(session)
PY
)"

tmux has-session -t "$created_session"
[[ "$(tmux show-options -qv -t "$created_session" @faryo_managed)" == "1" ]]
[[ "$(tmux show-options -qv -t "$created_session" @faryo_agent_source)" == "codex-cli" ]]
[[ "$(tmux show-options -qv -t "$created_session" @faryo_launch_id)" == "$launch_id" ]]

retry_response="$temp_root/retry-response.json"
curl -fsS --max-time 20 \
  -H "X-Owner-Token: $token" \
  -H 'Content-Type: application/json' \
  -d "{\"command\":\"codex\",\"cwd\":\"$temp_root\",\"max_running\":0,\"client_launch_id\":\"$launch_id\"}" \
  "http://127.0.0.1:$port/api/agent/new" >"$retry_response"
retry_session="$("$python_bin" - "$retry_response" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
if not data.get("ok"):
    raise SystemExit(1)
print(str(data.get("session") or ""))
PY
)"
[[ "$retry_session" == "$created_session" ]]
[[ "$(tmux list-sessions -F '#{@faryo_launch_id}' | awk -v id="$launch_id" '$0 == id {count += 1} END {print count + 0}')" == 1 ]]

status="$temp_root/status.json"
curl -fsS --max-time 5 \
  -H "X-Owner-Token: $token" \
  "http://127.0.0.1:$port/api/status?session=$created_session" >"$status"
"$python_bin" - "$status" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
assert data.get("ok") is True
assert data.get("agentSource") == "codex-cli"
assert data.get("tmuxAlive") is True
PY

after_sizes="$(tmux list-panes -a -F '#{session_name} #{window_width}x#{window_height}' | awk '$1 ~ /^codex[0-9]*$/ {print}' | sort)"
[[ "$before_sizes" == "$after_sizes" ]]
tmux kill-session -t "$created_session"
! tmux has-session -t "$created_session" 2>/dev/null
created_session=''

echo 'faryo-start-codex-runtime=PASS shell=bash codex=ready managed=yes idempotent-retry=yes existing-tmux-size=unchanged'
