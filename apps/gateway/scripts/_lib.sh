#!/usr/bin/env bash
set -euo pipefail

FARYO_GATEWAY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FARYO_HOME="${FARYO_HOME:-$HOME/.faryo}"
ENV_FILE="${FARYO_GATEWAY_ENV:-${FARYO_ENV_FILE:-$FARYO_HOME/gateway/config/faryo.env}}"

load_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "missing env file: $ENV_FILE" >&2
    echo "copy config/faryo.env.example to config/faryo.env and fill route owner tokens" >&2
    exit 2
  fi
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  : "${FARYO_TXY_OWNER_TOKEN:?missing FARYO_TXY_OWNER_TOKEN}"
  : "${FARYO_HP_OWNER_TOKEN:?missing FARYO_HP_OWNER_TOKEN}"
  : "${FARYO_PC_OWNER_TOKEN:?missing FARYO_PC_OWNER_TOKEN}"
}
