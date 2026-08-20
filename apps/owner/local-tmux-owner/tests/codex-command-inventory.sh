#!/usr/bin/env bash
set -euo pipefail

# Read-only PTY inventory: open the slash popup, scroll it, and compare command
# names. No slash command is submitted and no existing tmux client is resized.
repo_root=$(git rev-parse --show-toplevel)
# shellcheck source=../../../../scripts/runtime-env.sh
source "$repo_root/scripts/runtime-env.sh"
module="$repo_root/apps/owner/local-tmux-owner/static/codex-commands.js"
codex_bin=$(faryo_resolve_codex)
node_bin=$(faryo_resolve_node)
probe_session="faryo-command-inventory-$$"
geometry_pattern='^(codex[0-9]*|local-tmux-owner|faryo[0-9]+)\|'
before_geometry=$(tmux list-windows -a -F '#{session_name}|#{window_width}x#{window_height}' | rg "$geometry_pattern" | sort || true)

cleanup() {
  if tmux has-session -t "$probe_session" 2>/dev/null; then
    tmux kill-session -t "$probe_session"
  fi
}
trap cleanup EXIT

tmux new-session -d -x 160 -y 50 -s "$probe_session" -c "$repo_root" \
  "exec env PATH=\"$(dirname "$node_bin"):$PATH\" \"$codex_bin\""
sleep "${FARYO_CODEX_INVENTORY_WAIT_SECONDS:-15}"
tmux send-keys -t "$probe_session":0.0 -l '/'
sleep 1

observed=''
for _page in $(seq 0 13); do
  screen=$(tmux capture-pane -p -t "$probe_session":0.0 -S -20)
  page_commands=$(printf '%s\n' "$screen" | sed -n 's/^  \(\/[a-z][a-z-]*\).*/\1/p')
  observed=$(printf '%s\n%s\n' "$observed" "$page_commands")
  for _step in 1 2 3 4 5; do
    tmux send-keys -t "$probe_session":0.0 Down
  done
  sleep 0.35
done

cleanup
after_geometry=$(tmux list-windows -a -F '#{session_name}|#{window_width}x#{window_height}' | rg "$geometry_pattern" | sort || true)
if [[ "$before_geometry" != "$after_geometry" ]]; then
  printf '%s\n' 'existing tmux geometry changed during command inventory' >&2
  exit 1
fi

observed=$(printf '%s\n' "$observed" | sed '/^$/d' | sort -u)
expected=$("$node_bin" -e 'const api=require(process.argv[1]); process.stdout.write(api.inventory.map((item)=>item.command).sort().join("\n"));' "$module")
if [[ "$observed" != "$expected" ]]; then
  printf '%s\n' 'Codex slash-command inventory drift detected:' >&2
  comm -3 <(printf '%s\n' "$expected") <(printf '%s\n' "$observed") >&2
  exit 1
fi

version=$(PATH="$(dirname "$node_bin"):$PATH" "$codex_bin" --version)
count=$(printf '%s\n' "$observed" | wc -l)
printf 'Codex command inventory passed: %s, %s commands, existing tmux geometry unchanged\n' "$version" "$count"
