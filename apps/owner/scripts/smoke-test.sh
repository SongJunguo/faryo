#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env

SMOKE_DIRECT="faryo-smoke-direct-$$"
SMOKE_ALLOWED="faryo-smoke-$$"
SMOKE_MANAGED="$SMOKE_ALLOWED-faryo-0101-000000-abcd"
SMOKE_OTHER="$SMOKE_ALLOWED-prod"
SMOKE_FILE="$FARYO_OWNER_INBOX_DIR/faryo-smoke-$$.md"
SMOKE_OUTSIDE=$(mktemp --suffix=.md)
TMP_EVENTS=$(mktemp)
TMP=$(mktemp)
cleanup() {
  rm -f "$TMP_EVENTS" "$TMP" "$TMP.sessions" "$TMP.status" "$TMP.forbidden" "$TMP.file" "$TMP.view" "$SMOKE_FILE" "$SMOKE_OUTSIDE"
  tmux kill-session -t "$SMOKE_DIRECT" 2>/dev/null || true
  tmux kill-session -t "$SMOKE_ALLOWED" 2>/dev/null || true
  tmux kill-session -t "$SMOKE_MANAGED" 2>/dev/null || true
  tmux kill-session -t "$SMOKE_OTHER" 2>/dev/null || true
}
trap cleanup EXIT
tmux kill-session -t "$SMOKE_DIRECT" 2>/dev/null || true
tmux new-session -d -s "$SMOKE_DIRECT" "printf 'faryo smoke ready\n'; sleep 60"

echo "== health =="
curl_quiet "$(health_url)" | python3 -m json.tool

echo
echo "== status =="
curl_quiet -H "X-Owner-Token: $FARYO_OWNER_TOKEN" "$(api_url "status?session=$SMOKE_DIRECT")" | python3 -m json.tool

echo
echo "== events =="
curl --noproxy '*' -sS -N --max-time 3 -H "X-Owner-Token: $FARYO_OWNER_TOKEN" "$(api_url "events?session=$SMOKE_DIRECT")" > "$TMP_EVENTS" 2>/dev/null || true
grep -q '^event: capture' "$TMP_EVENTS"
grep -q '"agentRunning":' "$TMP_EVENTS"

echo
echo "== pet static =="
test "$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' "http://$FARYO_OWNER_HOST:$FARYO_OWNER_PORT/pet/pet-idle.png")" = "200"
test "$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' "http://$FARYO_OWNER_HOST:$FARYO_OWNER_PORT/pet/pet-sprite.png")" = "200"
test "$(curl --noproxy '*' -sS -o "$TMP" -w '%{http_code}' "http://$FARYO_OWNER_HOST:$FARYO_OWNER_PORT/compact-rules-codex.js")" = "200"
grep -q 'FaryoCodexCompactRules' "$TMP"
test "$(curl --noproxy '*' -sS -o "$TMP" -w '%{http_code}' "http://$FARYO_OWNER_HOST:$FARYO_OWNER_PORT/compact-rules-claude.js")" = "200"
grep -q 'FaryoClaudeCompactRules' "$TMP"

echo
echo "== capture =="
curl_quiet -H "X-Owner-Token: $FARYO_OWNER_TOKEN" "$(api_url "capture?session=$SMOKE_DIRECT&lines=$WEB_CAPTURE_LINES")" > "$TMP"
python3 - <<'PY' "$TMP"
import json, sys
p=json.load(open(sys.argv[1], encoding='utf-8'))
print({'ok':p.get('ok'), 'phase':p.get('phase'), 'lines':len(p.get('text','').splitlines())})
assert p.get('ok') is True
PY

echo
echo "== agent sessions =="
curl_quiet -H "X-Owner-Token: $FARYO_OWNER_TOKEN" -H "X-Faryo-Session-Namespace: $SMOKE_ALLOWED" "$(api_url "agent-sessions?limit=3")" > "$TMP.sessions"
python3 - <<'PY' "$TMP.sessions"
import json, sys
payload=json.load(open(sys.argv[1], encoding='utf-8'))
print({'ok': payload.get('ok'), 'activeCount': payload.get('activeCount'), 'sessions': len(payload.get('sessions', []))})
assert payload.get('ok') is True
assert isinstance(payload.get('sessions'), list)
assert isinstance(payload.get('activeCount'), int)
PY
echo
echo "== local files =="
printf 'smoke file\n' > "$SMOKE_FILE"
printf 'outside file\n' > "$SMOKE_OUTSIDE"
direct=$(curl --noproxy '*' -sS -o "$TMP.file" -w '%{http_code}' --get --data-urlencode "token=$FARYO_OWNER_TOKEN" --data-urlencode "path=$SMOKE_FILE" "$(api_url local-file)")
test "$direct" = "200"
grep -q 'smoke file' "$TMP.file"
view=$(curl --noproxy '*' -sS -o "$TMP.view" -w '%{http_code}' --get --data-urlencode "token=$FARYO_OWNER_TOKEN" --data-urlencode "path=$SMOKE_FILE" "$(api_url "local-file/view")")
test "$view" = "200"
grep -q 'token=' "$TMP.view"
outside=$(curl --noproxy '*' -sS -o "$TMP.forbidden" -w '%{http_code}' -H "X-Owner-Token: $FARYO_OWNER_TOKEN" -H "X-Faryo-Workspace-Root: /tmp" --get --data-urlencode "path=$SMOKE_OUTSIDE" "$(api_url local-file)")
test "$outside" = "200"
printf 'local file status: direct=%s view=%s outside=%s\n' "$direct" "$view" "$outside"

echo "SMOKE PASS"
