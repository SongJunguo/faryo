#!/usr/bin/env bash
set -euo pipefail

# Read-only PTY inventory: open the slash popup, scroll it, and compare command
# names. No slash command is submitted and no existing tmux client is resized.
script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(CDPATH= cd -- "$script_dir/../../../.." && pwd -P)
# shellcheck source=../../../../scripts/runtime-env.sh
source "$repo_root/scripts/runtime-env.sh"
catalog="$repo_root/apps/owner/local-tmux-owner/static/codex-command-catalog.json"
write_cache=false
if [[ "${1:-}" == "--write-cache" ]]; then
  write_cache=true
elif [[ -n "${1:-}" ]]; then
  printf 'usage: %s [--write-cache]\n' "$0" >&2
  exit 2
fi
codex_bin=$(faryo_resolve_codex)
node_bin=$(faryo_resolve_node)
probe_session="faryo-command-inventory-$$"
before_geometry=$(tmux list-windows -a -F '#{session_name}|#{window_width}x#{window_height}' | rg -v "^${probe_session}\\|" | sort || true)

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
after_geometry=$(tmux list-windows -a -F '#{session_name}|#{window_width}x#{window_height}' | rg -v "^${probe_session}\\|" | sort || true)
if [[ "$before_geometry" != "$after_geometry" ]]; then
  printf '%s\n' 'existing tmux geometry changed during command inventory' >&2
  exit 1
fi

observed=$(printf '%s\n' "$observed" | sed '/^$/d' | sort -u)
expected=$("$node_bin" -e 'const fs=require("node:fs");const value=JSON.parse(fs.readFileSync(process.argv[1],"utf8"));process.stdout.write(value.commands.map((item)=>item.command).sort().join("\n"));' "$catalog")
version=$(PATH="$(dirname "$node_bin"):$PATH" "$codex_bin" --version)
observed_version=${version##* }
if [[ "$write_cache" == true ]]; then
  cache_path=${FARYO_CODEX_COMMAND_CATALOG:-$HOME/.faryo/owner/cache/codex-command-catalog.json}
  FARYO_OBSERVED_COMMANDS="$observed" FARYO_OBSERVED_CODEX_VERSION="$observed_version" \
    "$node_bin" - "$cache_path" <<'NODE'
const fs = require('node:fs');
const path = require('node:path');
const target = path.resolve(process.argv[2]);
const commands = [...new Set((process.env.FARYO_OBSERVED_COMMANDS || '').split('\n').filter(Boolean))].sort();
if (!commands.length) throw new Error('empty Codex command inventory');
const payload = JSON.stringify({
  schemaVersion: 1,
  observedCodexVersion: process.env.FARYO_OBSERVED_CODEX_VERSION || '',
  commands,
}, null, 2) + '\n';
fs.mkdirSync(path.dirname(target), { recursive: true, mode: 0o700 });
const temporary = `${target}.tmp-${process.pid}`;
fs.writeFileSync(temporary, payload, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
fs.renameSync(temporary, target);
fs.chmodSync(target, 0o600);
NODE
  count=$(printf '%s\n' "$observed" | wc -l)
  drift=$([[ "$observed" == "$expected" ]] && printf no || printf yes)
  printf 'Codex command runtime catalog updated: %s, %s commands, drift=%s, existing tmux geometry unchanged\n' "$version" "$count" "$drift"
  exit 0
fi
if [[ "$observed" != "$expected" ]]; then
  printf '%s\n' 'Codex slash-command inventory drift detected:' >&2
  comm -3 <(printf '%s\n' "$expected") <(printf '%s\n' "$observed") >&2
  exit 1
fi

count=$(printf '%s\n' "$observed" | wc -l)
printf 'Codex command inventory passed: %s, %s commands, existing tmux geometry unchanged\n' "$version" "$count"
