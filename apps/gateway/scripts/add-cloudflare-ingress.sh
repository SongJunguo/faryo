#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: add-cloudflare-ingress.sh <hostname> [http://127.0.0.1:port]" >&2
}

FARYO_PUBLIC_HOSTNAME="${1:-}"
FARYO_INGRESS_SERVICE="${2:-http://127.0.0.1:8780}"
CLOUDFLARED_CONFIG="${CLOUDFLARED_CONFIG:-$HOME/.cloudflared/config.yml}"
FARYO_PYTHON="${FARYO_PYTHON:-python3}"

if [[ -z "$FARYO_PUBLIC_HOSTNAME" ]]; then
  usage
  exit 2
fi

export FARYO_PUBLIC_HOSTNAME FARYO_INGRESS_SERVICE CLOUDFLARED_CONFIG
candidate="$($FARYO_PYTHON - <<'PY'
import os
import re
import shutil
import tempfile
from pathlib import Path

hostname = os.environ["FARYO_PUBLIC_HOSTNAME"].strip().lower()
service = os.environ["FARYO_INGRESS_SERVICE"].strip()
config = Path(os.environ["CLOUDFLARED_CONFIG"]).expanduser()
if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", hostname) or ".." in hostname:
    raise ValueError("invalid hostname")
match = re.fullmatch(r"http://127\.0\.0\.1:([0-9]{1,5})", service)
if not match or not 1 <= int(match.group(1)) <= 65535:
    raise ValueError("service must be an http://127.0.0.1:<port> URL")
if not config.is_file():
    raise ValueError(f"cloudflared config not found: {config}")

lines = config.read_text(encoding="utf-8").splitlines()
host_pattern = re.compile(r"^\s*-\s*hostname:\s*['\"]?([^'\"\s]+)")
for index, line in enumerate(lines):
    found = host_pattern.match(line)
    if not found or found.group(1).lower() != hostname:
        continue
    following = "\n".join(lines[index:index + 3])
    if service not in following:
        raise ValueError("hostname already exists with a different service")
    print("UNCHANGED")
    raise SystemExit(0)

catchall = next(
    (index for index, line in enumerate(lines) if re.match(r"^\s*-\s*service:\s*http_status:", line)),
    None,
)
if catchall is None:
    raise ValueError("cloudflared ingress has no final http_status catch-all")
indent = re.match(r"^(\s*)", lines[catchall]).group(1)
lines[catchall:catchall] = [
    f"{indent}- hostname: {hostname}",
    f"{indent}  service: {service}",
]

handle, name = tempfile.mkstemp(prefix=".faryo-cloudflared-", suffix=".yml", dir=config.parent)
os.close(handle)
candidate = Path(name)
candidate.write_text("\n".join(lines) + "\n", encoding="utf-8")
candidate.chmod(0o600)
print(candidate)
PY
)"

if [[ "$candidate" == "UNCHANGED" ]]; then
  chmod 600 "$CLOUDFLARED_CONFIG"
  echo "cloudflared ingress already configured"
  exit 0
fi

cleanup() { unlink "$candidate" 2>/dev/null || true; }
trap cleanup EXIT
cloudflared tunnel --config "$candidate" ingress validate >/dev/null
backup="${CLOUDFLARED_CONFIG}.backup-$(date +%Y%m%dT%H%M%S%z)"
install -m 0600 "$CLOUDFLARED_CONFIG" "$backup"
install -m 0600 "$candidate" "$CLOUDFLARED_CONFIG"
printf 'updated cloudflared ingress; backup: %s\n' "$backup"
