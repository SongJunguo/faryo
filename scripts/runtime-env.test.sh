#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=runtime-env.sh
source "$ROOT/scripts/runtime-env.sh"

fixture="$(mktemp -d "${TMPDIR:-/tmp}/faryo-runtime-test.XXXXXX")"
cleanup() {
  [[ "$fixture" == /tmp/faryo-runtime-test.* ]] && rm -rf -- "$fixture"
}
trap cleanup EXIT INT TERM

python_stub="$fixture/conda-env/bin/python"
node_root="$fixture/nvm/versions/node/v24.0.0"
node_stub="$node_root/bin/node"
codex_launcher="$node_root/bin/codex"
codex_stub="$node_root/lib/node_modules/@openai/codex/bin/codex.js"
mkdir -p "$(dirname "$python_stub")" "$(dirname "$node_stub")" "$(dirname "$codex_stub")"
printf '#!/usr/bin/env sh\nexit 0\n' >"$python_stub"
printf '#!/usr/bin/env sh\nexit 0\n' >"$node_stub"
printf '#!/usr/bin/env node\n' >"$codex_stub"
chmod 700 "$python_stub" "$node_stub" "$codex_stub"
ln -s "$codex_stub" "$codex_launcher"

resolved=$(FARYO_PYTHON="$python_stub" faryo_resolve_python)
[[ "$resolved" == "$python_stub" ]]

venv_python="$fixture/venv/bin/python"
mkdir -p "$(dirname "$venv_python")"
ln -s "$python_stub" "$venv_python"
resolved=$(FARYO_PYTHON="$venv_python" faryo_resolve_python)
[[ "$resolved" == "$venv_python" ]]

resolved=$(env -u FARYO_PYTHON CONDA_PREFIX="$fixture/conda-env" bash -c \
  'source "$1"; faryo_resolve_python' bash "$ROOT/scripts/runtime-env.sh")
[[ "$resolved" == "$python_stub" ]]

resolved=$(FARYO_NODE_BIN="$node_stub" faryo_resolve_node)
[[ "$resolved" == "$node_stub" ]]

resolved=$(FARYO_CODEX_BIN="$codex_launcher" faryo_resolve_codex)
[[ "$resolved" == "$codex_stub" ]]

resolved=$(env -u FARYO_CODEX_BIN HOME="$fixture" NVM_DIR="$fixture/nvm" PATH=/usr/bin:/bin bash -c \
  'source "$1"; faryo_resolve_codex' bash "$ROOT/scripts/runtime-env.sh")
[[ "$resolved" == "$codex_stub" ]]

resolved=$(env -u FARYO_NODE_BIN HOME="$fixture/empty-home" PATH=/usr/bin:/bin \
  FARYO_CODEX_BIN="$codex_stub" bash -c \
  'source "$1"; faryo_resolve_node' bash "$ROOT/scripts/runtime-env.sh")
[[ "$resolved" == "$node_stub" ]]

owner_home="$fixture/owner-home"
owner_env="$owner_home/owner/config/faryo.env"
mkdir -p "$(dirname "$owner_env")"
printf '%s\n' \
  'FARYO_OWNER_HOST=127.0.0.1' \
  'FARYO_OWNER_PORT=8765' \
  'FARYO_OWNER_TOKEN=generic-token' \
  "FARYO_PYTHON=$python_stub" > "$owner_env"
resolved=$(env HOME="$fixture" FARYO_HOME="$owner_home" FARYO_OWNER_ENV="$owner_env" PATH=/usr/bin:/bin bash -c \
  'source "$1"; load_env; printf "%s\n" "$FARYO_PYTHON"' bash "$ROOT/apps/owner/scripts/_lib.sh")
[[ "$resolved" == "$python_stub" ]]

gateway_home="$fixture/gateway-home"
gateway_env="$gateway_home/gateway/config/faryo.env"
mkdir -p "$(dirname "$gateway_env")"
printf '%s\n' \
  'FARYO_GATEWAY_ROUTES=txy' \
  'FARYO_TXY_OWNER_TOKEN=generic-token' \
  "FARYO_PYTHON=$python_stub" > "$gateway_env"
resolved=$(env HOME="$fixture" FARYO_HOME="$gateway_home" FARYO_GATEWAY_ENV="$gateway_env" PATH=/usr/bin:/bin bash -c \
  'source "$1"; load_env; printf "%s\n" "$FARYO_PYTHON"' bash "$ROOT/apps/gateway/scripts/_lib.sh")
[[ "$resolved" == "$python_stub" ]]

if FARYO_PYTHON="$fixture/missing-python" faryo_resolve_python >/dev/null 2>&1; then
  echo "invalid explicit Python unexpectedly resolved" >&2
  exit 1
fi
if FARYO_NODE_BIN="$fixture/missing-node" faryo_resolve_node >/dev/null 2>&1; then
  echo "invalid explicit Node unexpectedly resolved" >&2
  exit 1
fi
if FARYO_CODEX_BIN="$fixture/missing-codex" faryo_resolve_codex >/dev/null 2>&1; then
  echo "invalid explicit Codex unexpectedly resolved" >&2
  exit 1
fi

echo "runtime discovery tests passed"
