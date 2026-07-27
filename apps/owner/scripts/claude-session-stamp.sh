#!/usr/bin/env bash
# SessionStart hook injected by the Owner at claude launch. Claude Code fires
# it on startup/resume/clear with the live session id on stdin; stamping that
# id onto the owning tmux session keeps the Owner's active map tracking id
# rotation (/clear, resume) instead of the id frozen at dispatch time.
set -u
[ -n "${TMUX_PANE:-}" ] || exit 0
id=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin).get("session_id") or ""))' 2>/dev/null) || exit 0
[ -n "$id" ] || exit 0
tmux set-option -t "$TMUX_PANE" @faryo_agent_session_id "$id" 2>/dev/null || true
exit 0
