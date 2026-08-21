"""Serialized Codex App Server stdio lifecycle and JSON-RPC client."""

from __future__ import annotations

import json
import select
import subprocess
import threading
import time
from typing import Any, Callable, Mapping


class CodexAppServerClient:
    def __init__(
        self,
        *,
        argv: Callable[..., list[str]],
        client_version: Callable[[], str],
        environment: Callable[[list[str]], Mapping[str, str]] | None = None,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.argv = argv
        self.client_version = client_version
        self.environment = environment
        self.popen = popen
        self.monotonic = monotonic
        self.process: subprocess.Popen[str] | None = None
        self.request_id = 0
        self.lock = threading.Lock()

    @staticmethod
    def send(process: subprocess.Popen[str], message: dict[str, Any]) -> bool:
        if process.stdin is None:
            return False
        try:
            process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except OSError:
            return False
        return True

    def read(self, process: subprocess.Popen[str], deadline: float) -> dict[str, Any] | None:
        if process.stdout is None:
            return None
        remaining = deadline - self.monotonic()
        if remaining <= 0:
            return None
        ready, _write, _error = select.select([process.stdout], [], [], remaining)
        if not ready:
            return None
        line = process.stdout.readline()
        if not line:
            return None
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return None
        return message if isinstance(message, dict) else None

    def stop_locked(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass

    def stop(self) -> None:
        with self.lock:
            self.stop_locked()

    def start_locked(self, timeout: float) -> subprocess.Popen[str] | None:
        process = self.process
        if process is not None and process.poll() is None:
            return process
        self.stop_locked()
        try:
            argv = self.argv("app-server", "--listen", "stdio://")
            process = self.popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=dict(self.environment(argv)) if self.environment else None,
            )
        except OSError:
            return None
        self.process = process
        self.request_id += 1
        request_id = self.request_id
        if not self.send(process, {
            "id": request_id,
            "method": "initialize",
            "params": {
                "clientInfo": {
                    "name": "local-tmux-owner",
                    "title": "Faryo Owner",
                    "version": self.client_version() or "0",
                },
                "capabilities": {},
            },
        }):
            self.stop_locked()
            return None
        deadline = self.monotonic() + timeout
        while self.monotonic() < deadline:
            message = self.read(process, deadline)
            if message is None:
                break
            if message.get("id") != request_id:
                continue
            if isinstance(message.get("result"), dict):
                if not self.send(process, {"method": "initialized", "params": {}}):
                    break
                return process
            break
        self.stop_locked()
        return None

    def rpc(self, method: str, params: dict[str, Any], timeout: float = 2.5) -> dict[str, Any]:
        with self.lock:
            for _attempt in range(2):
                process = self.start_locked(timeout)
                if process is None:
                    continue
                self.request_id += 1
                request_id = self.request_id
                if not self.send(process, {"id": request_id, "method": method, "params": params}):
                    self.stop_locked()
                    continue
                deadline = self.monotonic() + timeout
                while self.monotonic() < deadline:
                    message = self.read(process, deadline)
                    if message is None:
                        break
                    if message.get("id") != request_id:
                        continue
                    if isinstance(message.get("error"), dict):
                        error = message["error"]
                        return {
                            "ok": False,
                            "code": int(error.get("code") or 0),
                            "error": str(error.get("message") or "Codex App Server request failed"),
                        }
                    if "result" in message:
                        return {"ok": True, "result": message.get("result")}
                    return {
                        "ok": False,
                        "code": 0,
                        "error": "Codex App Server returned an invalid response",
                    }
                self.stop_locked()
        return {"ok": False, "code": 0, "error": "Codex App Server is unavailable"}

    def request(self, method: str, params: dict[str, Any], timeout: float = 2.5) -> dict[str, Any] | None:
        response = self.rpc(method, params, timeout)
        result = response.get("result") if response.get("ok") else None
        return result if isinstance(result, dict) else None
