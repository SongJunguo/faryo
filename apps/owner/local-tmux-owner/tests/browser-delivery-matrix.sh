#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${FARYO_DELIVERY_URL_TEMPLATE:-}" && "$FARYO_DELIVERY_URL_TEMPLATE" != *'{session}'* ]]; then
  echo 'FARYO_DELIVERY_URL_TEMPLATE must contain {session}' >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
# shellcheck source=../../../../scripts/runtime-env.sh
source "$repo_root/scripts/runtime-env.sh"
receiver='apps/owner/local-tmux-owner/tests/terminal-delivery-receiver.mjs'
browser_smoke="$repo_root/apps/owner/local-tmux-owner/tests/browser-katex-smoke.mjs"
matrix="$repo_root/apps/owner/local-tmux-owner/tests/browser-delivery-matrix.json"
session="faryo-delivery-matrix-$$"
approval_session="${session}-approval"
temp_root=''
owner_pid=''
attachment_smoke=0
node_bin="${FARYO_DELIVERY_NODE:-$(faryo_resolve_node)}"

cleanup() {
  if [[ -n "$owner_pid" ]]; then
    kill "$owner_pid" 2>/dev/null || true
    wait "$owner_pid" 2>/dev/null || true
  fi
  tmux kill-session -t "$session" 2>/dev/null || true
  tmux kill-session -t "$approval_session" 2>/dev/null || true
  if [[ -n "$temp_root" && "$temp_root" == /tmp/faryo-delivery-matrix.* && -d "$temp_root" ]]; then
    find "$temp_root" -type f -delete
    find "$temp_root" -depth -type d -empty -delete
  fi
}
trap cleanup EXIT INT TERM

tmux new-session -d -s "$session" -c "$repo_root" "exec \"$node_bin\" \"$repo_root/$receiver\""
ready=0
for _ in $(seq 1 50); do
  if tmux capture-pane -p -t "$session" 2>/dev/null | rg -q 'FARYO_DELIVERY_READY'; then
    ready=1
    break
  fi
  sleep 0.1
done
if [[ "$ready" != 1 ]]; then
  echo 'anonymous delivery receiver did not become ready' >&2
  exit 1
fi

initial_size="$(tmux display-message -p -t "$session" '#{window_width}x#{window_height}')"
url_template="${FARYO_DELIVERY_URL_TEMPLATE:-}"

if [[ -z "$url_template" ]]; then
  temp_root="$(mktemp -d -t faryo-delivery-matrix.XXXXXX)"
  python_bin="${FARYO_DELIVERY_PYTHON:-$(faryo_resolve_python)}"
  port="${FARYO_DELIVERY_PORT:-$((18000 + ($$ % 10000)))}"
  token="anonymous-delivery-$session"
  owner_log="$temp_root/owner.log"
  FARYO_OWNER_INBOX_DIR="$temp_root/inbox" \
  FARYO_OWNER_PANE_WIDTH=0 \
    "$python_bin" apps/owner/local-tmux-owner/server.py \
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
  url_template="http://127.0.0.1:$port/?token=$token&session={session}"
  attachment_smoke=1
fi

target_url="${url_template//\{session\}/$session}"

smoke_env=(
  "FARYO_SMOKE_URL=$target_url"
  "FARYO_SMOKE_SEND_MATRIX_FILE=$matrix"
  'FARYO_SMOKE_SKIP_RENDER_CHECKS=1'
  'FARYO_SMOKE_PRIVACY_SAFE=1'
  'FARYO_SMOKE_CHECK_OWNER_LAYOUT=1'
  "FARYO_SMOKE_VIEWPORT_WIDTH=${FARYO_SMOKE_VIEWPORT_WIDTH:-390}"
  "FARYO_SMOKE_VIEWPORT_HEIGHT=${FARYO_SMOKE_VIEWPORT_HEIGHT:-844}"
)
if [[ "$attachment_smoke" == 1 ]]; then
  smoke_env+=(
    'FARYO_SMOKE_CLIPBOARD_IMAGE=1'
    'FARYO_SMOKE_ATTACHMENT_PROMPT=Submit the anonymous clipboard image once.'
    'FARYO_SMOKE_ATTACHMENT_EXPECT_OUTPUT=FARYO_DELIVERY_ACK_21'
  )
fi
recovery_start_index=$((21 + attachment_smoke))
smoke_env+=(
  'FARYO_SMOKE_CHECK_RECOVERY=1'
  "FARYO_SMOKE_TMUX_SESSION=$session"
  "FARYO_SMOKE_RECOVERY_START_INDEX=$recovery_start_index"
  'FARYO_SMOKE_CHECK_AMBIGUOUS_SEND=1'
  "FARYO_SMOKE_AMBIGUOUS_SEND_INDEX=$((recovery_start_index + 2))"
)

  env "${smoke_env[@]}" "$node_bin" "$browser_smoke"

missing_url="${url_template//\{session\}/${session}-missing}"
env \
  "FARYO_SMOKE_URL=$missing_url" \
  'FARYO_SMOKE_SEND_TEXT=anonymous failed delivery draft' \
  'FARYO_SMOKE_EXPECT_SEND_FAILURE=1' \
  'FARYO_SMOKE_SKIP_RENDER_CHECKS=1' \
  'FARYO_SMOKE_PRIVACY_SAFE=1' \
  "FARYO_SMOKE_VIEWPORT_WIDTH=${FARYO_SMOKE_VIEWPORT_WIDTH:-390}" \
  "FARYO_SMOKE_VIEWPORT_HEIGHT=${FARYO_SMOKE_VIEWPORT_HEIGHT:-844}" \
  "$node_bin" "$browser_smoke"

tmux new-session -d -s "$approval_session" "printf 'Press enter to confirm or esc to go back\n'; sleep 60"
approval_size="$(tmux display-message -p -t "$approval_session" '#{window_width}x#{window_height}')"
approval_url="${url_template//\{session\}/$approval_session}"
env \
  "FARYO_SMOKE_URL=$approval_url" \
  'FARYO_SMOKE_SKIP_RENDER_CHECKS=1' \
  'FARYO_SMOKE_PRIVACY_SAFE=1' \
  'FARYO_SMOKE_CHECK_OWNER_LAYOUT=1' \
  'FARYO_SMOKE_EXPECT_KEY_NAV=visible' \
  "FARYO_SMOKE_VIEWPORT_WIDTH=${FARYO_SMOKE_VIEWPORT_WIDTH:-390}" \
  "FARYO_SMOKE_VIEWPORT_HEIGHT=${FARYO_SMOKE_VIEWPORT_HEIGHT:-844}" \
  "$node_bin" "$browser_smoke"
if [[ "$approval_size" != "$(tmux display-message -p -t "$approval_session" '#{window_width}x#{window_height}')" ]]; then
  echo 'Owner changed the approval test tmux dimensions' >&2
  exit 1
fi
echo 'faryo-browser-approval-controls=PASS normal=hidden approval=visible'

final_size="$(tmux display-message -p -t "$session" '#{window_width}x#{window_height}')"
if [[ "$initial_size" != "$final_size" ]]; then
  echo 'Owner changed the anonymous tmux window dimensions' >&2
  exit 1
fi

expected_ack_count=$((23 + attachment_smoke))
actual_ack_count="$(tmux capture-pane -p -S - -t "$session" | awk '/^FARYO_DELIVERY_ACK_/ { count += 1 } END { print count + 0 }')"
if [[ "$actual_ack_count" != "$expected_ack_count" ]]; then
  echo "anonymous receiver ACK count mismatch: expected=$expected_ack_count actual=$actual_ack_count" >&2
  exit 1
fi

if [[ "$attachment_smoke" == 1 ]]; then
  uploaded_count="$(find "$temp_root/inbox" -type f 2>/dev/null | wc -l)"
  if [[ "$uploaded_count" != 1 ]]; then
    echo 'attachment smoke did not create exactly one isolated upload' >&2
    exit 1
  fi
fi

echo "faryo-browser-delivery-matrix=PASS count=20 attachment=$attachment_smoke tmux-size=unchanged"
