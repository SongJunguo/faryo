"""Command parser and presentation for the unified Faryo CLI."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from faryo_cli import __version__
from faryo_cli.diagnostics import build_report, compact_status


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="faryo", description="Manage the local Faryo Owner and Gateway")
    root.add_argument("--version", action="version", version=f"Faryo {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("doctor", "Check runtime, configuration, services, and loopback health"),
        ("status", "Show a compact read-only service summary"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--json", action="store_true", help="Print privacy-safe machine-readable JSON")
    return root


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def print_doctor(report: dict[str, Any]) -> None:
    labels = {"ok": "OK", "warn": "WARN", "error": "FAIL"}
    for item in report["checks"]:
        print(f"{labels[item['status']]:<4} {item['id']:<20} {item['detail']}")
    counts = report["counts"]
    print(f"\nFaryo doctor: {counts['ok']} ok, {counts['warn']} warning, {counts['error']} failed")


def print_status(status: dict[str, Any]) -> None:
    print(f"Owner:  {status['owner']['service']} · health {status['owner']['health']}")
    print(f"Gateway: {status['gateway']['service']} · health {status['gateway']['health']}")
    print(f"tmux sessions: {status['tmuxSessions']}")
    if status["legacyOwner"]:
        print("Migration: legacy Owner tmux/keepalive is still active")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    report = build_report()
    if arguments.command == "doctor":
        if arguments.json:
            print_json(report)
        else:
            print_doctor(report)
        return 0 if report["ok"] else 1
    status = compact_status(report)
    if arguments.json:
        print_json(status)
    else:
        print_status(status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
