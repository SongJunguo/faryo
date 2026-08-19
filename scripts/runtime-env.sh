#!/usr/bin/env bash

# Runtime discovery shared by source checks and release automation. Functions
# print only the resolved executable path on stdout; diagnostics go to stderr.

faryo_command_path() {
  local value="${1:-}"
  [[ -n "$value" ]] || return 1
  if [[ "$value" == */* ]]; then
    [[ -x "$value" ]] || return 1
    readlink -f -- "$value"
    return
  fi
  command -v -- "$value" 2>/dev/null
}

faryo_resolve_conda() {
  local candidate
  for candidate in \
    "${CONDA_EXE:-}" \
    "$(command -v conda 2>/dev/null || true)" \
    "${HOME:-}/miniconda3/bin/conda" \
    "${HOME:-}/anaconda3/bin/conda"
  do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    readlink -f -- "$candidate"
    return 0
  done
  return 1
}

faryo_resolve_python() {
  local candidate conda_bin env_root
  if [[ -n "${FARYO_PYTHON:-}" ]]; then
    candidate=$(faryo_command_path "$FARYO_PYTHON") || {
      echo "FARYO_PYTHON is not executable: $FARYO_PYTHON" >&2
      return 1
    }
    printf '%s\n' "$candidate"
    return 0
  fi
  if [[ -n "${CONDA_PREFIX:-}" && -x "$CONDA_PREFIX/bin/python" ]]; then
    readlink -f -- "$CONDA_PREFIX/bin/python"
    return 0
  fi
  if conda_bin=$(faryo_resolve_conda); then
    env_root=$("$conda_bin" env list 2>/dev/null | awk '$1 == "faryo" { print $NF; exit }')
    if [[ -n "$env_root" && -x "$env_root/bin/python" ]]; then
      readlink -f -- "$env_root/bin/python"
      return 0
    fi
  fi
  if candidate=$(command -v python3 2>/dev/null) && [[ -x "$candidate" ]]; then
    readlink -f -- "$candidate"
    return 0
  fi
  echo "Python was not found. Set FARYO_PYTHON or activate the project Conda environment." >&2
  return 1
}

faryo_node_next_to_codex() {
  local codex_path resolved node_root candidate
  [[ -n "${FARYO_CODEX_BIN:-}" ]] || return 1
  codex_path=$(faryo_command_path "$FARYO_CODEX_BIN") || return 1
  resolved=$(readlink -f -- "$codex_path")
  case "$resolved" in
    */lib/node_modules/*)
      node_root="${resolved%%/lib/node_modules/*}"
      candidate="$node_root/bin/node"
      [[ -x "$candidate" ]] || return 1
      readlink -f -- "$candidate"
      return 0
      ;;
  esac
  return 1
}

faryo_latest_nvm_node() {
  local root candidate
  for root in "${NVM_DIR:-}" "${HOME:-}/.nvm"; do
    [[ -d "$root/versions/node" ]] || continue
    candidate=$(find "$root/versions/node" -mindepth 3 -maxdepth 3 -type f -path '*/bin/node' -perm -u+x -print 2>/dev/null | sort -V | tail -n 1)
    if [[ -n "$candidate" ]]; then
      readlink -f -- "$candidate"
      return 0
    fi
  done
  return 1
}

faryo_resolve_node() {
  local candidate
  if [[ -n "${FARYO_NODE_BIN:-}" ]]; then
    candidate=$(faryo_command_path "$FARYO_NODE_BIN") || {
      echo "FARYO_NODE_BIN is not executable: $FARYO_NODE_BIN" >&2
      return 1
    }
    printf '%s\n' "$candidate"
    return 0
  fi
  if candidate=$(command -v node 2>/dev/null) && [[ -x "$candidate" ]]; then
    readlink -f -- "$candidate"
    return 0
  fi
  if candidate=$(faryo_node_next_to_codex); then
    printf '%s\n' "$candidate"
    return 0
  fi
  if candidate=$(faryo_latest_nvm_node); then
    printf '%s\n' "$candidate"
    return 0
  fi
  echo "Node.js was not found. Set FARYO_NODE_BIN or expose the NVM Node binary." >&2
  return 1
}
