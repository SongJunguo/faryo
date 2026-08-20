#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env

GATEWAY_HOST="${GATEWAY_HOST:-127.0.0.1}"
GATEWAY_PORT="${GATEWAY_PORT:-8780}"

if [[ "$GATEWAY_HOST" != "127.0.0.1" && "$GATEWAY_HOST" != "localhost" ]]; then
  echo "refusing cleanup for non-local gateway host: $GATEWAY_HOST" >&2
  exit 1
fi

mapfile -t pids < <(ss -H -ltnp "sport = :$GATEWAY_PORT" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
if [[ "${#pids[@]}" -eq 0 ]]; then
  exit 0
fi

safe_pids=()
foreign=()
for pid in "${pids[@]}"; do
  [[ -r "/proc/$pid/cmdline" ]] || continue
  cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
  owner="$(ps -o user= -p "$pid" 2>/dev/null | awk '{print $1}')"
  if [[ "$owner" == "$(id -un)" && "$cmdline" == *"$FARYO_GATEWAY_ROOT/server/server.py"* ]]; then
    safe_pids+=("$pid")
  elif [[ "$owner" == "$(id -un)" && "$cmdline" == *"$FARYO_GATEWAY_ROOT/server/run_asgi.py"* ]]; then
    safe_pids+=("$pid")
  elif [[ "$owner" == "$(id -un)" && "$cmdline" == *"server/server.py"* ]]; then
    safe_pids+=("$pid")
  elif [[ "$owner" == "$(id -un)" && "$cmdline" == *"server/run_asgi.py"* ]]; then
    safe_pids+=("$pid")
  else
    foreign+=("$pid:$owner:$cmdline")
  fi
done

if [[ "${#foreign[@]}" -gt 0 ]]; then
  printf 'refusing to kill foreign listener on port %s:\n' "$GATEWAY_PORT" >&2
  printf '  %s\n' "${foreign[@]}" >&2
  exit 1
fi

if [[ "${#safe_pids[@]}" -eq 0 ]]; then
  echo "no safe Faryo gateway listener found on port $GATEWAY_PORT" >&2
  exit 1
fi

kill "${safe_pids[@]}" 2>/dev/null || true
for _ in $(seq 1 20); do
  alive=()
  for pid in "${safe_pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      alive+=("$pid")
    fi
  done
  [[ "${#alive[@]}" -eq 0 ]] && exit 0
  sleep 0.25
done
kill -KILL "${safe_pids[@]}" 2>/dev/null || true
