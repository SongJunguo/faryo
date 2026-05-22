#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env
export FARYO_PROJECT_WORKBENCH_SYNC_URL="${FARYO_PROJECT_WORKBENCH_SYNC_URL:-}"
export FARYO_PROJECT_WORKBENCH_SYNC_OWNER_LABEL="${FARYO_PROJECT_WORKBENCH_SYNC_OWNER_LABEL:-}"
export FARYO_PROJECT_WORKBENCH_ROOTS="${FARYO_PROJECT_WORKBENCH_ROOTS:-}"
export FARYO_PROJECT_WORKBENCH_SYNC_MODE="${FARYO_PROJECT_WORKBENCH_SYNC_MODE:-merge}"
export FARYO_OWNER_TOKEN="${FARYO_OWNER_TOKEN:-}"
export FARYO_OWNER_LABEL="${FARYO_OWNER_LABEL:-}"

python3 - "$@" <<'PY_SYNC'
import json, os, sys, urllib.error, urllib.request
from pathlib import Path

def need(name):
    value = os.environ.get(name, '').strip()
    if not value: raise SystemExit(f'missing {name}')
    return value

def project_args():
    args = [Path(arg).expanduser() for arg in sys.argv[1:] if arg.strip()]
    if args: return args
    roots = os.environ.get('FARYO_PROJECT_WORKBENCH_ROOTS', '').replace('\n', os.pathsep)
    args = [Path(item.strip()).expanduser() for item in roots.split(os.pathsep) if item.strip()]
    if not args: raise SystemExit('pass project roots or set FARYO_PROJECT_WORKBENCH_ROOTS')
    return args

def workbench(path):
    return path if path.is_file() else path / '00-system' / 'workbench.json'

def compact(path):
    resolved = path.resolve()
    for root in (Path.home() / 'brain', Path.home()):
        try: return resolved.relative_to(root.resolve()).as_posix()
        except ValueError: pass
    return resolved.as_posix()

def read_project(path):
    file_path = workbench(path)
    if not file_path.is_file(): raise SystemExit(f'missing workbench.json: {file_path}')
    try: payload = json.loads(file_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc: raise SystemExit(f'invalid JSON: {file_path}: {exc}') from exc
    if not isinstance(payload, dict): raise SystemExit(f'workbench must be a JSON object: {file_path}')
    row = dict(payload); row.setdefault('path', compact(file_path)); row.setdefault('workbench_path', str(file_path.resolve()))
    return row

def post(url, token, label, projects):
    body = json.dumps({'mode': os.environ.get('FARYO_PROJECT_WORKBENCH_SYNC_MODE', 'merge') or 'merge', 'projects': projects}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST', headers={'Content-Type': 'application/json; charset=utf-8', 'X-Owner-Token': token, 'X-Faryo-Owner-Label': label})
    try:
        with urllib.request.urlopen(req, timeout=20) as response: raw = response.read().decode('utf-8')
    except urllib.error.HTTPError as exc: raise SystemExit(f"sync failed: HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
    except urllib.error.URLError as exc: raise SystemExit(f'sync failed: {exc.reason}') from exc
    try: result = json.loads(raw)
    except json.JSONDecodeError: raise SystemExit(f'sync returned invalid JSON: {raw}')
    if not result.get('ok'): raise SystemExit(f"sync failed: {result.get('error') or raw}")

def main():
    token = need('FARYO_OWNER_TOKEN')
    label = os.environ.get('FARYO_PROJECT_WORKBENCH_SYNC_OWNER_LABEL', '').strip() or need('FARYO_OWNER_LABEL')
    projects = [read_project(path) for path in project_args()]
    post(need('FARYO_PROJECT_WORKBENCH_SYNC_URL'), token, label, projects)
    print(f'synced {len(projects)} project workbench row(s)')

if __name__ == '__main__': main()
PY_SYNC
