#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
browser_smoke="$repo_root/apps/owner/local-tmux-owner/tests/browser-katex-smoke.mjs"
python_bin="${FARYO_LIVE_PYTHON:-python3}"
node_bin="${FARYO_LIVE_NODE:-node}"
suffix="$$"
session="faryo-live-selection-$suffix"
port="${FARYO_LIVE_PORT:-$((27000 + (suffix % 1000)))}"
token="anonymous-live-$suffix"
temp_root="$(mktemp -d -t faryo-live-selection.XXXXXX)"
owner_pid=''

cleanup() {
  if [[ -n "$owner_pid" ]]; then
    kill "$owner_pid" 2>/dev/null || true
    wait "$owner_pid" 2>/dev/null || true
  fi
  tmux kill-session -t "$session" 2>/dev/null || true
  if [[ "$temp_root" == /tmp/faryo-live-selection.* && -d "$temp_root" ]]; then
    find "$temp_root" -type f -delete
    find "$temp_root" -depth -type d -empty -delete
  fi
}
trap cleanup EXIT INT TERM

readarray -t fixture_paths < <("$python_bin" - "$temp_root" "$repo_root" <<'PY'
from pathlib import Path
import json
import sqlite3
import sys

root = Path(sys.argv[1])
repo = Path(sys.argv[2])
thread_id = "22222222-3333-4444-8555-666666666666"
rollout = root / f"rollout-2026-01-01T00-00-00-{thread_id}.jsonl"
events = [
    {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Anonymous live selection question"}]}},
    {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "## Anonymous stable result\n\nThe finalized answer remains separate from live terminal evidence."}]}},
]
rollout.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

state_db = root / "state.sqlite"
connection = sqlite3.connect(state_db)
connection.execute("""
CREATE TABLE threads (
  id TEXT PRIMARY KEY, title TEXT, rollout_path TEXT, tokens_used INTEGER,
  model TEXT, reasoning_effort TEXT, cwd TEXT, updated_at TEXT,
  source TEXT, thread_source TEXT, archived INTEGER DEFAULT 0
)
""")
connection.execute(
    "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (thread_id, "Anonymous live fixture", str(rollout), 0, "fixture", "", str(repo), "2026-01-01T00:00:00+00:00", "cli", "user", 0),
)
connection.commit()
connection.close()

launcher = root / "codex-live-fixture"
launcher.write_text(
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    "rollout=\"$1\"\n"
    "exec 3<\"$rollout\"\n"
    "(\n"
    "printf '› Anonymous live selection question\\n'\n"
    "index=0\n"
    "while true; do\n"
    "  index=$((index + 1))\n"
    "  printf '• Explored anonymous context %03d\\n' \"$index\"\n"
    "  printf '  └ Search anonymous-pattern in fixture.py\\n'\n"
    "  printf '• Edited anonymous/fixture.py (+1 -0)\\n'\n"
    "  printf '  %03d +anonymous line %03d\\n' \"$index\" \"$index\"\n"
    "  printf '• Working (%ds • esc to interrupt)\\n' \"$index\"\n"
    "  sleep 0.15\n"
    "done\n"
    ") &\n"
    "wait\n",
    encoding="utf-8",
)
launcher.chmod(0o755)
print(rollout)
print(state_db)
print(launcher)
PY
)
rollout="${fixture_paths[0]}"
state_db="${fixture_paths[1]}"
launcher="${fixture_paths[2]}"

tmux new-session -d -x 200 -y 40 -s "$session" -c "$repo_root" "exec '$launcher' '$rollout'"
initial_size="$(tmux display-message -p -t "$session" '#{window_width}x#{window_height}')"

FARYO_CODEX_STATE_DB="$state_db" \
FARYO_CODEX_SESSION_INDEX="$temp_root/session-index.jsonl" \
FARYO_OWNER_DATA="$temp_root/data" \
FARYO_OWNER_PANE_WIDTH=0 \
  "$python_bin" "$repo_root/apps/owner/local-tmux-owner/server.py" \
    --host 127.0.0.1 --port "$port" --session "$session" --token "$token" --pane-width 0 \
    >"$temp_root/owner.log" 2>&1 &
owner_pid=$!

ready=0
for _ in $(seq 1 100); do
  if curl -fsS --max-time 1 "http://127.0.0.1:$port/api/capture?token=$token&session=$session&lines=320" 2>/dev/null \
      | "$python_bin" -c 'import json,sys; data=json.load(sys.stdin); raise SystemExit(0 if data.get("captureSource")=="codex-jsonl" and data.get("liveText") else 1)' 2>/dev/null; then
    ready=1
    break
  fi
  kill -0 "$owner_pid" 2>/dev/null || break
  sleep 0.1
done
if [[ "$ready" != 1 ]]; then
  echo 'live selection Owner fixture did not become ready' >&2
  curl -fsS --max-time 1 "http://127.0.0.1:$port/api/capture?token=$token&session=$session&lines=320" 2>/dev/null \
    | "$python_bin" -c 'import json,sys; data=json.load(sys.stdin); print({key:data.get(key) for key in ("captureSource","agentRunning","agentProfile","agentSource")}|{"hasLive":bool(data.get("liveText"))})' >&2 || true
  tmux display-message -p -t "$session" 'pane=#{pane_pid} command=#{pane_current_command}' >&2 || true
  ps -eo pid=,ppid=,args= | rg "codex-live-fixture|$session" | sed -n '1,12p' >&2 || true
  sed -n '1,100p' "$temp_root/owner.log" >&2
  exit 1
fi

for viewport in 390x844 1440x900; do
  width="${viewport%x*}"
  height="${viewport#*x}"
  env \
    "FARYO_SMOKE_URL=http://127.0.0.1:$port/?token=$token&session=$session" \
    'FARYO_SMOKE_PRIVACY_SAFE=1' \
    'FARYO_SMOKE_SKIP_RENDER_CHECKS=1' \
    'FARYO_SMOKE_CHECK_OWNER_LAYOUT=1' \
    'FARYO_SMOKE_CHECK_LIVE_SCROLL=1' \
    "FARYO_SMOKE_VIEWPORT_WIDTH=$width" \
    "FARYO_SMOKE_VIEWPORT_HEIGHT=$height" \
    "$node_bin" "$browser_smoke"
done

final_size="$(tmux display-message -p -t "$session" '#{window_width}x#{window_height}')"
if [[ "$initial_size" != "$final_size" ]]; then
  echo 'Live selection browser test changed tmux dimensions' >&2
  exit 1
fi

echo 'faryo-browser-live-selection-matrix=PASS viewports=390x844,1440x900 tail=180 dom=stable selection=paused copy=ready tmux-size=unchanged'
