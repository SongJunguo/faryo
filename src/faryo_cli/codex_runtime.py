"""Dynamic Codex CLI discovery for non-interactive Faryo services."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
from typing import Mapping


VERSION_RE = re.compile(r"^v?(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?")
TRUE_VALUES = {"1", "true", "yes", "on"}
PRIVATE_RUNTIME_PREFIXES = ("FARYO_", "GATEWAY_")


def _executable(path: Path | str | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path).expanduser()
    return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None


def _version_key(path: Path) -> tuple[int, int, int]:
    match = VERSION_RE.match(path.name)
    if not match:
        return (-1, -1, -1)
    return tuple(int(match.group(name) or 0) for name in ("major", "minor", "patch"))


def _nvm_roots(home: Path, values: Mapping[str, str]) -> list[Path]:
    roots: list[Path] = []
    for raw in (values.get("NVM_DIR"), str(home / ".nvm")):
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path not in roots and (path / "versions/node").is_dir():
            roots.append(path)
    return roots


def _nvm_versions(root: Path) -> list[Path]:
    versions = [path for path in (root / "versions/node").iterdir() if path.is_dir()]
    return sorted(versions, key=_version_key, reverse=True)


def _read_nvm_alias(root: Path, value: str, seen: set[str] | None = None) -> str:
    current = value.strip()
    visited = set() if seen is None else seen
    if not current or current in visited:
        return current
    visited.add(current)
    alias_path = root / "alias" / current
    try:
        target = alias_path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return current
    return _read_nvm_alias(root, target, visited)


def _matching_nvm_version(versions: list[Path], selector: str) -> Path | None:
    normalized = selector.strip().lower()
    if normalized in {"", "node", "stable", "unstable", "lts/*"}:
        return versions[0] if versions else None
    match = VERSION_RE.match(normalized)
    if not match:
        return versions[0] if versions else None
    parts = [int(match.group("major"))]
    if match.group("minor") is not None:
        parts.append(int(match.group("minor")))
    if match.group("patch") is not None:
        parts.append(int(match.group("patch")))
    return next(
        (
            version
            for version in versions
            if list(_version_key(version)[: len(parts)]) == parts
        ),
        None,
    )


def _nvm_default_codex(root: Path) -> Path | None:
    try:
        selector = (root / "alias/default").read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return None
    resolved = _read_nvm_alias(root, selector)
    version = _matching_nvm_version(_nvm_versions(root), resolved)
    return _executable(version / "bin/codex") if version else None


def _highest_nvm_codex(root: Path) -> Path | None:
    for version in _nvm_versions(root):
        if candidate := _executable(version / "bin/codex"):
            return candidate
    return None


def resolve_codex(
    configured: str = "",
    home: Path | None = None,
    values: Mapping[str, str] | None = None,
) -> str:
    """Resolve Codex afresh; legacy generated paths are hints, not pins."""

    environment = dict(os.environ if values is None else values)
    selected_home = (home or Path(environment.get("HOME") or Path.home())).expanduser()
    configured_path = (
        _executable(configured)
        if "/" in configured
        else _executable(shutil.which(configured, path=environment.get("PATH")))
    )
    pinned = str(environment.get("FARYO_CODEX_BIN_PINNED") or "").strip().lower() in TRUE_VALUES
    if pinned:
        return str(configured_path) if configured_path else ""

    nvm_roots = _nvm_roots(selected_home, environment)
    for root in nvm_roots:
        if candidate := _nvm_default_codex(root):
            return str(candidate)

    if candidate := _executable(shutil.which("codex", path=environment.get("PATH"))):
        return str(candidate)
    for candidate in (
        selected_home / ".local/share/npm-global/bin/codex",
        selected_home / ".local/bin/codex",
        Path("/usr/local/bin/codex"),
    ):
        if selected := _executable(candidate):
            return str(selected)
    for root in nvm_roots:
        if candidate := _highest_nvm_codex(root):
            return str(candidate)
    return str(configured_path) if configured_path else ""


def codex_argv(executable: str, *args: str) -> list[str]:
    """Freeze one discovered launcher to its matching runtime for one exec."""

    path = Path(executable).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return [executable, *args]
    marker = "/lib/node_modules/"
    value = str(resolved)
    if marker in value:
        node = Path(value.split(marker, 1)[0]) / "bin/node"
        if node.is_file() and os.access(node, os.X_OK):
            return [str(node), value, *args]
    return [str(path), *args]


def sanitized_agent_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Remove Faryo service internals before starting tmux or agent processes."""

    environment = dict(os.environ if base is None else base)
    roots = [
        Path(value).expanduser()
        for name in ("FARYO_INSTALL_ROOT", "FARYO_ROOT")
        if (value := str(environment.get(name) or "").strip())
    ]
    normalized_roots = [root.resolve(strict=False) for root in roots]
    for name in ("PWD", "OLDPWD"):
        value = str(environment.get(name) or "").strip()
        if not value:
            continue
        try:
            path = Path(value).expanduser().resolve(strict=False)
        except OSError:
            continue
        if any(path == root or root in path.parents for root in normalized_roots):
            environment.pop(name, None)
    python_path = str(environment.get("PYTHONPATH") or "")
    if python_path and roots:
        internal_paths = {
            str((root / "src").resolve(strict=False)) for root in roots
        }
        kept = []
        for entry in python_path.split(os.pathsep):
            if not entry:
                continue
            try:
                normalized = str(Path(entry).expanduser().resolve(strict=False))
            except OSError:
                normalized = entry
            if normalized not in internal_paths:
                kept.append(entry)
        if kept:
            environment["PYTHONPATH"] = os.pathsep.join(kept)
        else:
            environment.pop("PYTHONPATH", None)
    for name in tuple(environment):
        if name.startswith(PRIVATE_RUNTIME_PREFIXES):
            environment.pop(name, None)
    return environment


def codex_environment(argv: list[str], base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Expose matching Node/npm to Codex without leaking Faryo internals."""

    environment = sanitized_agent_environment(base)
    if not argv:
        return environment
    bin_dir = Path(argv[0]).expanduser().parent
    current = environment.get("PATH") or ""
    parts = [part for part in current.split(os.pathsep) if part]
    if str(bin_dir) not in parts:
        environment["PATH"] = os.pathsep.join([str(bin_dir), *parts])
    return environment
