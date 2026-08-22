"""Stable session-backend domain names and legacy wire compatibility."""

from __future__ import annotations

from enum import Enum
from typing import Any


class SessionBackend(str, Enum):
    """One writer implementation for a Codex conversation.

    Enum member names are the domain vocabulary used by new code.  Values are
    the existing wire/storage protocol and intentionally remain stable during
    rolling upgrades.
    """

    APP_SERVER = "web-managed"
    CODEX_TUI = "terminal-managed"

    @property
    def label(self) -> str:
        return {
            SessionBackend.APP_SERVER: "Codex App Server",
            SessionBackend.CODEX_TUI: "Codex TUI (tmux)",
        }[self]


APP_SERVER = SessionBackend.APP_SERVER
CODEX_TUI = SessionBackend.CODEX_TUI


def parse_backend(value: Any, *, default: SessionBackend | None = None) -> SessionBackend | None:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        return SessionBackend(raw)
    except ValueError:
        return None


def backend_for_source(source: Any) -> SessionBackend:
    return APP_SERVER if str(source or "").strip() == "codex-app-server" else CODEX_TUI


def backend_label(value: Any) -> str:
    selected = value if isinstance(value, SessionBackend) else parse_backend(value)
    return selected.label if selected is not None else "Unknown backend"
