#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
receiver="$repo_root/apps/owner/local-tmux-owner/tests/terminal-delivery-receiver.mjs"
browser_smoke="$repo_root/apps/owner/local-tmux-owner/tests/browser-katex-smoke.mjs"
suffix="$$"
session_a="faryo-send-isolation-a-$suffix"
session_b="faryo-send-isolation-b-$suffix"
temp_root="$(mktemp -d -t faryo-send-isolation.XXXXXX)"
python_bin="${FARYO_DELIVERY_PYTHON:-python3}"
owner_port="${FARYO_ISOLATION_OWNER_PORT:-$((23000 + (suffix % 1000)))}"
proxy_port="${FARYO_ISOLATION_PROXY_PORT:-$((24000 + (suffix % 1000)))}"
token="anonymous-isolation-$suffix"
owner_pid=''
proxy_pid=''

cleanup() {
  if [[ -n "$proxy_pid" ]]; then
    kill "$proxy_pid" 2>/dev/null || true
    wait "$proxy_pid" 2>/dev/null || true
  fi
  if [[ -n "$owner_pid" ]]; then
    kill "$owner_pid" 2>/dev/null || true
    wait "$owner_pid" 2>/dev/null || true
  fi
  tmux kill-session -t "$session_a" 2>/dev/null || true
  tmux kill-session -t "$session_b" 2>/dev/null || true
  if [[ "$temp_root" == /tmp/faryo-send-isolation.* && -d "$temp_root" ]]; then
    find "$temp_root" -type f -delete
    find "$temp_root" -depth -type d -empty -delete
  fi
}
trap cleanup EXIT INT TERM

for session in "$session_a" "$session_b"; do
  tmux new-session -d -s "$session" -c "$repo_root" "exec node $receiver"
done
for _ in $(seq 1 50); do
  ready_a=0
  ready_b=0
  tmux capture-pane -p -t "$session_a" 2>/dev/null | rg -q 'FARYO_DELIVERY_READY' && ready_a=1 || true
  tmux capture-pane -p -t "$session_b" 2>/dev/null | rg -q 'FARYO_DELIVERY_READY' && ready_b=1 || true
  [[ "$ready_a" == 1 && "$ready_b" == 1 ]] && break
  sleep 0.1
done
[[ "${ready_a:-0}" == 1 && "${ready_b:-0}" == 1 ]] || { echo 'isolation receivers did not become ready' >&2; exit 1; }

initial_a="$(tmux display-message -p -t "$session_a" '#{window_width}x#{window_height}')"
initial_b="$(tmux display-message -p -t "$session_b" '#{window_width}x#{window_height}')"
FARYO_OWNER_DATA="$temp_root/data" \
FARYO_OWNER_INBOX_DIR="$temp_root/inbox" \
FARYO_OWNER_PANE_WIDTH=0 \
  "$python_bin" "$repo_root/apps/owner/local-tmux-owner/server.py" \
    --host 127.0.0.1 --port "$owner_port" --session "$session_a" --token "$token" --pane-width 0 \
    >"$temp_root/owner.log" 2>&1 &
owner_pid=$!
for _ in $(seq 1 80); do
  curl -fsS --max-time 1 "http://127.0.0.1:$owner_port/health" >/dev/null 2>&1 && break
  kill -0 "$owner_pid" 2>/dev/null || { echo 'isolation Owner exited early' >&2; exit 1; }
  sleep 0.1
done
curl -fsS --max-time 1 "http://127.0.0.1:$owner_port/health" >/dev/null

# The production page uses /txy/. This tiny loopback-only proxy preserves that
# route shape while forwarding the isolated test to its ephemeral Owner.
node -e '
const http = require("http");
const ownerPort = Number(process.argv[1]);
const proxyPort = Number(process.argv[2]);
http.createServer((request, response) => {
  const upstreamPath = request.url.startsWith("/txy") ? (request.url.slice(4) || "/") : request.url;
  const headers = { ...request.headers, host: `127.0.0.1:${ownerPort}` };
  const upstream = http.request({ host: "127.0.0.1", port: ownerPort, path: upstreamPath, method: request.method, headers }, (result) => {
    response.writeHead(result.statusCode || 502, result.headers);
    result.pipe(response);
  });
  upstream.on("error", () => {
    response.writeHead(502, { "content-type": "application/json" });
    response.end(JSON.stringify({ ok: false, error: "isolated upstream unavailable" }));
  });
  request.pipe(upstream);
}).listen(proxyPort, "127.0.0.1");
' "$owner_port" "$proxy_port" >"$temp_root/proxy.log" 2>&1 &
proxy_pid=$!
for _ in $(seq 1 50); do
  curl -fsS --max-time 1 "http://127.0.0.1:$proxy_port/txy/health" >/dev/null 2>&1 && break
  kill -0 "$proxy_pid" 2>/dev/null || { echo 'isolation proxy exited early' >&2; exit 1; }
  sleep 0.1
done
curl -fsS --max-time 1 "http://127.0.0.1:$proxy_port/txy/health" >/dev/null

env \
  "FARYO_SMOKE_URL=http://127.0.0.1:$proxy_port/txy/?token=$token&session=$session_a" \
  'FARYO_SMOKE_CHECK_SESSION_SEND_ISOLATION=1' \
  "FARYO_SMOKE_SESSION_A=$session_a" \
  "FARYO_SMOKE_SESSION_B=$session_b" \
  'FARYO_SMOKE_SKIP_RENDER_CHECKS=1' \
  'FARYO_SMOKE_PRIVACY_SAFE=1' \
  'FARYO_SMOKE_CHECK_OWNER_LAYOUT=1' \
  'FARYO_SMOKE_VIEWPORT_WIDTH=390' \
  'FARYO_SMOKE_VIEWPORT_HEIGHT=844' \
  node "$browser_smoke"

acks_a="$(tmux capture-pane -p -S - -t "$session_a" | awk '/^FARYO_DELIVERY_ACK_/ { count += 1 } END { print count + 0 }')"
acks_b="$(tmux capture-pane -p -S - -t "$session_b" | awk '/^FARYO_DELIVERY_ACK_/ { count += 1 } END { print count + 0 }')"
[[ "$acks_a" == 2 && "$acks_b" == 0 ]] || { echo "session isolation ACK mismatch: a=$acks_a b=$acks_b" >&2; exit 1; }
[[ "$initial_a" == "$(tmux display-message -p -t "$session_a" '#{window_width}x#{window_height}')" ]]
[[ "$initial_b" == "$(tmux display-message -p -t "$session_b" '#{window_width}x#{window_height}')" ]]

echo 'faryo-browser-session-send-isolation=PASS target=a acks=2 target=b acks=0 tmux-size=unchanged'
