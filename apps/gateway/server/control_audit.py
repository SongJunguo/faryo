"""Privacy-preserving, body-free Gateway control audit storage."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable


CONTROL_AUDIT_MAX_ROWS = 5000
CONTROL_AUDIT_RETENTION_SECONDS = 7 * 24 * 60 * 60
CONTROL_AUDIT_PRUNE_INTERVAL_SECONDS = 60 * 60


def result_for_status(status: int) -> str:
    if 200 <= status < 300:
        return "success"
    if status == 409:
        return "conflict"
    if status in {401, 403}:
        return "denied"
    if status == 404:
        return "not-found"
    return "failed"


class ControlAuditStore:
    def __init__(
        self,
        secret: bytes,
        path: Path,
        user_routes: Callable[[str], list[str]],
    ) -> None:
        self.secret = secret
        self.path = path
        self.user_routes = user_routes
        self._lock = threading.Lock()
        self._count: int | None = None
        self._prune_at = 0.0

    def target_digest(self, value: str) -> str:
        clean = str(value or "").strip()
        if not clean:
            return ""
        digest = hmac.new(self.secret, clean.encode("utf-8"), hashlib.sha256).hexdigest()
        return "t_" + digest[:16]

    def _prune_locked(self, now: float) -> None:
        rows: list[dict[str, Any]] = []
        cutoff = now - CONTROL_AUDIT_RETENTION_SECONDS
        try:
            with self.path.open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                        epoch = float(row.get("epoch") or 0) if isinstance(row, dict) else 0
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
                    if epoch >= cutoff:
                        rows.append(row)
        except FileNotFoundError:
            rows = []
        rows = rows[-CONTROL_AUDIT_MAX_ROWS:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(
            "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        self._count = len(rows)
        self._prune_at = now + CONTROL_AUDIT_PRUNE_INTERVAL_SECONDS

    def append(
        self,
        *,
        username: str,
        route: str,
        action: str,
        target: str,
        request_id: str,
        status: int,
        duration_ms: int,
        idempotent: bool = False,
    ) -> None:
        """Append one bounded row. Audit I/O failure never blocks control."""
        try:
            now = time.time()
            row = {
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "epoch": int(now),
                "requestId": str(request_id or "")[:32],
                "user": str(username or "")[:128],
                "route": str(route or "")[:24],
                "action": str(action or "")[:32],
                "target": self.target_digest(target),
                "result": result_for_status(int(status)),
                "http": int(status),
                "durationMs": max(0, min(int(duration_ms), 3_600_000)),
                "idempotent": bool(idempotent),
            }
            encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self._count is None:
                    try:
                        with self.path.open(encoding="utf-8", errors="replace") as stream:
                            self._count = sum(1 for _line in stream)
                    except FileNotFoundError:
                        self._count = 0
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    os.chmod(self.path, 0o600)
                    os.write(descriptor, encoded.encode("utf-8"))
                finally:
                    os.close(descriptor)
                self._count += 1
                if self._count > CONTROL_AUDIT_MAX_ROWS or now >= self._prune_at:
                    self._prune_locked(now)
        except Exception:
            return

    def activity(self, username: str, limit: int = 30) -> list[dict[str, Any]]:
        allowed_routes = set(self.user_routes(username))
        maximum = max(1, min(int(limit), 100))
        rows: list[dict[str, Any]] = []
        with self._lock:
            if not self.path.exists():
                return []
            now = time.time()
            if now >= self._prune_at:
                self._prune_locked(now)
            try:
                with self.path.open(encoding="utf-8", errors="replace") as stream:
                    lines = stream.readlines()
            except FileNotFoundError:
                return []
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                not isinstance(row, dict)
                or row.get("user") != username
                or row.get("route") not in allowed_routes | {""}
            ):
                continue
            rows.append({
                key: row.get(key)
                for key in (
                    "time",
                    "requestId",
                    "route",
                    "action",
                    "target",
                    "result",
                    "http",
                    "durationMs",
                    "idempotent",
                )
            })
            if len(rows) >= maximum:
                break
        return rows
