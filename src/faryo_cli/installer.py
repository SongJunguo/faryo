"""Atomic user-service installation for the unified Faryo CLI."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Iterable

from faryo_cli.diagnostics import Layout
from faryo_cli.operations import OperationError, systemctl


UNIT_NAMES = {
    "owner": "faryo-owner.service",
    "gateway": "faryo-gateway.service",
}
LEGACY_UNIT_NAMES = (
    "faryo-owner-keepalive.service",
    "faryo-owner-keepalive.timer",
)


def unit_escape(value: str) -> str:
    if any(character in value for character in ("\n", "\r", "\x00")):
        raise OperationError("service path contains control characters")
    return value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')


def unit_path_escape(value: str) -> str:
    if not value.startswith("/"):
        raise OperationError("service path must be absolute")
    if any(character in value for character in ("\n", "\r", "\x00")):
        raise OperationError("service path contains control characters")
    return value.replace("%", "%%").replace("\\", "\\x5c").replace(" ", "\\x20").replace("\t", "\\x09")


def rendered_unit(component: str, layout: Layout, python: str) -> str:
    if component not in UNIT_NAMES:
        raise OperationError("unsupported service component")
    if layout.source_root is None:
        raise OperationError("Faryo application files are unavailable")
    template = layout.source_root / "deploy/user-systemd" / UNIT_NAMES[component]
    try:
        source = template.read_text(encoding="utf-8")
    except OSError as exc:
        raise OperationError("service template is unavailable") from exc
    replacements = {
        "@FARYO_ROOT_PATH@": unit_path_escape(str(layout.source_root)),
        "@FARYO_ROOT@": unit_escape(str(layout.source_root)),
        "@FARYO_HOME@": unit_escape(str(layout.faryo_home)),
        "@FARYO_PYTHON@": unit_escape(os.path.abspath(python)),
    }
    for marker, value in replacements.items():
        source = source.replace(marker, value)
    if "@FARYO_" in source:
        raise OperationError("service template has unresolved placeholders")
    return source


def atomic_write(path: Path, body: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(mode)
        temp.replace(path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def unit_directory(layout: Layout, values: dict[str, str] | None = None) -> Path:
    env = os.environ if values is None else values
    configured = env.get("XDG_CONFIG_HOME")
    return (Path(configured).expanduser() if configured else layout.home / ".config") / "systemd/user"


def backup_unit(path: Path, layout: Layout) -> None:
    if not path.is_file():
        return
    backup = layout.home / ".local/share/faryo/state/unit-backups" / f"{path.name}.previous"
    try:
        body = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OperationError("existing service unit is unreadable") from exc
    atomic_write(backup, body, 0o600)


def install_user_units(
    layout: Layout | None = None,
    *,
    components: Iterable[str] = ("owner", "gateway"),
    python: str,
    reload: bool = True,
) -> list[str]:
    selected = layout or Layout.from_environment()
    target_dir = unit_directory(selected)
    installed: list[str] = []
    for component in components:
        name = UNIT_NAMES.get(component)
        if not name:
            raise OperationError("unsupported service component")
        target = target_dir / name
        body = rendered_unit(component, selected, python)
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if current != body:
            backup_unit(target, selected)
            atomic_write(target, body, 0o644)
        installed.append(name)
    if reload:
        systemctl("daemon-reload")
    return installed


def install_services(
    layout: Layout | None = None,
    *,
    python: str,
    dry_run: bool = False,
    no_start: bool = False,
    migrate_owner: bool = False,
) -> str:
    from faryo_cli import migration
    from faryo_cli.operations import control_service, wait_for_health
    from faryo_cli.runtime import gateway_process, owner_process

    selected = layout or Layout.from_environment()
    # Validate application/config/loopback contracts before writing units.
    owner_process(selected)
    gateway_process(selected)
    for component in UNIT_NAMES:
        rendered_unit(component, selected, python)
    legacy = migration.legacy_owner_exists()
    if dry_run:
        return "dry-run"
    if legacy and not migrate_owner and not no_start:
        raise OperationError("legacy Owner migration requires --migrate-owner or --no-start")

    target_dir = unit_directory(selected)
    previous = {
        component: (target_dir / name).read_text(encoding="utf-8") if (target_dir / name).is_file() else None
        for component, name in UNIT_NAMES.items()
    }
    install_user_units(selected, python=python)
    if no_start:
        return "units-installed"
    try:
        if legacy:
            migration.migrate_owner(selected)
        else:
            control_service("faryo-owner.service", "restart")
        systemctl("enable", "faryo-owner.service")
        systemctl("enable", "faryo-gateway.service")
        control_service("faryo-gateway.service", "restart")
        wait_for_health(selected)
    except Exception as exc:
        try:
            systemctl("disable", "--now", "faryo-owner.service", check=False)
            for component, name in UNIT_NAMES.items():
                target = target_dir / name
                body = previous[component]
                if body is None:
                    target.unlink(missing_ok=True)
                else:
                    atomic_write(target, body, 0o644)
            systemctl("daemon-reload")
            if legacy and not migration.legacy_owner_exists():
                migration.restore_legacy(selected)
            if not legacy and previous["owner"] is not None:
                systemctl("restart", "faryo-owner.service", check=False)
            if previous["gateway"] is not None:
                systemctl("restart", "faryo-gateway.service", check=False)
        except Exception as rollback_exc:
            raise OperationError("service install and rollback both failed") from rollback_exc
        if isinstance(exc, OperationError):
            raise
        raise OperationError("service install failed") from exc
    return "installed"


def uninstall_user_services(layout: Layout | None = None) -> list[str]:
    from faryo_cli import migration

    selected = layout or Layout.from_environment()
    names = [*UNIT_NAMES.values(), *LEGACY_UNIT_NAMES]
    systemctl("disable", "--now", *names, check=False)
    if migration.legacy_owner_exists():
        migration.stop_legacy_owner()
    target_dir = unit_directory(selected)
    removed: list[str] = []
    for name in names:
        target = target_dir / name
        if target.is_symlink() or target.is_file():
            target.unlink()
            removed.append(name)
    systemctl("daemon-reload")
    systemctl("reset-failed", *names, check=False)
    return removed
