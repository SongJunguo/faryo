#!/usr/bin/env bash
set -euo pipefail

FARYO_GATEWAY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FARYO_REPO_ROOT="$(cd "$FARYO_GATEWAY_ROOT/../.." && pwd)"
# shellcheck source=../../../scripts/runtime-env.sh
source "$FARYO_REPO_ROOT/scripts/runtime-env.sh"
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
  # The Python config loader validates tokens for enabled routes only. Keeping
  # that validation in one place avoids requiring placeholder secrets for
  # disabled routes.
  : "${FARYO_PYTHON:=python3}"
  FARYO_PYTHON="$(faryo_resolve_python)"
  export FARYO_PYTHON
}
