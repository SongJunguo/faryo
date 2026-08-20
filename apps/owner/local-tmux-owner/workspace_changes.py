"""Bounded, read-only Git status and diff collection for one workspace."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any


STATUS_MAX_BYTES = 2 * 1024 * 1024
DIFF_MAX_BYTES = 512 * 1024
FILE_LIMIT = 200
GIT_TIMEOUT_SECONDS = 4


class WorkspaceChangesError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_EXTERNAL_DIFF": "",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "LC_ALL": "C.UTF-8",
        "PAGER": "cat",
    })
    return env


def _run_git(cwd: Path, arguments: list[str], timeout: float = GIT_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            [
                "git",
                "-c", "color.ui=false",
                "-c", "core.fsmonitor=false",
                "-c", "core.hooksPath=/dev/null",
                "-c", "core.pager=cat",
                "-c", "diff.external=",
                "-C", str(cwd),
                *arguments,
            ],
            check=False,
            capture_output=True,
            env=_git_env(),
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceChangesError("git-unavailable") from exc


def _resolved_directory(value: str | Path) -> Path:
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorkspaceChangesError("workspace-unavailable") from exc
    if not path.is_dir():
        raise WorkspaceChangesError("workspace-unavailable")
    return path


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def resolve_git_root(cwd: str | Path, workspace_root: str | Path | None) -> tuple[Path, Path]:
    working = _resolved_directory(cwd)
    scope = _resolved_directory(workspace_root) if workspace_root else None
    if scope and not _inside(working, scope):
        raise WorkspaceChangesError("workspace-out-of-scope")
    result = _run_git(working, ["rev-parse", "--show-toplevel"])
    if result.returncode != 0 or not result.stdout.strip():
        raise WorkspaceChangesError("not-a-git-worktree")
    try:
        git_root = Path(result.stdout.decode("utf-8", errors="strict").strip()).resolve(strict=True)
    except (UnicodeError, OSError, RuntimeError) as exc:
        raise WorkspaceChangesError("not-a-git-worktree") from exc
    if not git_root.is_dir() or (scope and not _inside(git_root, scope)) or (not scope and git_root == Path.home().resolve()):
        raise WorkspaceChangesError("workspace-out-of-scope")
    return working, git_root


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _status_files(value: bytes) -> tuple[list[dict[str, Any]], bool]:
    if len(value) > STATUS_MAX_BYTES:
        value = value[:STATUS_MAX_BYTES]
        output_truncated = True
    else:
        output_truncated = False
    records = value.split(b"\0")
    files: list[dict[str, Any]] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 4:
            continue
        status = _decode(record[:2])
        path = _decode(record[3:])
        if status[0] in {"R", "C"} or status[1] in {"R", "C"}:
            if index < len(records) and records[index]:
                index += 1
        files.append({
            "path": path,
            "status": status,
            "staged": status[0] not in {" ", "?"},
            "unstaged": status[1] not in {" ", "?"},
            "untracked": status == "??",
        })
        if len(files) >= FILE_LIMIT:
            output_truncated = output_truncated or any(records[index:])
            break
    return files, output_truncated


def _bounded_text(value: bytes, limit: int = DIFF_MAX_BYTES) -> tuple[str, bool, int]:
    original = len(value)
    if original <= limit:
        return _decode(value), False, original
    clipped = value[:limit]
    return _decode(clipped) + "\n\n[Faryo truncated this diff]", True, original


def collect_workspace_changes(cwd: str | Path, workspace_root: str | Path | None = None) -> dict[str, Any]:
    _working, git_root = resolve_git_root(cwd, workspace_root)
    status_result = _run_git(git_root, ["status", "--porcelain=v1", "-z", "--untracked-files=normal"])
    if status_result.returncode != 0:
        raise WorkspaceChangesError("git-status-failed")
    files, status_truncated = _status_files(status_result.stdout)

    branch_result = _run_git(git_root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    branch = _decode(branch_result.stdout).strip() if branch_result.returncode == 0 else "detached"

    diff_arguments = [
        "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames",
        "--ignore-submodules=all", "--unified=3", "HEAD", "--",
    ]
    diff_result = _run_git(git_root, diff_arguments)
    if diff_result.returncode != 0:
        staged = _run_git(git_root, ["diff", "--cached", *diff_arguments[1:-2], "--"])
        unstaged = _run_git(git_root, ["diff", *diff_arguments[1:-2], "--"])
        if staged.returncode != 0 or unstaged.returncode != 0:
            raise WorkspaceChangesError("git-diff-failed")
        diff_bytes = staged.stdout + (b"\n" if staged.stdout and unstaged.stdout else b"") + unstaged.stdout
    else:
        diff_bytes = diff_result.stdout
    diff, diff_truncated, original_bytes = _bounded_text(diff_bytes)
    return {
        "schemaVersion": 1,
        "repository": {"name": git_root.name, "branch": branch or "detached"},
        "summary": {
            "files": len(files),
            "staged": sum(bool(item["staged"]) for item in files),
            "unstaged": sum(bool(item["unstaged"]) for item in files),
            "untracked": sum(bool(item["untracked"]) for item in files),
            "statusTruncated": status_truncated,
            "diffTruncated": diff_truncated,
            "diffBytes": original_bytes,
        },
        "files": files,
        "diff": diff,
    }
