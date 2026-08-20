"""Privacy-minimal durable storage for reliable-send delivery checkpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable

import tmux_runtime


class DeliveryStore:
    def __init__(
        self,
        root: Path,
        *,
        ttl_seconds: float,
        cleanup_interval_seconds: float,
        max_record_bytes: int = 16 * 1024,
        epoch_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root = root
        self.ttl_seconds = ttl_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.max_record_bytes = max_record_bytes
        self.epoch_clock = epoch_clock
        self.monotonic_clock = monotonic_clock
        self._cleanup_at = 0.0

    def record_path(self, delivery_id: str) -> Path | None:
        clean_id = tmux_runtime.clean_client_message_id(delivery_id)
        return self.root / f"{clean_id}.json" if clean_id else None

    def reset_cleanup_timer(self) -> None:
        self._cleanup_at = 0.0

    def cleanup(self, now_epoch: float | None = None, *, force: bool = False) -> None:
        monotonic_now = self.monotonic_clock()
        if not force and monotonic_now - self._cleanup_at < self.cleanup_interval_seconds:
            return
        self._cleanup_at = monotonic_now
        cutoff = (now_epoch if now_epoch is not None else self.epoch_clock()) - self.ttl_seconds
        try:
            paths = list(self.root.iterdir())
        except OSError:
            return
        for path in paths:
            if path.suffix != ".json" or tmux_runtime.clean_client_message_id(path.stem) != path.stem:
                continue
            try:
                stat = path.lstat()
                if path.is_symlink() or stat.st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue

    def persist(self, delivery_id: str, state: dict[str, Any]) -> bool:
        path = self.record_path(delivery_id)
        status = str(state.get("status") or "")
        receipt = state.get("receipt")
        if path is None or status not in {"pasted", "accepted"}:
            return False
        if status == "accepted" and not isinstance(receipt, dict):
            return False
        record: dict[str, Any] = {
            "version": 2,
            "deliveryId": delivery_id,
            "session": str(state.get("session") or ""),
            "digest": str(state.get("digest") or ""),
            "status": status,
            "updatedEpoch": float(state.get("updatedEpoch") or self.epoch_clock()),
        }
        if status == "accepted":
            record["receipt"] = receipt
        else:
            record["pasteReady"] = bool(state.get("pasteReady"))
            record["queuedBaseline"] = self._nonnegative_int(state.get("queuedBaseline"), 0)
            for key in ("rolloutDevice", "rolloutInode", "rolloutOffset"):
                value = self._nonnegative_int(state.get(key), None)
                if value is not None:
                    record[key] = value
        temp_path: str | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.root, 0o700)
            descriptor, temp_path = tempfile.mkstemp(prefix=".delivery-", suffix=".tmp", dir=self.root)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            temp_path = None
            self._fsync_root()
            return True
        except OSError:
            return False
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def load(self, delivery_id: str, now_epoch: float | None = None) -> dict[str, Any] | None:
        path = self.record_path(delivery_id)
        if path is None:
            return None
        try:
            stat = path.lstat()
            if path.is_symlink() or stat.st_size > self.max_record_bytes:
                return None
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(record, dict):
            return None
        try:
            updated_epoch = float(record.get("updatedEpoch"))
        except (TypeError, ValueError):
            return None
        if (now_epoch if now_epoch is not None else self.epoch_clock()) - updated_epoch > self.ttl_seconds:
            try:
                path.unlink()
            except OSError:
                pass
            return None
        version = record.get("version")
        status = str(record.get("status") or "")
        receipt = record.get("receipt")
        digest = str(record.get("digest") or "")
        if (
            version not in {1, 2}
            or record.get("deliveryId") != delivery_id
            or status not in {"pasted", "accepted"}
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            return None
        if status == "accepted" and (
            not isinstance(receipt, dict)
            or receipt.get("deliveryId") != delivery_id
            or receipt.get("delivery") != "accepted"
        ):
            return None
        if status == "pasted" and version != 2:
            return None
        state: dict[str, Any] = {
            "session": str(record.get("session") or ""),
            "digest": digest,
            "status": status,
            "updatedAt": self.monotonic_clock(),
            "updatedEpoch": updated_epoch,
        }
        if status == "accepted":
            state["receipt"] = receipt
        else:
            state["pasteReady"] = bool(record.get("pasteReady"))
            state["queuedBaseline"] = self._nonnegative_int(record.get("queuedBaseline"), 0)
            for key in ("rolloutDevice", "rolloutInode", "rolloutOffset"):
                value = self._nonnegative_int(record.get(key), None)
                if value is not None:
                    state[key] = value
        return state

    @staticmethod
    def _nonnegative_int(value: Any, fallback: int | None) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return fallback
        return parsed if parsed >= 0 else fallback

    def _fsync_root(self) -> None:
        try:
            descriptor = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
