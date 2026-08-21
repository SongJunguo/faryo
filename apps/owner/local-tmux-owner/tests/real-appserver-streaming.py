#!/usr/bin/env python3
"""Opt-in real Codex App Server delta/final test with an isolated CODEX_HOME."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

import uvicorn


APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
for value in (str(APP_DIR), str(REPO_ROOT / "src")):
    if value not in sys.path:
        sys.path.insert(0, value)

import appserver_history
from appserver_runtime import AppServerRuntime
import codex_history
from faryo_cli import codex_runtime
import owner_asgi
import server


PROMPT = """Reply without tools. Write a short Chinese Markdown demonstration containing:
1. a heading;
2. the inline formula $x^2+y^2=z^2$;
3. the display formula $$\\int_0^1 x^2\\,dx=\\frac13$$;
4. a fenced Python code block.
End with the literal word STREAM_DONE.
"""
RESTART_PROMPT = """Reply without tools. Write 40 short numbered Chinese lines about restart-safe streaming,
then end with the literal word OWNER_RESTART_DONE.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", default="")
    parser.add_argument("--auth-file", default="")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--restart", action="store_true")
    return parser.parse_args()


def wait_for_socket(path: Path, process: subprocess.Popen[bytes], timeout: float = 12.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_socket():
            return
        if process.poll() is not None:
            raise RuntimeError("Codex App Server exited before opening its private socket")
        time.sleep(0.05)
    raise RuntimeError("Codex App Server did not open its private socket")


def jsonl_has_final(codex_home: Path, expected: str) -> bool:
    for path in codex_home.glob("sessions/**/*.jsonl"):
        try:
            with path.open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    message = codex_history.rollout_message(event)
                    if message == ("assistant", expected):
                        return True
        except OSError:
            continue
    return False


def free_port() -> int:
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def main() -> int:
    args = parse_args()
    source_home = Path.home()
    auth_file = Path(args.auth_file).expanduser() if args.auth_file else source_home / ".codex/auth.json"
    if not auth_file.is_file():
        raise RuntimeError("Codex authentication is unavailable for the isolated test")
    executable = codex_runtime.resolve_codex(args.codex, source_home, os.environ)
    if not executable:
        raise RuntimeError("Codex CLI is unavailable")

    with tempfile.TemporaryDirectory(prefix="faryo-real-appserver-") as temp:
        root = Path(temp)
        codex_home = root / "codex-home"
        workspace = root / "workspace"
        runtime_root = root / "runtime"
        for path in (codex_home, workspace, runtime_root):
            path.mkdir(mode=0o700)
        copied_auth = codex_home / "auth.json"
        shutil.copyfile(auth_file, copied_auth)
        copied_auth.chmod(0o600)
        socket_path = runtime_root / "codex-app-server.sock"
        registry_path = runtime_root / "sessions.json"
        argv = codex_runtime.codex_argv(
            executable,
            "app-server",
            "--listen",
            f"unix://{socket_path}",
        )
        environment = codex_runtime.codex_environment(argv, os.environ)
        environment["CODEX_HOME"] = str(codex_home)
        log_path = runtime_root / "appserver.log"
        process: subprocess.Popen[bytes] | None = None
        runtime: AppServerRuntime | None = None
        web_server: uvicorn.Server | None = None
        web_thread: threading.Thread | None = None
        try:
            with log_path.open("wb") as log:
                process = subprocess.Popen(
                    argv,
                    cwd=workspace,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                wait_for_socket(socket_path, process)
                runtime = AppServerRuntime(
                    socket_path=socket_path,
                    registry_path=registry_path,
                    client_version="real-test",
                )
                runtime.start()
                if not runtime.wait_ready(12):
                    raise RuntimeError("Faryo did not initialize the real Codex App Server")
                started = runtime.start_session(
                    cwd=str(workspace),
                    title="Faryo streaming test",
                    launch_id="real_appserver_streaming_test",
                )
                session = str(started["session"])
                cursor = runtime.replay(None).latest.render()
                runtime.send(session, PROMPT, "real_appserver_streaming_message")

                events = []
                partial_lengths: list[int] = []
                final_text = ""
                deadline = time.monotonic() + max(30.0, args.timeout)
                while time.monotonic() < deadline:
                    replay = runtime.wait_for_events(cursor, 1.0)
                    cursor = replay.latest.render()
                    events.extend(replay.events)
                    capture = runtime.capture(session)
                    assistants = [text for role, text in capture["messages"] if role == "assistant"]
                    if assistants:
                        partial_lengths.append(len(assistants[-1]))
                        final_text = assistants[-1]
                    observed_kinds = {event.kind for event in events}
                    if (
                        capture["snapshot"].get("lifecycle") == "idle"
                        and final_text
                        and {"item.delta", "item.final", "turn.completed"} <= observed_kinds
                    ):
                        break
                else:
                    raise RuntimeError("real Codex turn did not settle before the timeout")

                kinds = [event.kind for event in events]
                if "item.delta" not in kinds or "item.final" not in kinds or "turn.completed" not in kinds:
                    raise RuntimeError("real Codex notifications did not include delta, final, and turn completion")
                if not all(marker in final_text for marker in ("x^2+y^2=z^2", "\\int_0^1", "```", "STREAM_DONE")):
                    raise RuntimeError("real Codex final response lost Markdown or TeX structure")
                if "STREAM_DONE" in repr([event.payload for event in events]):
                    raise RuntimeError("the replay journal retained message body content")

                capture = runtime.capture(session)
                history = appserver_history.conversation_history_page(
                    capture["snapshot"],
                    thread_id=str(started["threadId"]),
                    limit=12,
                    max_page_turns=24,
                    page_char_budget=2 * 1024 * 1024,
                    preview_chars=96,
                    updated_at=lambda: "now",
                )
                if history["totalTurns"] < 1 or "STREAM_DONE" not in history["turns"][-1]["text"]:
                    raise RuntimeError("live App Server history did not converge to the final turn")
                jsonl_deadline = time.monotonic() + 5
                while time.monotonic() < jsonl_deadline and not jsonl_has_final(codex_home, final_text):
                    time.sleep(0.05)
                if not jsonl_has_final(codex_home, final_text):
                    raise RuntimeError("Codex JSONL did not contain the authoritative final response")

                delta_events = [event for event in events if event.kind == "item.delta"]
                print(
                    "real-appserver-streaming=PASS "
                    f"delta_batches={len(delta_events)} "
                    f"max_batch={max(int(event.payload.get('batchCount') or 1) for event in delta_events)} "
                    f"observed_lengths={len(set(partial_lengths))} "
                    "markdown=yes tex=yes jsonl=yes body_free_journal=yes"
                )
                if args.browser:
                    browser_cursor = runtime.replay(None).latest.render()
                    port = free_port()
                    app = owner_asgi.create_app(
                        server,
                        server.Config(server.DEFAULT_SESSION, "fixture-owner-token", 0),
                        runtime,
                    )
                    web_server = uvicorn.Server(
                        uvicorn.Config(
                            app,
                            host="127.0.0.1",
                            port=port,
                            access_log=False,
                            lifespan="on",
                            log_level="error",
                        )
                    )
                    web_thread = threading.Thread(target=web_server.run, daemon=True)
                    web_thread.start()
                    web_deadline = time.monotonic() + 5
                    while time.monotonic() < web_deadline and not web_server.started:
                        time.sleep(0.01)
                    if not web_server.started:
                        raise RuntimeError("isolated Owner browser fixture did not start")
                    browser_environment = dict(environment)
                    browser_environment["FARYO_SMOKE_URL"] = (
                        f"http://127.0.0.1:{port}/?token=fixture-owner-token&session={session}"
                    )
                    node = shutil.which("node", path=browser_environment.get("PATH"))
                    if not node:
                        raise RuntimeError("matching Node runtime is unavailable for the browser test")
                    browser = subprocess.run(
                        [
                            node,
                            str(APP_DIR / "tests/browser-real-appserver-streaming.mjs"),
                        ],
                        cwd=REPO_ROOT,
                        env=browser_environment,
                        text=True,
                        capture_output=True,
                        timeout=max(60.0, args.timeout + 30),
                        check=False,
                    )
                    if browser.returncode:
                        detail = (browser.stderr or browser.stdout or "browser check failed")[-4000:]
                        raise RuntimeError(detail)
                    print(browser.stdout.strip())
                    browser_replay = runtime.replay(browser_cursor)
                    if not any(event.kind == "item.delta" for event in browser_replay.events):
                        raise RuntimeError("browser-submitted turn did not produce replayable deltas")

                if args.restart:
                    runtime.send(
                        session,
                        RESTART_PROMPT,
                        "real_appserver_owner_restart_message",
                    )
                    before_restart = runtime.capture(session)
                    before_restart_answers = [
                        text for role, text in before_restart["messages"] if role == "assistant"
                    ]
                    if any("OWNER_RESTART_DONE" in text for text in before_restart_answers):
                        raise RuntimeError("restart test turn settled before Owner disconnect")
                    if web_server is not None:
                        web_server.should_exit = True
                    if web_thread is not None:
                        web_thread.join(5)
                    web_server = None
                    web_thread = None
                    runtime.stop()
                    runtime = AppServerRuntime(
                        socket_path=socket_path,
                        registry_path=registry_path,
                        client_version="real-test-restarted",
                    )
                    runtime.start()
                    if not runtime.wait_ready(12):
                        raise RuntimeError("restarted Owner did not reconnect to the existing App Server")
                    restart_deadline = time.monotonic() + max(30.0, args.timeout)
                    restart_final = ""
                    while time.monotonic() < restart_deadline:
                        restart_capture = runtime.capture(session)
                        assistants = [
                            text
                            for role, text in restart_capture["messages"]
                            if role == "assistant"
                        ]
                        restart_final = assistants[-1] if assistants else ""
                        if (
                            restart_capture["snapshot"].get("lifecycle") == "idle"
                            and "OWNER_RESTART_DONE" in restart_final
                        ):
                            break
                        time.sleep(0.05)
                    else:
                        raise RuntimeError("Owner restart did not recover the in-flight final response")
                    if not jsonl_has_final(codex_home, restart_final):
                        raise RuntimeError("restarted Owner final did not converge to Codex JSONL")
                    print("real-appserver-owner-restart=PASS active_turn=preserved final=jsonl")

                runtime.close_session(session)
        finally:
            if web_server is not None:
                web_server.should_exit = True
            if web_thread is not None:
                web_thread.join(5)
            if runtime is not None:
                runtime.stop()
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
