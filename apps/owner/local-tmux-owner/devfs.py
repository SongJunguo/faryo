#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
from http import HTTPStatus
from pathlib import Path
from typing import Any

MAX_OUTPUT_CHARS = 500_000
MAX_TIMEOUT_SECONDS = 900
TASK_COMMANDS = {
    "run_tests": {
        "package.json": ["npm", "test"],
        "pyproject.toml": ["python3", "-m", "pytest"],
    },
    "run_build": {
        "package.json": ["npm", "run", "build"],
        "pyproject.toml": ["python3", "-m", "build"],
    },
    "run_lint": {
        "package.json": ["npm", "run", "lint"],
        "pyproject.toml": ["python3", "-m", "ruff", "check", "."],
    },
}


def _default_cwd() -> Path:
    preferred = Path.home() / "brain" / "tools" / "faryo"
    return preferred if preferred.is_dir() else Path.home()


def _allowed_roots() -> list[Path]:
    raw = os.environ.get("FARYO_OWNER_ALLOWED_ROOTS", "").strip()
    values = raw.split(os.pathsep) if raw else [
        str(Path.home() / "brain"),
        str(Path.home() / ".faryo"),
        "/opt/faryo",
    ]
    roots: list[Path] = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        try:
            roots.append(Path(value).expanduser().resolve())
        except OSError:
            continue
    return roots


class ActionError(Exception):
    def __init__(self, code: str, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.code = code
        self.status = status


def _under_allowed_root(path: Path) -> bool:
    return any(path == root or root in path.parents for root in _allowed_roots())


def _path(value: Any, field: str = "path", *, base: Path | None = None) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ActionError("INVALID_ARGUMENT", f"{field} is required")
    raw = Path(text).expanduser()
    candidate = raw if raw.is_absolute() else (base or _default_cwd()) / raw
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise ActionError("INVALID_PATH", f"invalid {field}: {exc}") from exc
    if not _under_allowed_root(resolved):
        raise ActionError("PATH_OUTSIDE_ALLOWED_ROOTS", f"{field} is outside allowed roots", HTTPStatus.FORBIDDEN)
    return resolved


def _entry(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "type": "dir" if path.is_dir() else "file" if path.is_file() else "other",
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }


def _search_files(root: Path, glob: str):
    if root.is_file():
        if not glob or root.match(glob):
            yield root
        return
    if not root.is_dir():
        raise ActionError("INVALID_PATH", f"not a file or directory: {root}")
    for candidate in sorted(root.rglob("*"), key=lambda item: str(item).lower()):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root)
        if glob and not relative.match(glob):
            continue
        yield candidate


def _search_text(payload: dict[str, Any], encoding: str) -> dict[str, Any]:
    root = _path(payload.get("path"))
    query = str(payload.get("query") or "")
    if not query:
        raise ActionError("INVALID_ARGUMENT", "query is required")
    glob = str(payload.get("glob") or "").strip()
    max_results = max(1, min(int(payload.get("max_results") or 100), 1000))
    matches: list[dict[str, Any]] = []
    skipped_files = 0
    truncated = False
    for path in _search_files(root, glob):
        try:
            with path.open("r", encoding=encoding, errors="replace") as stream:
                for line_number, line in enumerate(stream, start=1):
                    column = line.find(query)
                    if column < 0:
                        continue
                    matches.append({
                        "path": str(path),
                        "line": line_number,
                        "column": column + 1,
                        "text": line.rstrip("\r\n"),
                    })
                    if len(matches) >= max_results:
                        truncated = True
                        break
        except (OSError, UnicodeError):
            skipped_files += 1
        if truncated:
            break
    return {
        "ok": True,
        "action": "search_text",
        "path": str(root),
        "query": query,
        "glob": glob or None,
        "matches": matches,
        "match_count": len(matches),
        "max_results": max_results,
        "truncated": truncated,
        "skipped_files": skipped_files,
    }


def _error(exc: Exception) -> tuple[dict[str, Any], int]:
    if isinstance(exc, ActionError):
        return {"ok": False, "code": exc.code, "error": str(exc)}, int(exc.status)
    if isinstance(exc, FileNotFoundError):
        return {"ok": False, "code": "PATH_NOT_FOUND", "error": str(exc)}, int(HTTPStatus.NOT_FOUND)
    if isinstance(exc, PermissionError):
        return {"ok": False, "code": "PERMISSION_DENIED", "error": str(exc)}, int(HTTPStatus.FORBIDDEN)
    if isinstance(exc, NotADirectoryError):
        return {"ok": False, "code": "NOT_A_DIRECTORY", "error": str(exc)}, int(HTTPStatus.BAD_REQUEST)
    if isinstance(exc, IsADirectoryError):
        return {"ok": False, "code": "NOT_A_FILE", "error": str(exc)}, int(HTTPStatus.BAD_REQUEST)
    return {"ok": False, "code": "INTERNAL_ERROR", "error": str(exc)}, int(HTTPStatus.INTERNAL_SERVER_ERROR)


def handle_devfs(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    try:
        action = str(payload.get("action") or "").strip()
        encoding = str(payload.get("encoding") or "utf-8")
        if action == "list_dir":
            path = _path(payload.get("path"))
            if not path.is_dir():
                raise ActionError("NOT_A_DIRECTORY", f"not a directory: {path}")
            entries = [_entry(p) for p in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))]
            return {"ok": True, "action": action, "path": str(path), "entries": entries}, 200
        if action == "read_file":
            path = _path(payload.get("path"))
            return {"ok": True, "action": action, "path": str(path), "content": path.read_text(encoding=encoding)}, 200
        if action == "search_text":
            return _search_text(payload, encoding), 200
        if action in {"git_status", "git_diff"}:
            cwd = _path(payload.get("cwd") or payload.get("path") or str(_default_cwd()), "cwd")
            if not cwd.is_dir():
                raise ActionError("NOT_A_DIRECTORY", f"cwd is not a directory: {cwd}")
            command = ["git", "status", "--short", "--branch"] if action == "git_status" else ["git", "diff", "--no-ext-diff"]
            if action == "git_diff" and bool(payload.get("staged", False)):
                command.append("--cached")
            completed = subprocess.run(command, cwd=str(cwd), text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
            return {"ok": completed.returncode == 0, "action": action, "cwd": str(cwd), "exit_code": completed.returncode, "stdout": completed.stdout[-MAX_OUTPUT_CHARS:], "stderr": completed.stderr[-MAX_OUTPUT_CHARS:]}, 200
        if action == "write_file":
            path = _path(payload.get("path"))
            path.parent.mkdir(parents=True, exist_ok=True)
            content = str(payload.get("content") or "")
            path.write_text(content, encoding=encoding)
            return {"ok": True, "action": action, "path": str(path), "bytes": len(content.encode(encoding))}, 200
        if action == "replace_text":
            path = _path(payload.get("path"))
            old_text = str(payload.get("old_text") or "")
            new_text = str(payload.get("new_text") or "")
            if not old_text:
                raise ActionError("INVALID_ARGUMENT", "old_text is required")
            content = path.read_text(encoding=encoding)
            count = content.count(old_text)
            if count == 0:
                raise ActionError("TEXT_NOT_FOUND", "old_text not found", HTTPStatus.NOT_FOUND)
            expected = payload.get("expected_count")
            if expected is not None and int(expected) != count:
                raise ActionError("COUNT_MISMATCH", f"expected_count={expected}, actual_count={count}", HTTPStatus.CONFLICT)
            path.write_text(content.replace(old_text, new_text), encoding=encoding)
            return {"ok": True, "action": action, "path": str(path), "replacements": count}, 200
        if action == "mkdir":
            path = _path(payload.get("path"))
            path.mkdir(parents=True, exist_ok=bool(payload.get("exist_ok", True)))
            return {"ok": True, "action": action, "path": str(path)}, 200
        if action == "move_path":
            source = _path(payload.get("source"), "source")
            destination = _path(payload.get("destination"), "destination")
            destination.parent.mkdir(parents=True, exist_ok=True)
            moved = shutil.move(str(source), str(destination))
            return {"ok": True, "action": action, "source": str(source), "destination": str(moved)}, 200
        if action == "delete_path":
            path = _path(payload.get("path"))
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path) if bool(payload.get("recursive", False)) else path.rmdir()
            else:
                path.unlink()
            return {"ok": True, "action": action, "path": str(path)}, 200
        raise ActionError("UNSUPPORTED_ACTION", f"unsupported action: {action}")
    except Exception as exc:
        return _error(exc)


def handle_task(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    try:
        action = str(payload.get("action") or "").strip()
        commands = TASK_COMMANDS.get(action)
        if not commands:
            raise ActionError("UNSUPPORTED_ACTION", f"unsupported task: {action}")
        cwd = _path(payload.get("cwd") or str(_default_cwd()), "cwd")
        if not cwd.is_dir():
            raise ActionError("NOT_A_DIRECTORY", f"cwd is not a directory: {cwd}")
        command = next((value for marker, value in commands.items() if (cwd / marker).is_file()), None)
        if not command:
            raise ActionError("TASK_NOT_CONFIGURED", f"no supported project marker for {action} in {cwd}")
        timeout_seconds = max(1, min(int(payload.get("timeout_seconds") or 300), MAX_TIMEOUT_SECONDS))
        completed = subprocess.run(command, cwd=str(cwd), text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_seconds, check=False)
        return {"ok": completed.returncode == 0, "action": action, "command": command, "cwd": str(cwd), "exit_code": completed.returncode, "stdout": completed.stdout[-MAX_OUTPUT_CHARS:], "stderr": completed.stderr[-MAX_OUTPUT_CHARS:], "timed_out": False}, 200
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "action": str(payload.get("action") or ""), "exit_code": None, "stdout": exc.stdout or "", "stderr": exc.stderr or "", "timed_out": True, "code": "TASK_TIMEOUT", "error": "task timed out"}, int(HTTPStatus.REQUEST_TIMEOUT)
    except Exception as exc:
        return _error(exc)
