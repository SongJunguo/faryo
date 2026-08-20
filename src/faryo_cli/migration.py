"""Rollback-backed transition from legacy Owner tmux supervision to systemd."""

from __future__ import annotations

import shutil
import subprocess
import time

from faryo_cli.diagnostics import Layout, http_status, run_command, service_state
from faryo_cli.operations import OperationError, endpoint, run_legacy_owner, systemctl, unit_exists


def tmux_geometry() -> dict[str, tuple[int, int]]:
    executable = shutil.which("tmux")
    if not executable:
        raise OperationError("tmux is unavailable")
    try:
        result = run_command(
            [executable, "list-panes", "-a", "-F", "#{session_name}\t#{window_width}\t#{window_height}"],
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperationError("tmux geometry is unavailable") from exc
    if result.returncode != 0:
        raise OperationError("tmux geometry is unavailable")
    geometry: dict[str, tuple[int, int]] = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] == "local-tmux-owner":
            continue
        try:
            geometry[parts[0]] = (int(parts[1]), int(parts[2]))
        except ValueError:
            continue
    return geometry


def legacy_owner_exists() -> bool:
    executable = shutil.which("tmux")
    if not executable:
        return False
    try:
        return run_command([executable, "has-session", "-t", "local-tmux-owner"], timeout=2).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def stop_legacy_owner() -> None:
    systemctl("stop", "faryo-owner-keepalive.timer", check=False)
    systemctl("stop", "faryo-owner-keepalive.service", check=False)
    executable = shutil.which("tmux")
    if executable and legacy_owner_exists():
        try:
            result = run_command([executable, "kill-session", "-t", "local-tmux-owner"], timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OperationError("legacy Owner did not stop") from exc
        if result.returncode != 0:
            raise OperationError("legacy Owner did not stop")


def wait_owner(layout: Layout, timeout: float = 12.0) -> None:
    host, port, path = endpoint(layout, "owner")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if http_status(host, port, path) == 200:
            return
        time.sleep(0.1)
    raise OperationError("direct Owner did not become healthy")


def verify_geometry(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> None:
    changed = [name for name, size in before.items() if after.get(name) != size]
    if changed:
        raise OperationError("agent tmux geometry changed during Owner migration")


def restore_legacy(layout: Layout) -> None:
    systemctl("stop", "faryo-owner.service", check=False)
    run_legacy_owner(layout, "start")
    wait_owner(layout)


def migrate_owner(layout: Layout | None = None) -> str:
    selected = layout or Layout.from_environment()
    if not unit_exists("faryo-owner.service"):
        raise OperationError("direct Owner service is not installed")
    before = tmux_geometry()
    had_legacy = legacy_owner_exists()
    if service_state("faryo-owner.service") == "active" and not had_legacy:
        verify_geometry(before, tmux_geometry())
        return "already-direct"
    stop_legacy_owner()
    try:
        systemctl("enable", "faryo-owner.service")
        systemctl("start", "faryo-owner.service")
        wait_owner(selected)
        verify_geometry(before, tmux_geometry())
    except Exception as exc:
        systemctl("disable", "--now", "faryo-owner.service", check=False)
        if had_legacy:
            try:
                restore_legacy(selected)
            except Exception as rollback_exc:
                raise OperationError("Owner migration and rollback both failed") from rollback_exc
        if isinstance(exc, OperationError):
            raise
        raise OperationError("Owner migration failed") from exc
    systemctl("disable", "faryo-owner-keepalive.timer", check=False)
    systemctl("stop", "faryo-owner-keepalive.service", check=False)
    return "migrated"
