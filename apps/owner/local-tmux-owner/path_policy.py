"""Workspace-scoped local-file and start-directory policy."""

from __future__ import annotations

import hashlib
import hmac
from http import HTTPStatus
import os
from pathlib import Path
from typing import Iterable


class PathPolicyError(Exception):
    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status = status


def inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def clean_local_path(value: str | None) -> str:
    text = (value or "").strip()
    if (text.startswith("<") and text.endswith(">")) or (text[:1] in {"'", '"', "`"} and text[-1:] == text[:1]):
        text = text[1:-1].strip()
    if not text or "\x00" in text:
        raise PathPolicyError("missing file path")
    return text


def resolve_local_file(path_value: str | None, bases: Iterable[str | Path | None], suffixes: set[str]) -> Path:
    raw = Path(clean_local_path(path_value)).expanduser()
    candidates = [raw] if raw.is_absolute() else [Path(base).expanduser() / raw for base in bases if base]
    for candidate in candidates:
        try:
            path = candidate.resolve()
        except OSError:
            continue
        if path.is_file() and path.suffix.lower() in suffixes:
            return path
    raise PathPolicyError("file not found", HTTPStatus.NOT_FOUND)


def start_directory_roots(values: Iterable[str], workspace_root: str | None, *, home: Path | None = None) -> list[Path]:
    candidates = [value for value in values if str(value).strip()]
    if workspace_root:
        candidates.append(workspace_root)
    if not candidates:
        candidates.append(str(home or Path.home()))
    roots: list[Path] = []
    for value in candidates:
        try:
            root = Path(os.path.expandvars(str(value))).expanduser().resolve()
        except OSError:
            continue
        if root.is_dir() and root not in roots:
            roots.append(root)
    return roots


def resolve_start_directory(path_value: str | None, roots: list[Path]) -> Path:
    if not roots:
        raise PathPolicyError("no start-directory roots are configured", HTTPStatus.FORBIDDEN)
    raw = str(path_value or "").strip()
    try:
        path = (Path(os.path.expandvars(raw)).expanduser() if raw else roots[0]).resolve()
    except OSError as exc:
        raise PathPolicyError("working directory is unavailable", HTTPStatus.NOT_FOUND) from exc
    if not any(inside(path, root) for root in roots):
        raise PathPolicyError("working directory is outside the configured roots", HTTPStatus.FORBIDDEN)
    if not path.is_dir():
        raise PathPolicyError("working directory is unavailable", HTTPStatus.NOT_FOUND)
    return path


def list_start_directories(path: Path, roots: list[Path], limit: int) -> tuple[Path | None, list[Path], bool]:
    parent = path.parent if path.parent != path and any(inside(path.parent, root) for root in roots) else None
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name.casefold())
    except OSError as exc:
        raise PathPolicyError("working directory cannot be listed", HTTPStatus.FORBIDDEN) from exc
    directories: list[Path] = []
    truncated = False
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            resolved = child.resolve()
        except OSError:
            continue
        if not resolved.is_dir() or not any(inside(resolved, root) for root in roots):
            continue
        directories.append(resolved)
        if len(directories) >= limit:
            truncated = True
            break
    return parent, directories, truncated


def directory_selection_token(token: str, path: Path) -> str:
    return hmac.new(token.encode("utf-8"), f"cwd:{path}".encode("utf-8"), hashlib.sha256).hexdigest()
