"""Gateway bridge-package persistence, attachment storage, and retention."""

from __future__ import annotations

import json
from pathlib import Path
import secrets
import shutil
import threading
import time
from typing import Any, Callable


BRIDGE_ASSET_LIMIT = 4
BRIDGE_PENDING_RETENTION_SECONDS = 30 * 24 * 60 * 60
BRIDGE_DELIVERED_RETENTION_SECONDS = 7 * 24 * 60 * 60
BRIDGE_CLEANUP_INTERVAL_SECONDS = 60 * 60


class BridgePackageStore:
    def __init__(
        self,
        root: Path,
        mcp_user: str,
        *,
        clean_package_id: Callable[[str], str | None],
        normalize_asset: Callable[[Any], dict[str, Any] | None],
        asset_bytes: Callable[[dict[str, Any]], tuple[str, bytes]],
        mime_extensions: dict[str, str],
        now_ts: Callable[[], int],
    ) -> None:
        self.root = root
        self.mcp_user = mcp_user
        self.clean_package_id = clean_package_id
        self.normalize_asset = normalize_asset
        self.asset_bytes = asset_bytes
        self.mime_extensions = mime_extensions
        self.now_ts = now_ts
        self.root.mkdir(parents=True, exist_ok=True)
        self._cleanup_lock = threading.Lock()
        self._cleanup_at = 0.0

    @staticmethod
    def asset_sources(payload: dict[str, Any]) -> list[Any]:
        assets: list[Any] = []
        for key in ("attachments", "files", "assets", "images"):
            values = payload.get(key)
            if isinstance(values, list):
                assets.extend(values)
        for key in ("attachment", "file", "asset", "image"):
            if payload.get(key):
                assets.insert(0, payload.get(key))
        return assets[:BRIDGE_ASSET_LIMIT]

    @staticmethod
    def attachment_only_prompt(title: str) -> str:
        return (
            "# Faryo Handoff Package\n"
            f"Title: {title}\n\n"
            "Review the attached files and continue from the current session context. "
            "Use the attachment paths below as the canonical source files."
        )

    def save_assets(
        self,
        package_id: str,
        package_dir: Path,
        asset_sources: list[Any],
        start_index: int = 1,
    ) -> list[dict[str, Any]]:
        assets = []
        for index, item in enumerate(asset_sources, start=start_index):
            asset = self.normalize_asset(item)
            if not asset:
                raise ValueError("invalid attachment payload")
            mime_type, data = self.asset_bytes(asset)
            file_name = f"asset-{index}{self.mime_extensions[mime_type]}"
            path = package_dir / file_name
            path.write_bytes(data)
            assets.append({
                "file_name": asset["file_name"],
                "mime_type": mime_type,
                "size": len(data),
                "path": str(path),
                "url": f"/bridge/packages/{package_id}/{file_name}",
            })
        return assets

    def user_can_access(self, username: str, package: dict[str, Any]) -> bool:
        owner = str(package.get("owner") or "")
        return owner == username or (not owner and username == self.mcp_user)

    def save(self, payload: dict[str, Any], username: str) -> dict[str, Any]:
        self.cleanup()
        title = str(payload.get("title") or payload.get("topic") or "Untitled handoff").strip()[:120]
        title = title or "Untitled handoff"
        prompt = str(
            payload.get("prompt")
            or payload.get("instruction")
            or payload.get("handoff_prompt")
            or ""
        ).strip()
        assets = self.asset_sources(payload)
        if not prompt and not assets:
            raise ValueError("package prompt or attachment is required")
        package_id = f"{self.now_ts()}-{secrets.token_hex(4)}"
        package_dir = self.root / package_id
        package_dir.mkdir(parents=True, exist_ok=False)
        try:
            package = {
                "id": package_id,
                "owner": username,
                "title": title,
                "source": str(payload.get("source") or "Faryo Gateway"),
                "intent": str(payload.get("intent") or ""),
                "context": str(payload.get("context") or payload.get("summary") or ""),
                "prompt": prompt or self.attachment_only_prompt(title),
                "assets": self.save_assets(package_id, package_dir, assets),
                "status": "pending",
                "created_at": self.now_ts(),
                "updated_at": self.now_ts(),
            }
            (package_dir / "package.json").write_text(
                json.dumps(package, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return package
        except Exception:
            shutil.rmtree(package_dir, ignore_errors=True)
            raise

    def append_assets(self, package_id: str, asset_sources: list[Any], username: str) -> dict[str, Any]:
        package_id = self.clean_package_id(package_id) or ""
        package = self.get(package_id, username)
        if not package_id:
            raise ValueError("invalid package id")
        if not asset_sources:
            raise ValueError("attachment is required")
        if not package:
            raise ValueError("package not found")
        if package.get("status") != "pending":
            raise ValueError("package is already delivered")
        assets = package.get("assets") if isinstance(package.get("assets"), list) else []
        package["assets"] = assets + self.save_assets(
            package_id,
            self.root / package_id,
            asset_sources[:BRIDGE_ASSET_LIMIT],
            len(assets) + 1,
        )
        package["prompt"] = str(package.get("prompt") or "").strip() or self.attachment_only_prompt(
            str(package.get("title") or "Handoff package")
        )
        self.update(package)
        return package

    def list(self, username: str, status: str | None = None) -> list[dict[str, Any]]:
        self.cleanup()
        packages = [
            package
            for package in (self.get(path.parent.name, username) for path in self.root.glob("*/package.json"))
            if package and (not status or package.get("status") == status)
        ]
        return sorted(
            packages,
            key=lambda item: int(item.get("updated_at") or item.get("created_at") or 0),
            reverse=True,
        )

    def cleanup(self, current_time: int | None = None, force: bool = False) -> int:
        now = int(current_time if current_time is not None else self.now_ts())
        monotonic_now = time.monotonic()
        with self._cleanup_lock:
            if not force and monotonic_now < self._cleanup_at:
                return 0
            self._cleanup_at = monotonic_now + BRIDGE_CLEANUP_INTERVAL_SECONDS
            root = self.root.resolve()
            removed = 0
            try:
                candidates = list(self.root.iterdir())
            except OSError:
                return 0
            for package_dir in candidates:
                if package_dir.is_symlink() or self.clean_package_id(package_dir.name) != package_dir.name:
                    continue
                try:
                    target = package_dir.resolve(strict=True)
                    if target.parent != root or not target.is_dir():
                        continue
                    package_file = target / "package.json"
                    package = json.loads(package_file.read_text(encoding="utf-8"))
                    if not isinstance(package, dict):
                        continue
                    updated = int(
                        package.get("updated_at")
                        or package.get("created_at")
                        or package_file.stat().st_mtime
                    )
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    continue
                retention = (
                    BRIDGE_PENDING_RETENTION_SECONDS
                    if package.get("status") == "pending"
                    else BRIDGE_DELIVERED_RETENTION_SECONDS
                )
                if updated <= 0 or now - updated <= retention:
                    continue
                shutil.rmtree(target)
                removed += 1
            return removed

    def get(self, package_id: str, username: str | None = None) -> dict[str, Any] | None:
        path = self.root / (self.clean_package_id(package_id) or "") / "package.json"
        try:
            package = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(package, dict):
            return None
        if username and not self.user_can_access(username, package):
            return None
        return package

    def update(self, package: dict[str, Any]) -> None:
        package_id = self.clean_package_id(str(package.get("id") or ""))
        if not package_id:
            raise ValueError("invalid package id")
        package["updated_at"] = self.now_ts()
        (self.root / package_id / "package.json").write_text(
            json.dumps(package, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
