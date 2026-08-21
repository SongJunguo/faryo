#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
# shellcheck source=../../../../scripts/runtime-env.sh
source "$repo_root/scripts/runtime-env.sh"
browser_smoke="$repo_root/apps/owner/local-tmux-owner/tests/browser-katex-smoke.mjs"
session="faryo-protected-resources-$$"
temp_root=''
owner_pid=''

cleanup() {
  if [[ -n "$owner_pid" ]]; then
    kill "$owner_pid" 2>/dev/null || true
    wait "$owner_pid" 2>/dev/null || true
  fi
  tmux kill-session -t "$session" 2>/dev/null || true
  if [[ -n "$temp_root" && "$temp_root" == /tmp/faryo-protected-resources.* && -d "$temp_root" ]]; then
    find "$temp_root" -type f -delete
    find "$temp_root" -depth -type d -empty -delete
  fi
}
trap cleanup EXIT INT TERM

pane_size() {
  tmux list-panes -a -F '#{session_name} #{window_width}x#{window_height}' \
    | awk -v wanted="$session" '$1 == wanted { print $2; exit }'
}

fixture_command="printf '%s\n' '[fixture file](./README.md)' '![fixture image](./apps/owner/local-tmux-owner/static/icons/faryo-logo.png)' '<oai-mem-citation>' '<citation_entries>' 'MEMORY.md:1-2|note=[Anonymous browser fixture]' '</citation_entries>' '<rollout_ids>' '00000000-0000-0000-0000-000000000000' '</rollout_ids>' '</oai-mem-citation>'; exec sleep 120"
tmux new-session -d -x 200 -y 40 -s "$session" -c "$repo_root" "$fixture_command"
initial_size="$(pane_size)"
if [[ -z "$initial_size" ]]; then
  echo 'anonymous protected-resource fixture did not start' >&2
  exit 1
fi

temp_root="$(mktemp -d -t faryo-protected-resources.XXXXXX)"
python_bin="${FARYO_RESOURCE_PYTHON:-$(faryo_resolve_python)}"
node_bin="${FARYO_RESOURCE_NODE:-$(faryo_resolve_node)}"
port="${FARYO_RESOURCE_PORT:-$((20000 + ($$ % 10000)))}"
token="anonymous-resource-$session"
owner_log="$temp_root/owner.log"

FARYO_OWNER_PANE_WIDTH=0 \
PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$python_bin" "$repo_root/apps/owner/local-tmux-owner/server.py" \
    --host 127.0.0.1 --port "$port" --session "$session" --token "$token" --pane-width 0 \
    >"$owner_log" 2>&1 &
owner_pid=$!

owner_ready=0
for _ in $(seq 1 80); do
  if curl -fsS --max-time 1 "http://127.0.0.1:$port/api/status?token=$token&session=$session" >/dev/null 2>&1; then
    owner_ready=1
    break
  fi
  if ! kill -0 "$owner_pid" 2>/dev/null; then break; fi
  sleep 0.1
done
if [[ "$owner_ready" != 1 ]]; then
  echo 'ephemeral Owner did not become ready' >&2
  sed -n '1,80p' "$owner_log" >&2
  exit 1
fi

unauthenticated_status="$(curl -sS --output /dev/null --write-out '%{http_code}' \
  --get --data-urlencode 'path=./README.md' "http://127.0.0.1:$port/api/local-file")"
authenticated_status="$(curl -sS --output /dev/null --write-out '%{http_code}' \
  --header "X-Owner-Token: $token" \
  --get --data-urlencode 'path=./README.md' "http://127.0.0.1:$port/api/local-file")"
if [[ "$unauthenticated_status" != 401 || "$authenticated_status" != 200 ]]; then
  echo 'protected local-file authentication boundary failed' >&2
  exit 1
fi

owner_headers="$(curl -sS -D - -o /dev/null "http://127.0.0.1:$port/?token=$token&session=$session" | tr -d '\r')"
for expected_header in \
  'Content-Security-Policy:' \
  'X-Content-Type-Options: nosniff' \
  'X-Frame-Options: DENY' \
  'Referrer-Policy: no-referrer' \
  'Permissions-Policy:'
do
  if ! rg -Fqi "$expected_header" <<<"$owner_headers"; then
    echo "Owner security header missing: $expected_header" >&2
    exit 1
  fi
done

env \
  "FARYO_SMOKE_URL=http://127.0.0.1:$port/?token=$token&session=$session" \
  'FARYO_SMOKE_SKIP_RENDER_CHECKS=1' \
  'FARYO_SMOKE_PRIVACY_SAFE=1' \
  'FARYO_SMOKE_CHECK_OWNER_LAYOUT=1' \
  'FARYO_SMOKE_EXPECT_GOAL_STATUS=none' \
  'FARYO_SMOKE_CHECK_MODE_SWITCH=1' \
  'FARYO_SMOKE_CHECK_AST_FIXTURE=1' \
  'FARYO_SMOKE_CHECK_QUESTION_NAV=1' \
  'FARYO_SMOKE_MIN_PROTECTED_LINKS=1' \
  'FARYO_SMOKE_MIN_PROTECTED_IMAGES=1' \
  'FARYO_SMOKE_MIN_MEMORY_REFERENCES=1' \
  "FARYO_SMOKE_QUESTION_NAV_SCREENSHOT=${FARYO_RESOURCE_QUESTION_NAV_SCREENSHOT:-}" \
  "FARYO_SMOKE_UI_SCREENSHOT=${FARYO_RESOURCE_UI_SCREENSHOT:-}" \
  "FARYO_SMOKE_UI_FOCUS=${FARYO_RESOURCE_UI_FOCUS:-}" \
  "FARYO_SMOKE_THEME=${FARYO_RESOURCE_UI_THEME:-}" \
  "FARYO_SMOKE_VIEWPORT_WIDTH=${FARYO_RESOURCE_VIEWPORT_WIDTH:-390}" \
  "FARYO_SMOKE_VIEWPORT_HEIGHT=${FARYO_RESOURCE_VIEWPORT_HEIGHT:-844}" \
  "$node_bin" "$browser_smoke"

env \
  "FARYO_SMOKE_URL=http://127.0.0.1:$port/?token=$token&session=$session" \
  'FARYO_SMOKE_SKIP_RENDER_CHECKS=1' \
  'FARYO_SMOKE_PRIVACY_SAFE=1' \
  'FARYO_SMOKE_FORCE_RENDER_FAILURE=1' \
  'FARYO_SMOKE_MIN_RENDER_FALLBACKS=1' \
  'FARYO_SMOKE_MIN_MEMORY_REFERENCES=1' \
  "FARYO_SMOKE_VIEWPORT_WIDTH=${FARYO_RESOURCE_VIEWPORT_WIDTH:-390}" \
  "FARYO_SMOKE_VIEWPORT_HEIGHT=${FARYO_RESOURCE_VIEWPORT_HEIGHT:-844}" \
  "$node_bin" "$browser_smoke"

final_size="$(pane_size)"
if [[ "$initial_size" != "$final_size" ]]; then
  echo 'Owner changed the protected-resource fixture tmux dimensions' >&2
  exit 1
fi

echo 'faryo-browser-protected-resources=PASS auth=401/200 token-url=absent memory-card=visible render-fallback=isolated file=blob image=blob tmux-size=unchanged'
