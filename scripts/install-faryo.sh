#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  install-faryo.sh [--version vX.Y.Z] [--python /path/to/python3] [--workspace /path] [--migrate-owner]

Downloads the exact Faryo source release and SHA-256 manifest, verifies both,
then creates a versioned private virtual environment and user services.
USAGE
}

VERSION="${FARYO_VERSION:-}"
BOOTSTRAP_PYTHON="${FARYO_BOOTSTRAP_PYTHON:-}"
WORKSPACE="${FARYO_INITIAL_WORKSPACE:-$PWD}"
REPOSITORY="SongJunguo/faryo"
MIGRATE_OWNER=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      VERSION="$2"
      shift 2
      ;;
    --python)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      BOOTSTRAP_PYTHON="$2"
      shift 2
      ;;
    --workspace)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      WORKSPACE="$2"
      shift 2
      ;;
    --migrate-owner)
      MIGRATE_OWNER=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unsupported argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { echo "tar is required" >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum is required" >&2; exit 1; }
command -v tmux >/dev/null 2>&1 || { echo "tmux is required" >&2; exit 1; }
command -v systemctl >/dev/null 2>&1 || { echo "systemd user services are required" >&2; exit 1; }
systemctl --user show-environment >/dev/null 2>&1 || { echo "the systemd user manager is unavailable" >&2; exit 1; }

if [[ -z "$BOOTSTRAP_PYTHON" ]]; then
  if [[ -x /usr/bin/python3 ]]; then
    BOOTSTRAP_PYTHON=/usr/bin/python3
  else
    BOOTSTRAP_PYTHON="$(command -v python3 || true)"
  fi
fi
[[ -n "$BOOTSTRAP_PYTHON" && -x "$BOOTSTRAP_PYTHON" ]] || { echo "Python 3.10+ is required" >&2; exit 1; }
"$BOOTSTRAP_PYTHON" -c 'import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "Python 3.10+ with the venv module is required: $BOOTSTRAP_PYTHON" >&2
  exit 1
}
[[ -d "$WORKSPACE" ]] || { echo "initial workspace is not a directory: $WORKSPACE" >&2; exit 1; }
WORKSPACE="$(cd "$WORKSPACE" && pwd -P)"

TEMP_DIR="$(mktemp -d -t faryo-install.XXXXXXXX)"
cleanup() {
  [[ -n "${TEMP_DIR:-}" && -d "$TEMP_DIR" ]] && rm -rf -- "$TEMP_DIR"
}
trap cleanup EXIT

curl_release() {
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location --max-time 120 "$1" -o "$2"
}

if [[ -z "$VERSION" ]]; then
  metadata="$TEMP_DIR/latest.json"
  curl_release "https://api.github.com/repos/$REPOSITORY/releases/latest" "$metadata"
  VERSION="$("$BOOTSTRAP_PYTHON" - "$metadata" <<'PY'
import json
import re
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(payload, dict):
    raise SystemExit("latest stable Faryo release metadata is invalid")
tag = str(payload.get("tag_name") or "")
if payload.get("draft") or payload.get("prerelease") or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
    raise SystemExit("latest stable Faryo release metadata is invalid")
print(tag)
PY
)"
fi
[[ "$VERSION" == v* ]] || VERSION="v$VERSION"
[[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "invalid Faryo version: $VERSION" >&2; exit 2; }

ARCHIVE_NAME="faryo-$VERSION.tar.gz"
CHECKSUM_NAME="$ARCHIVE_NAME.sha256"
BASE_URL="https://github.com/$REPOSITORY/releases/download/$VERSION"
ARCHIVE="$TEMP_DIR/$ARCHIVE_NAME"
CHECKSUM="$TEMP_DIR/$CHECKSUM_NAME"
curl_release "$BASE_URL/$ARCHIVE_NAME" "$ARCHIVE"
curl_release "$BASE_URL/$CHECKSUM_NAME" "$CHECKSUM"
[[ "$(stat -c '%s' "$ARCHIVE")" -le 33554432 && "$(stat -c '%s' "$CHECKSUM")" -le 4096 ]] || {
  echo "Faryo release assets exceed their size limits" >&2
  exit 1
}

"$BOOTSTRAP_PYTHON" - "$CHECKSUM" "$ARCHIVE_NAME" <<'PY'
import re
import sys
from pathlib import Path

lines = [line.strip() for line in Path(sys.argv[1]).read_text(encoding="ascii").splitlines() if line.strip()]
pattern = rf"[0-9a-fA-F]{{64}}\s+\*?{re.escape(sys.argv[2])}"
if len(lines) != 1 or re.fullmatch(pattern, lines[0]) is None:
    raise SystemExit("Faryo checksum manifest is invalid")
PY
(cd "$TEMP_DIR" && sha256sum --check --strict "$CHECKSUM_NAME")

"$BOOTSTRAP_PYTHON" - "$ARCHIVE" "faryo-$VERSION" <<'PY'
import sys
import tarfile
from pathlib import PurePosixPath

total = 0
with tarfile.open(sys.argv[1], "r:*") as archive:
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or not path.parts or ".." in path.parts or path.parts[0] != sys.argv[2]:
            raise SystemExit("Faryo release archive has an unsafe path")
        if not (member.isdir() or member.isreg()):
            raise SystemExit("Faryo release archive has an unsupported entry")
        total += member.size
        if total > 134217728:
            raise SystemExit("Faryo release archive exceeds its extraction limit")
PY

SOURCE_DIR="$TEMP_DIR/source"
mkdir -m 700 "$SOURCE_DIR"
tar --extract --gzip --file "$ARCHIVE" --directory "$SOURCE_DIR" --no-same-owner --no-same-permissions
APP_ROOT="$SOURCE_DIR/faryo-$VERSION"
[[ -f "$APP_ROOT/pyproject.toml" && -f "$APP_ROOT/apps/owner/RELEASE" && -f "$APP_ROOT/src/faryo_cli/__init__.py" ]] || {
  echo "verified archive has an invalid Faryo source layout" >&2
  exit 1
}

INSTALL_ARGS=(--python "$BOOTSTRAP_PYTHON" --workspace "$WORKSPACE")
[[ "$MIGRATE_OWNER" == 1 ]] && INSTALL_ARGS+=(--migrate-owner)
PYTHONPATH="$APP_ROOT/src" "$BOOTSTRAP_PYTHON" -m faryo_cli install "${INSTALL_ARGS[@]}"

echo "Faryo $VERSION is installed."
echo "Run: $HOME/.local/bin/faryo doctor"
echo "Open: $HOME/.local/bin/faryo open"
if [[ -f "$HOME/.faryo/gateway/config/initial-password" ]]; then
  echo "Initial local login password: $HOME/.faryo/gateway/config/initial-password"
fi
