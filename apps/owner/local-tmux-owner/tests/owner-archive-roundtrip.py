#!/usr/bin/env python3
"""Isolated real App Server -> Owner archive/unarchive round trip."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import select
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
OWNER_SERVER = REPO_ROOT / "apps" / "owner" / "local-tmux-owner" / "run_owner_asgi.py"
DEFAULT_NODE = Path.home() / ".nvm" / "versions" / "node" / "v24.16.0" / "bin" / "node"
DEFAULT_CODEX = Path.home() / ".nvm" / "versions" / "node" / "v24.16.0" / "lib" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"


def send(process: subprocess.Popen[str], message: dict) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()


def read_response(process: subprocess.Popen[str], request_id: int, timeout: float = 12) -> dict:
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _write, _error = select.select([process.stdout], [], [], max(0, deadline - time.monotonic()))
        if not ready:
            break
        line = process.stdout.readline()
        if not line:
            break
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == request_id:
            return message
    raise RuntimeError(f"App Server request {request_id} timed out")


def stop(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def owner_post(port: int, token: str, path: str, thread_id: str, workspace: Path) -> dict:
    body = json.dumps({"agent_session_id": thread_id}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "X-Owner-Token": token,
        "X-Faryo-History-Scope": "workspace",
        "X-Faryo-Workspace-Root": str(workspace),
    }
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=12)
    try:
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        if response.status != 200:
            raise RuntimeError(f"Owner returned HTTP {response.status}: {payload.get('error')}")
        return payload
    finally:
        connection.close()


def owner_history_total(port: int, token: str, workspace: Path, archive: str) -> int:
    headers = {
        "X-Owner-Token": token,
        "X-Faryo-History-Scope": "workspace",
        "X-Faryo-Workspace-Root": str(workspace),
    }
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=12)
    try:
        connection.request("GET", f"/api/agent-sessions?view=split&limit=10&offset=0&archive={archive}", headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        if response.status != 200:
            raise RuntimeError(f"Owner history returned HTTP {response.status}")
        return int(payload.get("historyTotal") or 0)
    finally:
        connection.close()


def main() -> None:
    node = Path(os.environ.get("FARYO_ARCHIVE_NODE", str(DEFAULT_NODE))).expanduser()
    codex = Path(os.environ.get("FARYO_ARCHIVE_CODEX", str(DEFAULT_CODEX))).expanduser()
    if not node.is_file() or not codex.is_file():
        raise RuntimeError("set FARYO_ARCHIVE_NODE and FARYO_ARCHIVE_CODEX to installed executables")
    with tempfile.TemporaryDirectory(prefix="faryo-owner-archive.") as temp:
        root = Path(temp)
        archive_fixture_home = root / "codex-home"
        workspace = root / "workspace"
        archive_fixture_home.mkdir()
        workspace.mkdir()
        child_env = dict(os.environ)
        child_env.update({
            "CODEX_HOME": str(archive_fixture_home),
            "FARYO_CODEX_BIN": str(codex),
            "FARYO_CODEX_STATE_DB": str(archive_fixture_home / "state_5.sqlite"),
            "FARYO_CODEX_SESSION_INDEX": str(archive_fixture_home / "session_index.jsonl"),
            "FARYO_OWNER_DATA": str(root / "owner-data"),
        })
        app_server: subprocess.Popen[str] | None = subprocess.Popen(
            [str(node), str(codex), "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            env=child_env,
        )
        owner: subprocess.Popen[str] | None = None
        try:
            send(app_server, {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "faryo-test", "title": "Faryo archive fixture", "version": "0"}, "capabilities": {}}})
            assert "result" in read_response(app_server, 1)
            send(app_server, {"method": "initialized", "params": {}})
            send(app_server, {"id": 2, "method": "thread/start", "params": {"cwd": str(workspace)}})
            started = read_response(app_server, 2)
            if started.get("error"):
                raise RuntimeError("anonymous thread/start failed")
            thread = started["result"]["thread"]
            thread_id = str(thread["id"])
            rollout = Path(thread["path"])
            send(app_server, {"id": 3, "method": "thread/name/set", "params": {"threadId": thread_id, "name": "Anonymous archive fixture"}})
            if read_response(app_server, 3).get("error"):
                raise RuntimeError("anonymous thread/name/set failed")
            deadline = time.monotonic() + 5
            while not rollout.is_file() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not rollout.is_file():
                raise RuntimeError("anonymous rollout was not materialized")
            before_hash = hashlib.sha256(rollout.read_bytes()).hexdigest()
            stop(app_server)
            app_server = None

            # thread/start records the test client as an app-server source.
            # Normalize only this disposable fixture so Owner exercises the
            # same cli/user visibility boundary as production sessions.
            state_db = archive_fixture_home / "state_5.sqlite"
            connection = sqlite3.connect(state_db)
            try:
                connection.execute(
                    "UPDATE threads SET source = 'cli', thread_source = 'user', cwd = ? WHERE id = ?",
                    (str(workspace), thread_id),
                )
                connection.commit()
            finally:
                connection.close()

            port = free_port()
            token = "anonymous-owner-archive-token"
            owner = subprocess.Popen(
                [sys.executable, str(OWNER_SERVER), "--host", "127.0.0.1", "--port", str(port), "--session", "faryo-archive-no-tmux", "--token", token, "--pane-width", "0"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=child_env,
            )
            for _attempt in range(100):
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                    connection.request("GET", "/health")
                    ready = connection.getresponse().status == 200
                    connection.close()
                    if ready:
                        break
                except OSError:
                    pass
                time.sleep(0.05)
            else:
                raise RuntimeError("isolated Owner did not start")

            if owner_history_total(port, token, workspace, "active") != 1:
                raise RuntimeError("anonymous current history baseline was incorrect")
            archived = owner_post(port, token, "/api/agent-session/archive", thread_id, workspace)
            if not archived.get("archived") or archived.get("duplicate"):
                raise RuntimeError("Owner archive response was incorrect")
            archived_files = list((archive_fixture_home / "archived_sessions").rglob(f"*{thread_id}*.jsonl"))
            if len(archived_files) != 1 or hashlib.sha256(archived_files[0].read_bytes()).hexdigest() != before_hash:
                raise RuntimeError("archived rollout hash changed")
            if owner_history_total(port, token, workspace, "active") != 0 or owner_history_total(port, token, workspace, "archived") != 1:
                raise RuntimeError("archived history filter did not update")

            restored = owner_post(port, token, "/api/agent-session/unarchive", thread_id, workspace)
            if restored.get("archived") or restored.get("duplicate"):
                raise RuntimeError("Owner unarchive response was incorrect")
            restored_path = next(iter((archive_fixture_home / "sessions").rglob(f"*{thread_id}*.jsonl")), None)
            if restored_path is None or hashlib.sha256(restored_path.read_bytes()).hexdigest() != before_hash:
                raise RuntimeError("restored rollout hash changed")
            if owner_history_total(port, token, workspace, "active") != 1 or owner_history_total(port, token, workspace, "archived") != 0:
                raise RuntimeError("restored history filter did not update")
            print("faryo-owner-archive-roundtrip=PASS archive=rpc unarchive=rpc filters=current,archived hash=unchanged real-home=untouched")
        finally:
            stop(owner)
            stop(app_server)


if __name__ == "__main__":
    main()
