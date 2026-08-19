#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
browser_smoke="$repo_root/apps/owner/local-tmux-owner/tests/browser-katex-smoke.mjs"
python_bin="${FARYO_HISTORY_PYTHON:-python3}"
suffix="$$"
session="faryo-full-history-$suffix"
port="${FARYO_HISTORY_PORT:-$((25000 + (suffix % 1000)))}"
token="anonymous-history-$suffix"
temp_root="$(mktemp -d -t faryo-full-history.XXXXXX)"
owner_pid=''

cleanup() {
  if [[ -n "$owner_pid" ]]; then
    kill "$owner_pid" 2>/dev/null || true
    wait "$owner_pid" 2>/dev/null || true
  fi
  tmux kill-session -t "$session" 2>/dev/null || true
  if [[ "$temp_root" == /tmp/faryo-full-history.* && -d "$temp_root" ]]; then
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
thread_id = "11111111-2222-4333-8444-555555555555"
rollout = root / f"rollout-2026-01-01T00-00-00-{thread_id}.jsonl"
events = []
for index in range(40):
    events.extend((
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": f"Anonymous question {index + 1}"}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": f"## Anonymous result {index + 1}\n\n\\[x_{{{index + 1}}}=u+{index + 1}\\]\n\nThe complete turn remains paged.",
                }],
            },
        },
        {"type": "response_item", "payload": {"type": "function_call", "name": "ignored_fixture_tool"}},
    ))
rollout.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

state_db = root / "state.sqlite"
connection = sqlite3.connect(state_db)
connection.execute("""
CREATE TABLE threads (
  id TEXT PRIMARY KEY,
  title TEXT,
  rollout_path TEXT,
  tokens_used INTEGER,
  model TEXT,
  reasoning_effort TEXT,
  cwd TEXT,
  updated_at TEXT,
  source TEXT,
  thread_source TEXT,
  archived INTEGER DEFAULT 0
)
""")
connection.execute(
    "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (thread_id, "Anonymous history fixture", str(rollout), 0, "fixture", "", str(repo), "2026-01-01T00:00:00+00:00", "cli", "user", 0),
)
connection.commit()
connection.close()

launcher = root / "codex-fixture"
launcher.write_text(
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    "rollout=\"$1\"\n"
    "exec 3<\"$rollout\"\n"
    "bash -c 'exec -a \"$1\" sleep 120' _ \"$0-worker\" &\n"
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
      | "$python_bin" -c 'import json,sys; data=json.load(sys.stdin); raise SystemExit(0 if data.get("captureSource")=="codex-jsonl" else 1)' 2>/dev/null; then
    ready=1
    break
  fi
  kill -0 "$owner_pid" 2>/dev/null || break
  sleep 0.1
done
if [[ "$ready" != 1 ]]; then
  echo 'full-history Owner fixture did not become structured' >&2
  sed -n '1,100p' "$temp_root/owner.log" >&2
  exit 1
fi

env \
  "FARYO_SMOKE_URL=http://127.0.0.1:$port/?token=$token&session=$session" \
  'FARYO_SMOKE_PRIVACY_SAFE=1' \
  'FARYO_SMOKE_EXPECT_STRUCTURED=1' \
  'FARYO_SMOKE_CHECK_OWNER_LAYOUT=1' \
  'FARYO_SMOKE_CHECK_MODE_SWITCH=1' \
  'FARYO_SMOKE_MIN_QUESTION_MARKERS=40' \
  'FARYO_SMOKE_EXPECT_HISTORY_TURNS=40' \
  "FARYO_SMOKE_VIEWPORT_WIDTH=${FARYO_HISTORY_VIEWPORT_WIDTH:-390}" \
  "FARYO_SMOKE_VIEWPORT_HEIGHT=${FARYO_HISTORY_VIEWPORT_HEIGHT:-844}" \
  node "$browser_smoke"

final_size="$(tmux display-message -p -t "$session" '#{window_width}x#{window_height}')"
[[ "$initial_size" == "$final_size" ]]
echo 'faryo-browser-full-history-matrix=PASS total=40 lazy-pages=PASS tmux-size=unchanged'
