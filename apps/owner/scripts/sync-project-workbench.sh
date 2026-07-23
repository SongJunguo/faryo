#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_lib.sh
source "$SCRIPT_DIR/_lib.sh"
load_env
export FARYO_PROJECT_WORKBENCH_SYNC_URL="${FARYO_PROJECT_WORKBENCH_SYNC_URL:-}"
export FARYO_PROJECT_WORKBENCH_SYNC_OWNER_LABEL="${FARYO_PROJECT_WORKBENCH_SYNC_OWNER_LABEL:-}"
export FARYO_PROJECT_WORKBENCH_ROOTS="${FARYO_PROJECT_WORKBENCH_ROOTS:-}"
export FARYO_PROJECT_WORKBENCH_SYNC_MODE="${FARYO_PROJECT_WORKBENCH_SYNC_MODE:-}"
export FARYO_OWNER_TOKEN="${FARYO_OWNER_TOKEN:-}"
export FARYO_OWNER_LABEL="${FARYO_OWNER_LABEL:-}"
export FARYO_OWNER_ROOT

python3 - "$@" <<'PY_SYNC'
import json, os, sys, urllib.error, urllib.request
from pathlib import Path

shared_dir = Path(os.environ["FARYO_OWNER_ROOT"]).parent / "shared"
if str(shared_dir) not in sys.path:
    sys.path.insert(0, str(shared_dir))
import pd_state

def need(name):
    value = os.environ.get(name, '').strip()
    if not value: raise SystemExit(f'missing {name}')
    return value

def project_sources():
    args = [Path(arg).expanduser() for arg in sys.argv[1:] if arg.strip()]
    if args: return args, True
    roots = os.environ.get('FARYO_PROJECT_WORKBENCH_ROOTS', '').replace('\n', os.pathsep)
    args = [Path(item.strip()).expanduser() for item in roots.split(os.pathsep) if item.strip()]
    if not args: raise SystemExit('pass project roots or set FARYO_PROJECT_WORKBENCH_ROOTS')
    return args, False

def expand_source(path):
    if path.is_file() or workbench(path).is_file():
        return [path]
    projects = sorted(path.glob('*/00-system/workbench.json')) if path.is_dir() else []
    if projects:
        return [item.parent.parent for item in projects]
    return [path]

def project_args():
    sources, explicit = project_sources()
    paths = []
    for source in sources:
        for path in expand_source(source):
            resolved = path.resolve()
            if resolved not in paths:
                paths.append(resolved)
    return paths, explicit

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
    definition_path = file_path.parent / 'conops.md'
    if definition_path.is_file():
        row['definition'] = pd_state.parse_project_definition(definition_path.read_text(encoding='utf-8'))
    return row

def sync_mode(explicit):
    return os.environ.get('FARYO_PROJECT_WORKBENCH_SYNC_MODE', '').strip() or ('merge' if explicit else 'replace_owner')

def post(url, token, label, projects, mode):
    body = json.dumps({'mode': mode, 'projects': projects}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
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
    paths, explicit = project_args()
    projects = [read_project(path) for path in paths]
    post(need('FARYO_PROJECT_WORKBENCH_SYNC_URL'), token, label, projects, sync_mode(explicit))
    print(f'synced {len(projects)} project workbench row(s)')

if __name__ == '__main__': main()
PY_SYNC
