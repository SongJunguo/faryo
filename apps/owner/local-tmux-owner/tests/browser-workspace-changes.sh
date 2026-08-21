#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
# shellcheck source=../../../../scripts/runtime-env.sh
source "$repo_root/scripts/runtime-env.sh"
python_bin="${FARYO_CHANGES_PYTHON:-$(faryo_resolve_python)}"
node_bin="${FARYO_CHANGES_NODE:-$(faryo_resolve_node)}"
suffix="$$"
session="faryo-workspace-changes-$suffix"
port="${FARYO_CHANGES_PORT:-$((28000 + (suffix % 1000)))}"
token="anonymous-workspace-changes-$suffix"
temp_root="$(mktemp -d -t faryo-workspace-changes.XXXXXX)"
fixture="$temp_root/repository"
owner_pid=''

cleanup() {
  if [[ -n "$owner_pid" ]]; then
    kill "$owner_pid" 2>/dev/null || true
    wait "$owner_pid" 2>/dev/null || true
  fi
  tmux kill-session -t "$session" 2>/dev/null || true
  if [[ "$temp_root" == /tmp/faryo-workspace-changes.* && -d "$temp_root" ]]; then
    find "$temp_root" -type f -delete
    find "$temp_root" -depth -type l -delete
    find "$temp_root" -depth -type d -empty -delete
  fi
}
trap cleanup EXIT INT TERM

mkdir -p "$fixture"
git -C "$fixture" init -q
git -C "$fixture" config user.name 'Anonymous Test'
git -C "$fixture" config user.email 'anonymous.invalid'
printf 'before\n' >"$fixture/tracked.txt"
git -C "$fixture" add tracked.txt
git -C "$fixture" commit -qm fixture
printf 'after\n' >"$fixture/tracked.txt"
printf 'staged\n' >"$fixture/staged.txt"
git -C "$fixture" add staged.txt
printf 'untracked\n' >"$fixture/untracked.txt"

tmux new-session -d -x 200 -y 40 -s "$session" -c "$fixture" 'exec sleep 120'
initial_size="$(tmux display-message -p -t "$session" '#{window_width}x#{window_height}')"

FARYO_OWNER_DATA="$temp_root/data" PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$python_bin" "$repo_root/apps/owner/local-tmux-owner/run_owner_asgi.py" \
  --host 127.0.0.1 --port "$port" --session "$session" --token "$token" --pane-width 0 \
  >/dev/null 2>&1 &
owner_pid=$!
for _attempt in $(seq 1 100); do
  curl --noproxy '*' -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1 && break
  sleep 0.05
done
curl --noproxy '*' -fsS "http://127.0.0.1:$port/health" >/dev/null

for spec in '390 844 /usr/bin/google-chrome' '1440 900 /usr/bin/microsoft-edge-stable'; do
  set -- $spec
  FARYO_CHANGES_URL="http://127.0.0.1:$port/?token=$token&session=$session" \
  FARYO_CHANGES_WIDTH="$1" FARYO_CHANGES_HEIGHT="$2" FARYO_CHANGES_EXPECT_FILES=3 \
  CHROME_BIN="$3" "$node_bin" "$repo_root/apps/owner/local-tmux-owner/tests/browser-workspace-changes-smoke.mjs"
done

final_size="$(tmux display-message -p -t "$session" '#{window_width}x#{window_height}')"
[[ "$initial_size" == "$final_size" ]]
echo 'faryo-browser-workspace-changes-matrix=PASS viewports=390x844,1440x900 read-only=yes tmux-size=unchanged'
