#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
# shellcheck source=../../../../scripts/runtime-env.sh
source "$repo_root/scripts/runtime-env.sh"
receiver="$repo_root/apps/owner/local-tmux-owner/tests/terminal-delivery-receiver.mjs"
session="faryo-send-restart-$$"
temp_root="$(mktemp -d -t faryo-send-restart.XXXXXX)"
python_bin="${FARYO_RESTART_PYTHON:-$(faryo_resolve_python)}"
node_bin="${FARYO_RESTART_NODE:-$(faryo_resolve_node)}"
port="${FARYO_RESTART_PORT:-$((22000 + ($$ % 10000)))}"
token="anonymous-restart-$session"
owner_pid=''

cleanup() {
  if [[ -n "$owner_pid" ]]; then
    kill "$owner_pid" 2>/dev/null || true
    wait "$owner_pid" 2>/dev/null || true
  fi
  tmux kill-session -t "$session" 2>/dev/null || true
  if [[ "$temp_root" == /tmp/faryo-send-restart.* && -d "$temp_root" ]]; then
    find "$temp_root" -type f -delete
    find "$temp_root" -depth -type d -empty -delete
  fi
}
trap cleanup EXIT INT TERM

tmux new-session -d -s "$session" -c "$repo_root" "exec \"$node_bin\" \"$receiver\""
for _ in $(seq 1 50); do
  tmux capture-pane -p -t "$session" 2>/dev/null | rg -q 'FARYO_DELIVERY_READY' && break
  sleep 0.1
done
tmux capture-pane -p -t "$session" | rg -q 'FARYO_DELIVERY_READY' || { echo 'restart receiver did not become ready' >&2; exit 1; }

start_owner() {
  FARYO_OWNER_DATA="$temp_root/data" \
  FARYO_OWNER_INBOX_DIR="$temp_root/inbox" \
  FARYO_OWNER_PANE_WIDTH=0 \
  PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$python_bin" "$repo_root/apps/owner/local-tmux-owner/server.py" \
      --host 127.0.0.1 --port "$port" --session "$session" --token "$token" --pane-width 0 \
      >"$temp_root/owner.log" 2>&1 &
  owner_pid=$!
  for _ in $(seq 1 80); do
    if curl -fsS --max-time 1 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then return; fi
    kill -0 "$owner_pid" 2>/dev/null || break
    sleep 0.1
  done
  echo 'ephemeral Owner did not become ready' >&2
  exit 1
}

stop_owner() {
  kill "$owner_pid"
  wait "$owner_pid" 2>/dev/null || true
  owner_pid=''
}

payload="$(jq -cn --arg session "$session" --arg text 'anonymous restart idempotency' --arg id 'web-restart-idempotency' '{session:$session,text:$text,clientMessageId:$id}')"
start_owner
first="$(curl -fsS -H "X-Owner-Token: $token" -H 'Content-Type: application/json' --data-binary "$payload" "http://127.0.0.1:$port/api/send")"
[[ "$(jq -r '.duplicate' <<<"$first")" == 'false' ]] || { echo 'first delivery was unexpectedly duplicate' >&2; exit 1; }
stop_owner

start_owner
second="$(curl -fsS -H "X-Owner-Token: $token" -H 'Content-Type: application/json' --data-binary "$payload" "http://127.0.0.1:$port/api/send")"
[[ "$(jq -r '.duplicate' <<<"$second")" == 'true' ]] || { echo 'restart delivery was not deduplicated' >&2; exit 1; }

ack_count="$(tmux capture-pane -p -S - -t "$session" | awk '/^FARYO_DELIVERY_ACK_/ { count += 1 } END { print count + 0 }')"
[[ "$ack_count" == 1 ]] || { echo "restart delivery ACK count mismatch: $ack_count" >&2; exit 1; }
receipt="$temp_root/data/send-deliveries/web-restart-idempotency.json"
[[ -f "$receipt" && "$(stat -c '%a' "$receipt")" == 600 ]] || { echo 'persistent delivery receipt permissions are wrong' >&2; exit 1; }
[[ "$(stat -c '%a' "$(dirname "$receipt")")" == 700 ]] || { echo 'persistent delivery directory permissions are wrong' >&2; exit 1; }
if rg -Fq 'anonymous restart idempotency' "$receipt"; then
  echo 'persistent delivery receipt leaked the message body' >&2
  exit 1
fi

echo 'faryo-send-restart-idempotency=PASS duplicates=0/1 tmux-acks=1 directory=0700 receipt=0600 body=absent'
