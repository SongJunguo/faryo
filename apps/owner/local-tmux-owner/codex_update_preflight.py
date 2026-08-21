#!/usr/bin/env python3
"""Check/update Codex before a Faryo-managed TUI starts, then exec the TUI."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping

from faryo_cli import codex_runtime


SCHEMA_VERSION = 1
VERSION_RE = re.compile(r"\b(?P<version>\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)\b")
DEFAULT_CHECK_INTERVAL = 60 * 60
DEFAULT_FAILURE_RETRY = 5 * 60
CHECK_TIMEOUT = 15
UPDATE_TIMEOUT = 180
UPDATE_STATES = {"current", "updated", "failed"}
Runner = Callable[..., subprocess.CompletedProcess[str]]


def version_text(value: str) -> str:
    match = VERSION_RE.search(str(value or ""))
    return match.group("version") if match else ""


def version_key(value: str) -> tuple[int, int, int, int, str]:
    normalized = version_text(value)
    if not normalized:
        return (-1, -1, -1, -1, "")
    core, separator, suffix = normalized.partition("-")
    numbers = tuple(int(part) for part in core.split("."))
    return (*numbers, 1 if not separator else 0, suffix)


def command_prefix(launch_argv: list[str]) -> list[str]:
    if (
        len(launch_argv) >= 2
        and Path(launch_argv[0]).name.startswith("node")
        and Path(launch_argv[1]).suffix == ".js"
    ):
        return launch_argv[:2]
    return launch_argv[:1]


def read_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) and value.get("schemaVersion") == SCHEMA_VERSION else {}


def write_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def run(
    runner: Runner,
    argv: list[str],
    *,
    environment: Mapping[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return runner(
        argv,
        env=dict(environment),
        timeout=timeout,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def installed_version(
    prefix: list[str],
    environment: Mapping[str, str],
    runner: Runner,
) -> str:
    try:
        result = run(runner, [*prefix, "--version"], environment=environment, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return version_text(result.stdout or result.stderr) if result.returncode == 0 else ""


def npm_executable(prefix: list[str]) -> Path | None:
    if len(prefix) < 2 or not Path(prefix[0]).name.startswith("node"):
        return None
    candidate = Path(prefix[0]).parent / "npm"
    return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None


def npm_latest_version(
    npm: Path,
    environment: Mapping[str, str],
    runner: Runner,
) -> str:
    try:
        result = run(
            runner,
            [
                str(npm),
                "view",
                "@openai/codex",
                "version",
                "--json",
                "--fetch-retries=1",
                "--fetch-timeout=10000",
            ],
            environment=environment,
            timeout=CHECK_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        value = result.stdout
    return version_text(str(value))


def cached_codex_latest(environment: Mapping[str, str]) -> str:
    home = Path(environment.get("CODEX_HOME") or Path(environment.get("HOME") or Path.home()) / ".codex")
    try:
        value = json.loads((home / "version.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return version_text(str(value.get("latest_version") or "")) if isinstance(value, dict) else ""


def doctor_latest_version(
    prefix: list[str],
    environment: Mapping[str, str],
    runner: Runner,
) -> str:
    try:
        result = run(
            runner,
            [
                *prefix,
                "-c",
                "check_for_update_on_startup=false",
                "doctor",
                "--json",
            ],
            environment=environment,
            timeout=CHECK_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ""
    for check in payload.get("checks") or []:
        if isinstance(check, dict) and check.get("id") == "updates.status":
            details = check.get("details") or {}
            return version_text(str(details.get("latest version") or ""))
    return ""


def latest_version(
    prefix: list[str],
    environment: Mapping[str, str],
    runner: Runner,
) -> tuple[str, Path | None]:
    npm = npm_executable(prefix)
    if npm:
        latest = npm_latest_version(npm, environment, runner)
        if latest:
            return latest, npm
    latest = doctor_latest_version(prefix, environment, runner)
    return (latest or cached_codex_latest(environment)), npm


def update_codex(
    prefix: list[str],
    npm: Path | None,
    environment: Mapping[str, str],
    runner: Runner,
) -> bool:
    command = (
        [str(npm), "install", "-g", "@openai/codex@latest"]
        if npm
        else [*prefix, "-c", "check_for_update_on_startup=false", "update"]
    )
    try:
        result = run(
            runner,
            command,
            environment=environment,
            timeout=UPDATE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def run_preflight(
    launch_argv: list[str],
    state_file: Path,
    *,
    runner: Runner = subprocess.run,
    environment: Mapping[str, str] | None = None,
    now: float | None = None,
    check_interval: int = DEFAULT_CHECK_INTERVAL,
    failure_retry: int = DEFAULT_FAILURE_RETRY,
) -> dict[str, Any]:
    prefix = command_prefix(launch_argv)
    runtime_env = codex_runtime.codex_environment(prefix, environment)
    checked_at = int(time.time() if now is None else now)
    installed = installed_version(prefix, runtime_env, runner)
    prior = read_state(state_file)
    prior_latest = cached_codex_latest(runtime_env)
    retry_after = failure_retry if prior.get("result") == "failed" else check_interval
    cache_current = (
        installed
        and prior.get("installedVersion") == installed
        and checked_at - int(prior.get("checkedAt") or 0) < max(0, retry_after)
        and not (prior_latest and version_key(prior_latest) > version_key(installed))
    )
    if cache_current:
        return dict(prior)

    latest, npm = latest_version(prefix, runtime_env, runner)
    result = "current"
    final_version = installed
    if not installed or not latest:
        result = "failed"
    elif version_key(latest) > version_key(installed):
        print(f"Faryo: updating Codex {installed} -> {latest}...", flush=True)
        if update_codex(prefix, npm, runtime_env, runner):
            final_version = installed_version(prefix, runtime_env, runner)
            result = (
                "updated"
                if final_version and version_key(final_version) >= version_key(latest)
                else "failed"
            )
        else:
            result = "failed"

    state = {
        "schemaVersion": SCHEMA_VERSION,
        "checkedAt": checked_at,
        "installedVersion": final_version or installed,
        "latestVersion": latest,
        "result": result,
    }
    write_state(state_file, state)
    return state


def set_tmux_status(session: str, status: str) -> None:
    if not re.fullmatch(r"faryo[1-9][0-9]*", session) or status not in UPDATE_STATES:
        return
    try:
        subprocess.run(
            ["tmux", "set-option", "-q", "-t", session, "@faryo_codex_update", status],
            timeout=2,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    launch_argv = list(args.command)
    if launch_argv[:1] == ["--"]:
        launch_argv.pop(0)
    if not launch_argv:
        return 2
    state_dir = Path(args.state_dir).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.chmod(0o700)
    lock_path = state_dir / "codex-auto-update.lock"
    state_file = state_dir / "codex-auto-update.json"
    status = "failed"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.chmod(lock_path, 0o600)
        with os.fdopen(descriptor, "r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            status = str(run_preflight(launch_argv, state_file).get("result") or "failed")
    except Exception:
        status = "failed"
    set_tmux_status(args.session, status)
    if status == "failed":
        print("Faryo: Codex auto-update failed; continuing with the installed version.", flush=True)
    environment = codex_runtime.codex_environment(command_prefix(launch_argv))
    try:
        os.execvpe(launch_argv[0], launch_argv, environment)
    except OSError:
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
