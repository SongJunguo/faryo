#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FARYO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
FARYO_HOME="${FARYO_HOME:-$HOME/.faryo}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE="$UNIT_DIR/faryo-gateway.service"
TEMPLATE="$FARYO_ROOT/deploy/user-systemd/faryo-gateway.service"
ENV_FILE="${FARYO_GATEWAY_ENV:-$FARYO_HOME/gateway/config/faryo.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing private Gateway config: $ENV_FILE" >&2
  echo "run apps/gateway/scripts/init-local-gateway.sh first" >&2
  exit 2
fi

install -d -m 0755 "$UNIT_DIR"
tmp="$(mktemp "${TMPDIR:-/tmp}/faryo-gateway-unit.XXXXXX")"
trap 'unlink "$tmp" 2>/dev/null || true' EXIT
sed \
  -e "s|@FARYO_ROOT@|$FARYO_ROOT|g" \
  -e "s|@FARYO_HOME@|$FARYO_HOME|g" \
  "$TEMPLATE" > "$tmp"
install -m 0644 "$tmp" "$UNIT_FILE"

systemctl --user daemon-reload
systemctl --user enable --now faryo-gateway.service
printf 'installed and started: %s\n' "$UNIT_FILE"
