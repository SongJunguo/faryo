#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env
export FARYO_PROJECT_WORKBENCH_SYNC_URL="${FARYO_PROJECT_WORKBENCH_SYNC_URL:-}"
export FARYO_PROJECT_WORKBENCH_SYNC_OWNER_LABEL="${FARYO_PROJECT_WORKBENCH_SYNC_OWNER_LABEL:-}"
export FARYO_PROJECT_WORKBENCH_ROOTS="${FARYO_PROJECT_WORKBENCH_ROOTS:-}"
export FARYO_OWNER_TOKEN="${FARYO_OWNER_TOKEN:-}"
export FARYO_OWNER_LABEL="${FARYO_OWNER_LABEL:-}"

python3 - "$@" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing {name}")
    return value


def configured_paths() -> list[Path]:
    raw_args = [arg for arg in sys.argv[1:] if arg.strip()]
    if raw_args:
        return [Path(arg).expanduser() for arg in raw_args]

    paths = []
    raw_roots = os.environ.get("FARYO_PROJECT_WORKBENCH_ROOTS", "")
    for chunk in raw_roots.replace("\n", os.pathsep).split(os.pathsep):
        item = chunk.strip()
        if item:
            paths.append(Path(item).expanduser())

    if not paths:
        raise SystemExit("pass project roots or set FARYO_PROJECT_WORKBENCH_ROOTS")
    return paths


def workbench_file(path: Path) -> Path:
    if path.is_file():
        return path
    return path / "00-system" / "workbench.json"


def compact_path(path: Path) -> str:
    resolved = path.resolve()
    for root in (Path.home() / "brain", Path.home()):
        try:
            return resolved.relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return resolved.as_posix()


def read_project(path: Path) -> dict:
    file_path = workbench_file(path)
    if not file_path.is_file():
        raise SystemExit(f"missing workbench.json: {file_path}")
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON: {file_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"workbench must be a JSON object: {file_path}")
    row = dict(payload)
    row.setdefault("path", compact_path(file_path))
    row.setdefault("workbench_path", str(file_path.resolve()))
    return row


def main() -> None:
    url = env_required("FARYO_PROJECT_WORKBENCH_SYNC_URL")
    owner_token = os.environ.get("FARYO_OWNER_TOKEN", "").strip()
    owner_label = os.environ.get("FARYO_PROJECT_WORKBENCH_SYNC_OWNER_LABEL", "").strip() or os.environ.get("FARYO_OWNER_LABEL", "").strip()
    if not (owner_token and owner_label):
        raise SystemExit("missing FARYO_OWNER_TOKEN/FARYO_OWNER_LABEL")
    projects = [read_project(path) for path in configured_paths()]
    body = json.dumps({"projects": projects}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Owner-Token": owner_token,
        "X-Faryo-Owner-Label": owner_label,
    }
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"sync failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"sync failed: {exc.reason}") from exc

    try:
        result = json.loads(response_body)
    except json.JSONDecodeError:
        raise SystemExit(f"sync returned invalid JSON: {response_body}")
    if not result.get("ok"):
        raise SystemExit(f"sync failed: {result.get('error') or response_body}")
    print(f"synced {len(projects)} project workbench row(s)")


if __name__ == "__main__":
    main()
PY
