"""Rollback and uninstall operations for versioned Faryo installations."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import shutil

from faryo_cli.application import (
    ProgramLayout,
    VERSION_RE,
    activate_version,
    atomic_write,
    prepared_version_is_healthy,
    restore_activation,
    symlink_target,
    venv_python,
)
from faryo_cli.diagnostics import Layout
from faryo_cli.operations import OperationError


def snapshot_text_files(paths: tuple[Path, ...]) -> dict[Path, str | None]:
    snapshot: dict[Path, str | None] = {}
    for path in paths:
        try:
            snapshot[path] = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            snapshot[path] = None
        except OSError as exc:
            raise OperationError("private runtime config is unreadable") from exc
    return snapshot


def restore_text_files(snapshot: dict[Path, str | None]) -> None:
    for path, body in snapshot.items():
        if body is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, body, 0o600)


def restore_previous_marker(path: Path, body: str | None) -> None:
    if body is None:
        path.unlink(missing_ok=True)
    else:
        atomic_write(path, body, 0o600)


def switch_version(version_dir: Path, layout: Layout | None = None) -> str:
    from faryo_cli.application import replace_env_value
    from faryo_cli.installer import install_services

    selected = layout or Layout.from_environment()
    program = ProgramLayout.from_layout(selected)
    target = version_dir.absolute()
    if target.parent != program.versions.absolute() or not prepared_version_is_healthy(target):
        raise OperationError("rollback target is not a healthy Faryo version")
    current = symlink_target(program.current)
    if current == target:
        raise OperationError("requested Faryo version is already active")
    marker = program.state / "previous-version"
    marker_body = marker.read_text(encoding="utf-8") if marker.is_file() else None
    configs = snapshot_text_files((selected.owner_env, selected.gateway_env))
    activate_version(target, selected)
    python = str(venv_python(target))
    version_layout = replace(selected, source_root=target / "app")
    try:
        for path in configs:
            replace_env_value(path, "FARYO_PYTHON", python)
        install_services(version_layout, python=python)
    except Exception:
        restore_text_files(configs)
        restore_activation(current, selected)
        restore_previous_marker(marker, marker_body)
        raise
    return target.name


def rollback_application(layout: Layout | None = None) -> str:
    selected = layout or Layout.from_environment()
    program = ProgramLayout.from_layout(selected)
    marker = program.state / "previous-version"
    try:
        name = marker.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise OperationError("no previous Faryo version is recorded") from exc
    if not VERSION_RE.fullmatch(name):
        raise OperationError("recorded previous Faryo version is invalid")
    return switch_version(program.versions / name, selected)


def bounded_user_tree(path: Path, home: Path, expected_name: str) -> Path:
    absolute = path.absolute()
    user_home = home.absolute()
    if absolute.name != expected_name or absolute == user_home or user_home not in absolute.parents:
        raise OperationError("refusing to remove an unbounded user path")
    if absolute.is_symlink():
        raise OperationError("refusing to recursively remove a symbolic link")
    return absolute


def unlink_cli(program: ProgramLayout) -> None:
    path = program.bin_path
    if not os.path.lexists(path):
        return
    if not path.is_symlink():
        raise OperationError("refusing to replace a non-symlink faryo command")
    target = path.resolve(strict=False)
    root = program.root.absolute()
    if target != root and root not in target.parents:
        raise OperationError("faryo command does not target the managed installation")
    path.unlink()


def uninstall_application(
    layout: Layout | None = None,
    *,
    purge_data: bool = False,
    confirmed: bool = False,
) -> str:
    from faryo_cli.installer import uninstall_user_services

    selected = layout or Layout.from_environment()
    if purge_data and not confirmed:
        raise OperationError("--purge-data requires --yes")
    program = ProgramLayout.from_layout(selected)
    program_root = bounded_user_tree(program.root, selected.home, "faryo")
    data_root = bounded_user_tree(selected.faryo_home, selected.home, ".faryo") if purge_data else None
    uninstall_user_services(selected)
    unlink_cli(program)
    if program_root.exists():
        shutil.rmtree(program_root)
    if data_root is not None and data_root.exists():
        shutil.rmtree(data_root)
    return "uninstalled and private data removed" if purge_data else "uninstalled; private data preserved"
