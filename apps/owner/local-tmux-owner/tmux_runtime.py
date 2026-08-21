"""Low-level subprocess, tmux, process-tree, and identifier primitives."""

from __future__ import annotations

import re
import subprocess
from typing import Mapping


TMUX_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
CODEX_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
CLIENT_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")
CLIENT_LAUNCH_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")


def run_command(
    args: list[str],
    *,
    input_text: str | None = None,
    timeout: float = 5.0,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env=dict(environment) if environment is not None else None,
    )


def run_tmux(
    args: list[str],
    *,
    timeout: float = 5.0,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return run_command(
        ["tmux", *args],
        timeout=timeout,
        environment=environment,
    )


def parse_process_table(output: str) -> dict[int, tuple[int, str]]:
    table: dict[int, tuple[int, str]] = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        table[pid] = (ppid, parts[2] if len(parts) > 2 else "")
    return table


def process_table() -> dict[int, tuple[int, str]]:
    result = run_command(["ps", "-eo", "pid=,ppid=,args="], timeout=3)
    return parse_process_table(result.stdout) if result.returncode == 0 else {}


def descendants(root_pid: int, table: dict[int, tuple[int, str]]) -> list[tuple[int, str]]:
    children: dict[int, list[int]] = {}
    for pid, (ppid, _command) in table.items():
        children.setdefault(ppid, []).append(pid)
    output: list[tuple[int, str]] = []
    stack = list(children.get(root_pid, []))
    while stack:
        pid = stack.pop()
        output.append((pid, table.get(pid, (0, ""))[1]))
        stack.extend(children.get(pid, []))
    return output


def _clean_identifier(value: str | None, pattern: re.Pattern[str]) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    return cleaned if pattern.fullmatch(cleaned) else None


def clean_tmux_session_name(value: str | None) -> str | None:
    return _clean_identifier(value, TMUX_SESSION_NAME_RE)


def clean_agent_session_id(value: str | None) -> str | None:
    return _clean_identifier(value, CODEX_THREAD_ID_RE)


def clean_client_message_id(value: str | None) -> str | None:
    return _clean_identifier(value, CLIENT_MESSAGE_ID_RE)


def clean_client_launch_id(value: str | None) -> str | None:
    return _clean_identifier(value, CLIENT_LAUNCH_ID_RE)
