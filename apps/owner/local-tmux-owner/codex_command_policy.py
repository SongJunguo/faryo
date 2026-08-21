"""Versioned and runtime-overridable Codex slash-command catalog."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import threading
from typing import Any


CATALOG_SCHEMA_VERSION = 1
EXACT_COMMAND_RE = re.compile(r"^/[a-z][a-z-]*$")
APP_DIR = Path(__file__).resolve().parent
FALLBACK_CATALOG = APP_DIR / "static" / "codex-command-catalog.json"
DEFAULT_RUNTIME_CATALOG = Path(
    os.environ.get(
        "FARYO_CODEX_COMMAND_CATALOG",
        str(Path.home() / ".faryo" / "owner" / "cache" / "codex-command-catalog.json"),
    )
).expanduser()


@dataclass(frozen=True)
class CommandEntry:
    command: str
    description: str
    category: str
    behavior: str
    argument_hint: str = ""
    aliases: tuple[str, ...] = ()

    def public_value(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "description": self.description,
            "category": self.category,
            "behavior": self.behavior,
            "argumentHint": self.argument_hint,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True)
class CommandCatalog:
    tested_codex_version: str
    observed_codex_version: str
    entries: tuple[CommandEntry, ...]
    source: str
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def by_command(self) -> dict[str, CommandEntry]:
        result: dict[str, CommandEntry] = {}
        for entry in self.entries:
            result[entry.command] = entry
            for alias in entry.aliases:
                result[alias] = entry
        return result

    @property
    def drifted(self) -> bool:
        return bool(self.added or self.removed) or bool(
            self.observed_codex_version
            and self.tested_codex_version
            and self.observed_codex_version != self.tested_codex_version
        )

    def public_value(self) -> dict[str, Any]:
        return {
            "schemaVersion": CATALOG_SCHEMA_VERSION,
            "testedCodexVersion": self.tested_codex_version,
            "observedCodexVersion": self.observed_codex_version,
            "source": self.source,
            "drifted": self.drifted,
            "added": list(self.added),
            "removed": list(self.removed),
            "commands": [entry.public_value() for entry in self.entries],
        }


def _read_payload(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 512 * 1024:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and value.get("schemaVersion") == CATALOG_SCHEMA_VERSION else None


def _clean_command(value: object) -> str | None:
    command = str(value or "").strip().lower()
    return command if EXACT_COMMAND_RE.fullmatch(command) else None


def _entries(payload: dict[str, Any], fallback: dict[str, CommandEntry] | None = None) -> tuple[CommandEntry, ...]:
    result: list[CommandEntry] = []
    seen: set[str] = set()
    for raw in payload.get("commands") or []:
        if isinstance(raw, str):
            raw = {"command": raw}
        if not isinstance(raw, dict):
            continue
        command = _clean_command(raw.get("command"))
        if not command or command in seen:
            continue
        known = (fallback or {}).get(command)
        aliases = tuple(
            alias
            for value in (raw.get("aliases") or (known.aliases if known else ()))
            if (alias := _clean_command(value)) is not None and alias != command
        )
        result.append(
            CommandEntry(
                command=command,
                description=str(raw.get("description") or (known.description if known else "New Codex command"))[:240],
                category=str(raw.get("category") or (known.category if known else "Unclassified"))[:48],
                behavior=str(raw.get("behavior") or (known.behavior if known else "unclassified")),
                argument_hint=str(raw.get("argumentHint") or (known.argument_hint if known else ""))[:80],
                aliases=aliases,
            )
        )
        seen.add(command)
    return tuple(result)


def load_catalog(
    *,
    fallback_path: Path = FALLBACK_CATALOG,
    runtime_path: Path | None = DEFAULT_RUNTIME_CATALOG,
) -> CommandCatalog:
    fallback_payload = _read_payload(fallback_path)
    if fallback_payload is None:
        raise RuntimeError("Codex command fallback catalog is unavailable")
    fallback_entries = _entries(fallback_payload)
    fallback_by_command = {entry.command: entry for entry in fallback_entries}
    tested_version = str(fallback_payload.get("testedCodexVersion") or "")
    runtime_payload = _read_payload(runtime_path) if runtime_path is not None else None
    if runtime_payload is None:
        return CommandCatalog(tested_version, "", fallback_entries, "fallback")
    runtime_entries = _entries(runtime_payload, fallback_by_command)
    if not runtime_entries:
        return CommandCatalog(tested_version, "", fallback_entries, "fallback")
    runtime_names = {entry.command for entry in runtime_entries}
    fallback_names = set(fallback_by_command)
    return CommandCatalog(
        tested_version,
        str(runtime_payload.get("observedCodexVersion") or ""),
        runtime_entries,
        "runtime",
        tuple(sorted(runtime_names - fallback_names)),
        tuple(sorted(fallback_names - runtime_names)),
    )


_DEFAULT_CATALOG = load_catalog()
_CATALOG_LOCK = threading.Lock()


def default_catalog() -> CommandCatalog:
    with _CATALOG_LOCK:
        return _DEFAULT_CATALOG


def reload_default_catalog(
    *,
    runtime_path: Path | None = DEFAULT_RUNTIME_CATALOG,
) -> CommandCatalog:
    global _DEFAULT_CATALOG
    catalog = load_catalog(runtime_path=runtime_path)
    with _CATALOG_LOCK:
        _DEFAULT_CATALOG = catalog
    return catalog


def exact_command(value: object, catalog: CommandCatalog | None = None) -> str | None:
    command = _clean_command(value)
    if command is None:
        return None
    selected = catalog or default_catalog()
    return command if command in selected.by_command else None


def command_invocation(value: object, catalog: CommandCatalog | None = None) -> str | None:
    line = str(value or "").strip()
    if not line or len(line) > 4096 or any(character in line for character in ("\n", "\r", "\x00")):
        return None
    head, separator, arguments = line.partition(" ")
    selected = catalog or default_catalog()
    command = exact_command(head, selected)
    if command is None:
        return None
    return command + (separator + arguments if separator else "")


def command_entry(command: object, catalog: CommandCatalog | None = None) -> CommandEntry | None:
    selected = catalog or default_catalog()
    invocation = command_invocation(command, selected)
    if invocation is None:
        return None
    return selected.by_command.get(invocation.split(" ", 1)[0])


def command_behavior(command: object, catalog: CommandCatalog | None = None) -> str | None:
    selected = catalog or default_catalog()
    entry = command_entry(command, selected)
    return entry.behavior if entry else None
