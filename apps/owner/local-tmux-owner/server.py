#!/usr/bin/env python3
"""Local Tmux Owner: tiny HTTP bridge from mobile browser to a fixed tmux pane.

This server intentionally exposes only fixed tmux operations:
status, capture, send text, interrupt, approve, and navigation keys.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as _dt
from email import policy
from email.parser import BytesParser
import gzip
import hashlib
import hmac
import html as _html
import io
import json
import mmap
import os
import re
import secrets
import select
import shlex
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, NamedTuple

SHARED_DIR = Path(__file__).resolve().parents[2] / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
import pd_state
import workbench_state as wb_state
import urllib.error
import urllib.request
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

try:
    from rich.console import Console as RichConsole
    from rich.text import Text as RichText
except ImportError:  # pragma: no cover - runtime fallback for minimal environments
    RichConsole = None
    RichText = None

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
SHARED_STATIC_DIR = SHARED_DIR / "static"
RELEASE_FILE = APP_DIR.parent / "RELEASE"
AGENT_STATE_DB = Path(os.environ.get("FARYO_CODEX_STATE_DB", str(Path.home() / ".codex" / "state_5.sqlite"))).expanduser()
CODEX_SESSION_INDEX = Path(os.environ.get("FARYO_CODEX_SESSION_INDEX", str(Path.home() / ".codex" / "session_index.jsonl"))).expanduser()
DEFAULT_SESSION = "__faryo_no_default__"
DEFAULT_PORT = 8765
SHARED_STATIC_FILES = {
    "appearance.css": "text/css; charset=utf-8",
    "appearance.js": "text/javascript; charset=utf-8",
}
# Faryo must not change a terminal UI's geometry by default.  A positive
# --pane-width remains an explicit compatibility opt-in for terminal-only
# capture, but Codex always follows its real tmux clients.
DEFAULT_PANE_WIDTH = 0
FALLBACK_OWNER_LABEL = "TMUX"
MAX_SEND_CHARS = 120_000
PASTE_READY_TIMEOUT = 1.2
PASTE_READY_POLL_INTERVAL = 0.05
PASTE_READY_MIN_PROBE_CHARS = 8
PASTE_SETTLE_SECONDS = 0.12
SEND_ACCEPT_TIMEOUT = 2.2
SEND_ACCEPT_RETRY_DELAY = 0.18
SEND_KEY_MAX_ATTEMPTS = 3
SEND_DELIVERY_TTL_SECONDS = 48 * 60 * 60
SEND_DELIVERY_CLEANUP_INTERVAL_SECONDS = 60 * 60
CAPTURE_COMPACT_LINES = 320
CAPTURE_FULL_LINES = 800
CAPTURE_DEFAULT_LINES = CAPTURE_FULL_LINES
CAPTURE_MAX_LINES = CAPTURE_FULL_LINES
CODEX_LIVE_TAIL_LINES = 60
EVENT_STREAM_MAX_SECONDS = 75
EVENT_STREAM_MAX_CONNECTIONS = 16
EVENT_STREAM_HEARTBEAT_SECONDS = 10
RATE_LIMIT_CACHE_TTL = 120.0
CODEX_TRANSCRIPT_CACHE_TTL = 5.0
# Markdown source line count is a poor proxy for browser cost: one formula-heavy
# answer can contain hundreds of short lines while remaining only a few KB.  A
# soft line budget must therefore never make the conversation look as if all
# prior turns disappeared.  Keep a useful recent turn window, with a separate
# hard character ceiling for mobile payload safety.
CODEX_TRANSCRIPT_PAGE_TURNS = 12
CODEX_TRANSCRIPT_MIN_TURNS = CODEX_TRANSCRIPT_PAGE_TURNS
CODEX_TRANSCRIPT_CHAR_BUDGET = 512 * 1024
CODEX_ROLLOUT_CACHE_LINE_BUDGET = CAPTURE_MAX_LINES * 2
CODEX_ROLLOUT_CACHE_CHAR_BUDGET = 4 * 1024 * 1024
CODEX_ROLLOUT_CACHE_MIN_TURNS = CODEX_TRANSCRIPT_MIN_TURNS
CODEX_ROLLOUT_CACHE_MAX_PATHS = 16
CODEX_ROLLOUT_TAIL_SCAN_BYTES = 16 * 1024 * 1024
CODEX_ROLLOUT_MAX_CATCHUP_BYTES = 8 * 1024 * 1024
CODEX_HISTORY_PAGE_TURNS = CODEX_TRANSCRIPT_PAGE_TURNS
CODEX_HISTORY_MAX_PAGE_TURNS = 24
CODEX_HISTORY_PAGE_CHAR_BUDGET = 2 * 1024 * 1024
CODEX_HISTORY_PREVIEW_CHARS = 88
CODEX_HISTORY_INDEX_MAX_PATHS = CODEX_ROLLOUT_CACHE_MAX_PATHS
THREAD_COLUMNS = "id, title, rollout_path, tokens_used, model, reasoning_effort, cwd, updated_at, source, thread_source"
INTERACTIVE_CODEX_THREAD_SOURCES = {"cli", "vscode"}
AGENT_SESSION_LIST_LIMIT = 20
AGENT_SESSION_QUERY_LIMIT = 1000
EMPTY_MANAGED_SESSION_TTL_SECONDS = 60
MAX_MANAGED_AGENT_IDLE_SECONDS = 24 * 60 * 60
AGENT_START_READY_TIMEOUT = 15.0
START_DIRECTORY_MAX_ENTRIES = 160
RUNTIME_LOCK = threading.RLock()
RELEASE_VERSION_CACHE: str | None = None
FARYO_OWNER_DATA = Path(os.environ.get("FARYO_OWNER_DATA", str(Path.home() / ".faryo" / "owner" / "data"))).expanduser()
FILE_INBOX_ROOT = Path(os.environ.get("FARYO_OWNER_INBOX_DIR", str(FARYO_OWNER_DATA / "inbox"))).expanduser()
CACHE_ROOT = Path(os.environ.get("FARYO_OWNER_CACHE_DIR", str(FARYO_OWNER_DATA / "cache"))).expanduser()
LOGS_ROOT = Path(os.environ.get("FARYO_OWNER_LOGS_DIR", str(FARYO_OWNER_DATA / "logs"))).expanduser()
SEND_DELIVERY_ROOT = Path(os.environ.get("FARYO_OWNER_DELIVERY_DIR", str(FARYO_OWNER_DATA / "send-deliveries"))).expanduser()
MAX_ATTACHMENT_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_RETENTION_DAYS = 7
IMAGE_MIME_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heif",
}
DOCUMENT_MIME_SUFFIXES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/rtf": ".rtf",
}
ALLOWED_ATTACHMENT_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif",
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".odt", ".odp", ".ods", ".md", ".txt", ".csv", ".json", ".rtf",
}
PROJECT_ITEM_TYPES = wb_state.ITEM_TYPES
PROJECT_DONE_STATUSES = wb_state.DONE_STATUSES
PROJECT_ITEM_STAGES = wb_state.ITEM_STAGES
PROJECT_TERMINAL_STAGES = wb_state.TERMINAL_STAGES
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}
IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".heif": "image/heif",
}
LOCAL_FILE_CONTENT_TYPES = {
    ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".rtf": "application/rtf",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".bash": "text/plain; charset=utf-8",
    ".c": "text/plain; charset=utf-8",
    ".cc": "text/plain; charset=utf-8",
    ".cfg": "text/plain; charset=utf-8",
    ".cpp": "text/plain; charset=utf-8",
    ".css": "text/plain; charset=utf-8",
    ".go": "text/plain; charset=utf-8",
    ".h": "text/plain; charset=utf-8",
    ".hpp": "text/plain; charset=utf-8",
    ".html": "text/plain; charset=utf-8",
    ".ini": "text/plain; charset=utf-8",
    ".java": "text/plain; charset=utf-8",
    ".js": "text/plain; charset=utf-8",
    ".jsx": "text/plain; charset=utf-8",
    ".lean": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".py": "text/plain; charset=utf-8",
    ".rs": "text/plain; charset=utf-8",
    ".sh": "text/plain; charset=utf-8",
    ".sql": "text/plain; charset=utf-8",
    ".tex": "text/plain; charset=utf-8",
    ".toml": "text/plain; charset=utf-8",
    ".ts": "text/plain; charset=utf-8",
    ".tsx": "text/plain; charset=utf-8",
    ".xml": "text/plain; charset=utf-8",
    ".yaml": "text/plain; charset=utf-8",
    ".yml": "text/plain; charset=utf-8",
    ".zsh": "text/plain; charset=utf-8",
}
LOCAL_FILE_SUFFIXES = set(LOCAL_FILE_CONTENT_TYPES)
EXTERNAL_VIEWER_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".odp", ".ods", ".rtf"}
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
ANSI_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f]")
ANSI_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
HTML_CODE_RE = re.compile(r"<code[^>]*>(.*)</code>", re.S)
RICH_PRE_RE = re.compile(r"^\s*<pre\b[^>]*>(.*)</pre>\s*$", re.S)
STYLE_ATTR_RE = re.compile(r'\sstyle="([^"]*)"')
SEPARATOR_RE = re.compile(r"^[\s─━═\-—_]{20,}$")
SEPARATOR_OUTPUT_RE = re.compile(r"^\s*(?:[└│]\s*)?(?:\d+:)?[\s─━═\-—_]{4,}$")
LONG_SEPARATOR_RE = re.compile(r"[─━═]{20,}")
AGENT_BOUNDARY_RE = re.compile(r"^[\s─━═\-—_]*(Worked for .*?)[\s─━═\-—_]*$", re.I)
AGENT_PLACEHOLDER_RE = re.compile(r"^\s*[›>]\s*Write tests for @filename\s*$", re.I)
USER_PROMPT_RE = re.compile(r"^\s*›\s+")
# Codex uses `›` while idle and `»` while a turn or background startup is
# active.  Both glyphs identify the live composer; historical user messages
# continue to use `›` and are matched separately by USER_PROMPT_RE.
AGENT_INPUT_PROMPT_RE = re.compile(r"^\s*[›>»](?:\s|$)")
AGENT_META_RE = re.compile(r"^\s*((?:gpt|o\d)[\w.\- ]*)\s*·\s+(.+?)\s*$", re.I)
NO_AGENT_META_RE = re.compile(r"a^")
ROLLOUT_THREAD_ID_RE = re.compile(r"rollout-.*-(?P<id>[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl", re.I)
REASONING_EFFORT_SUFFIX_RE = re.compile(r"\b(?P<effort>low|medium|high|xhigh)\s*$", re.I)
FAST_STATUS_RE = re.compile(r"\bFast(?:\s+mode)?(?:\s+(?:is|set\s+to))?\s+(?P<state>on|off|true|false|enabled|disabled)\b", re.I)
SHELL_PREP_RE = re.compile(r"^(?:pwd|clear|ls(?:\s+[-\w./~]+)*|cd(?:\s+[-\w./~]+)?)$")
FAST_CONFIG_KEYS = {
    "auto-fast",
    "codex-auto-fast",
}
SESSION_GIT_PREFIXES = ("🌿", "✏️", "✏", "⚠️")
SESSION_GIT_ROOT_OPTION = "@faryo_git_root"
SESSION_TITLE_NOISE_RE = re.compile(r"^(?:📁 |Ctx |(?:gpt|o\d)[\w.\- ]+\s+(?:low|medium|high|xhigh)$)", re.I)
class AgentProfile(NamedTuple):
    key: str
    command: str
    source: str
    input_prompt_re: Any = AGENT_INPUT_PROMPT_RE
    user_prompt_re: Any = USER_PROMPT_RE
    meta_re: Any = AGENT_META_RE
    boundary_re: Any = AGENT_BOUNDARY_RE
    placeholder_re: Any = AGENT_PLACEHOLDER_RE


CODEX_PROFILE = AgentProfile("codex", "codex", "codex-cli")
RUNTIME_PROFILE = AgentProfile("runtime", "", "runtime", NO_AGENT_META_RE, NO_AGENT_META_RE, NO_AGENT_META_RE, NO_AGENT_META_RE, NO_AGENT_META_RE)
AGENT_PROFILES = (CODEX_PROFILE,)
AGENT_LAUNCH_COMMANDS = {profile.command for profile in AGENT_PROFILES}
AGENT_SOURCE_BY_COMMAND = {profile.command: profile.source for profile in AGENT_PROFILES}
BLACK_VALUES = {"#000", "#000000", "black", "rgb(0,0,0)", "rgb(0, 0, 0)"}
# Explicit terminal white is the light-theme twin of BLACK_VALUES: drop it so
# terminal text inherits the theme foreground instead of vanishing on light
# backgrounds.
WHITE_VALUES = {"#fff", "#ffffff", "white", "rgb(255,255,255)", "rgb(255, 255, 255)"}
USER_INPUT_COLOR = "var(--user-input-color, #CAD2FF)"
LOW_CONTRAST_TERMINAL_VALUES = {"#000080", "#0000aa", "#0000cd", "#0000ff", "blue"}
_rate_limit_cache: dict[str, Any] | None = None
_rate_limit_cache_at = 0.0
_rate_limit_lock = threading.Lock()
_rate_limit_refreshing = False
_codex_app_server_process: subprocess.Popen[str] | None = None
_codex_app_server_request_id = 0
_codex_app_server_lock = threading.Lock()
_codex_thread_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_codex_thread_cache_lock = threading.Lock()
_codex_rollout_cache: dict[str, dict[str, Any]] = {}
_codex_rollout_cache_lock = threading.Lock()
_codex_rollout_path_locks: dict[str, threading.Lock] = {}
_codex_history_cache: dict[str, dict[str, Any]] = {}
_codex_history_cache_lock = threading.Lock()
_codex_history_path_locks: dict[str, threading.Lock] = {}
_codex_session_index_cache: dict[str, str] = {}
_codex_session_index_signature: tuple[int, int, int, int] | None = None
_codex_session_index_lock = threading.Lock()
# Sending is serialized per tmux session because a pane has only one composer.
# Exact message-id locks keep reuse deterministic across sessions.  Both lock
# registries are reference-counted so unrelated sends cannot collide and idle
# entries do not accumulate for the lifetime of the Owner.
_send_delivery_lock = threading.RLock()
_send_session_locks: dict[str, dict[str, Any]] = {}
_send_message_locks: dict[str, dict[str, Any]] = {}
_send_deliveries: dict[str, dict[str, Any]] = {}
_send_delivery_cleanup_at = 0.0


@contextmanager
def scoped_send_delivery_lock(registry: dict[str, dict[str, Any]], key: str):
    with _send_delivery_lock:
        entry = registry.setdefault(key, {"lock": threading.RLock(), "references": 0})
        entry["references"] = int(entry["references"]) + 1
        lock = entry["lock"]
    try:
        with lock:
            yield
    finally:
        with _send_delivery_lock:
            entry["references"] = int(entry["references"]) - 1
            if entry["references"] == 0 and registry.get(key) is entry:
                registry.pop(key, None)


def send_session_delivery_lock(session: str):
    return scoped_send_delivery_lock(_send_session_locks, session)


def send_message_delivery_lock(delivery_id: str):
    return scoped_send_delivery_lock(_send_message_locks, delivery_id)


def short_path(path: str | None) -> str | None:
    if not path:
        return path
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~/" + path[len(home) + 1:]
    return path


def git_status(cwd: str | None) -> dict[str, Any] | None:
    if not cwd:
        return None
    top = run_cmd(["git", "-C", cwd, "rev-parse", "--show-toplevel"], timeout=2)
    if top.returncode != 0 or not top.stdout.strip():
        return None
    try:
        git_root = Path(top.stdout.strip()).expanduser().resolve()
    except OSError:
        return None
    if git_root == Path.home().resolve():
        return None
    res = run_cmd(["git", "-C", cwd, "status", "--short", "--branch"], timeout=2)
    if res.returncode != 0:
        return None
    lines = [line for line in res.stdout.splitlines() if line.strip()]
    head, body = (lines[0] if lines else ""), lines[1:]
    branch = head[3:].split("...", 1)[0].strip() if head.startswith("## ") else "git"
    detached = branch.startswith("HEAD ")
    changed = sum(line[:2] != "??" for line in body)
    untracked = sum(line[:2] == "??" for line in body)
    insertions = deletions = 0
    diff_res = run_cmd(["git", "-C", cwd, "diff", "--numstat", "HEAD", "--"], timeout=2)
    if diff_res.returncode != 0:
        diff_res = run_cmd(["git", "-C", cwd, "diff", "--numstat", "--"], timeout=2)
    if diff_res.returncode == 0:
        for row in diff_res.stdout.splitlines():
            parts = row.split("\t", 2)
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                insertions += int(parts[0])
                deletions += int(parts[1])
    marks = [label for label in (f"+{insertions}" if insertions else "", f"-{deletions}" if deletions else "", f"?{untracked}" if untracked else "", *(f"{arrow}{n}" for word, arrow in (("ahead", "↑"), ("behind", "↓")) for n in re.findall(rf"{word} (\d+)", head))) if label]
    if not detached and branch != "main":
        main_res = run_cmd(["git", "-C", cwd, "rev-list", "--left-right", "--count", "origin/main...HEAD"], timeout=2)
        if main_res.returncode == 0:
            behind_main, ahead_main = [int(value) for value in main_res.stdout.split()[:2]]
            marks.extend(label for label in (f"m+{ahead_main}" if ahead_main else "", f"m-{behind_main}" if behind_main else "") if label)
    clean = not changed and not untracked
    mark_text = (" " + " ".join(marks)) if marks else ""
    if detached:
        return {"state": "error", "label": f"⚠️ DETACHED{mark_text}", "title": "\n".join(lines[:12])}
    return {"state": "clean" if clean else "dirty", "label": f"{'🌿' if clean else '✏️'}{mark_text} {branch}", "title": "\n".join(lines[:12])}


def session_title_topic(value: Any, fallback: str = "Untitled session") -> str:
    labels = {owner_label(), "TXY", "HP", "PC", FALLBACK_OWNER_LABEL}
    lines = [line.strip() for line in str(value or "").replace("\r", "\n").split("\n") if line.strip()]
    topic = next((line for line in lines if line not in labels and not line.startswith(SESSION_GIT_PREFIXES) and not SESSION_TITLE_NOISE_RE.match(line)), "")
    return topic or fallback


def session_index_title(value: Any) -> str:
    return " ".join(str(value or "").replace("\r", "\n").split())


def session_git_label(cwd: str | None, cache: dict[str, str], active: bool = True) -> str:
    if not cwd or not active:
        return ""
    if cwd not in cache:
        cache[cwd] = str((git_status(cwd) or {}).get("label") or "")
    return cache[cwd]


def session_git_cwd(config: Config, session: str | None, cwd: str | None) -> str | None:
    return (tmux_session_option(config, session, SESSION_GIT_ROOT_OPTION) or cwd) if session else cwd


def env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None:
            return value
    return default


def default_owner_label() -> str:
    hostname = socket.gethostname().strip().lower()
    if not hostname:
        return FALLBACK_OWNER_LABEL
    if "hp" in hostname:
        return "HP"
    if hostname == "sl" or hostname.startswith("sl-") or hostname.endswith("-sl") or "-sl-" in hostname:
        return "PC"
    if "cloud" in hostname or "txy" in hostname:
        return "TXY"
    return (hostname.split(".", 1)[0][:16] or FALLBACK_OWNER_LABEL).upper()


def owner_label() -> str:
    label = env_value("FARYO_OWNER_LABEL", default="").strip()
    return label or default_owner_label()


def clean_owner_label(label: str | None) -> str | None:
    if not label:
        return None
    decoded = unquote(label)
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", decoded).strip()
    return cleaned[:32] or None


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


class OwnerError(Exception):
    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


class Config:
    def __init__(self, session: str, token: str, pane_width: int):
        self.session = session
        self.token = token
        self.pane_width = pane_width


def run_cmd(args: list[str], *, input_text: str | None = None, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
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
    )

def tmux(config: Config, args: list[str], *, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return run_cmd(["tmux", *args], timeout=timeout)


def tmux_target(config: Config) -> str:
    return config.session


def tmux_sessions(config: Config) -> list[str]:
    res = tmux(config, ["list-sessions", "-F", "#{session_name}"], timeout=2)
    if res.returncode != 0: return [config.session]
    return [line for line in res.stdout.splitlines() if line and line != "local-tmux-owner"]


def parse_sqlite_timestamp(value: Any) -> float:
    if isinstance(value, (int, float)): return float(value)
    try: return float(str(value or "").strip())
    except ValueError: pass
    try: return _dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).timestamp()
    except ValueError: return 0.0


def active_codex_thread_state(config: Config) -> tuple[dict[str, str], set[str]]:
    active: dict[str, str] = {}
    superseded: set[str] = set()
    for name in tmux_sessions(config):
        target = target_config(config, name)
        if agent_profile_in_pane(target) is not CODEX_PROFILE:
            continue
        # The live fd scan wins over the id recorded at dispatch: /new inside
        # a resumed session rotates the thread id, and the frozen id would
        # keep the Running badge on a transcript the pane no longer writes.
        cwd = get_pane_cwd(target)
        threads = active_agent_threads(target, cwd)
        if threads:
            thread_id = str(threads[0].get("id") or "")
            if thread_id: active[thread_id] = name
            superseded.update(str(row.get("id") or "") for row in threads[1:] if row.get("id"))
            continue
        session_id = tmux_session_option(config, name, "@faryo_agent_session_id")
        if tmux_session_option(config, name, "@faryo_agent_source") == CODEX_PROFILE.source and session_id:
            active[session_id] = name
    return active, superseded

def active_codex_thread_map(config: Config) -> dict[str, str]:
    active, _superseded = active_codex_thread_state(config)
    return active

def tmux_session_option(config: Config, session: str, key: str, value: str | None = None) -> str:
    if value is not None:
        tmux(config, ["set-option", "-q", "-t", session, key, value], timeout=2); return value
    res = tmux(config, ["show-options", "-qv", "-t", session, key], timeout=2); return res.stdout.strip() if res.returncode == 0 else ""

def agent_state_rows(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    if not AGENT_STATE_DB.exists(): return []
    try:
        conn = sqlite3.connect(f"file:{AGENT_STATE_DB.as_posix()}?mode=ro", uri=True, timeout=1)
        try:
            conn.row_factory = sqlite3.Row; return [dict(row) for row in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def codex_rows(where: str, params: tuple[Any, ...], limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
    sql = f"SELECT {THREAD_COLUMNS}, created_at FROM threads WHERE {where} ORDER BY updated_at DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = (*params, max(0, limit), max(0, offset))
    return agent_state_rows(sql, params)


def codex_count(where: str, params: tuple[Any, ...]) -> int:
    rows = agent_state_rows(f"SELECT COUNT(*) AS total FROM threads WHERE {where}", params)
    try:
        return max(0, int(rows[0].get("total") or 0)) if rows else 0
    except (TypeError, ValueError):
        return 0


def codex_session_index_titles() -> dict[str, str]:
    """Return Codex's explicit thread names without rescanning an unchanged index."""
    global _codex_session_index_cache, _codex_session_index_signature
    try:
        stat = CODEX_SESSION_INDEX.stat()
        signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    except OSError:
        with _codex_session_index_lock:
            _codex_session_index_cache = {}
            _codex_session_index_signature = None
        return {}
    with _codex_session_index_lock:
        if signature == _codex_session_index_signature:
            return dict(_codex_session_index_cache)
        titles: dict[str, str] = {}
        try:
            with CODEX_SESSION_INDEX.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    thread_id = str(row.get("id") or "").strip()
                    title = session_index_title(row.get("thread_name"))
                    if thread_id and title:
                        titles[thread_id] = title
        except OSError:
            return dict(_codex_session_index_cache)
        _codex_session_index_cache = titles
        _codex_session_index_signature = signature
        return dict(titles)


def codex_thread_title(thread: dict[str, Any], fallback: str = "Untitled session", index_titles: dict[str, str] | None = None) -> str:
    thread_id = str(thread.get("id") or "").strip()
    titles = index_titles if index_titles is not None else codex_session_index_titles()
    return titles.get(thread_id) or session_title_topic(thread.get("title"), fallback)


def codex_capture_session_metadata(thread_id: str) -> dict[str, str]:
    """Metadata that may change without changing the conversation transcript."""
    clean_id = str(thread_id or "").strip()
    if not clean_id:
        return {}
    payload = {"sessionId": clean_id}
    if title := codex_session_index_titles().get(clean_id):
        payload["sessionTitle"] = title
    return payload


def capture_event_digest(text: str, live_text: str, session_metadata: dict[str, str]) -> int:
    return hash((text, live_text, session_metadata.get("sessionTitle", "")))


def path_under_root(path_value: str | None, root_value: str | None) -> bool:
    try: return bool(path_value and root_value and Path(path_value).expanduser().resolve().is_relative_to(Path(root_value).expanduser().resolve()))
    except OSError: return False


def codex_session_item(config: Config, item: dict[str, Any], index_titles: dict[str, str], git_labels: dict[str, str], tmux_session: str = "") -> dict[str, Any]:
    cwd = str(item.get("cwd") or "")
    thread_id = str(item.get("id") or "")
    updated_ts = parse_sqlite_timestamp(item.get("updated_at"))
    fallback = short_path(cwd) or thread_id or "Untitled session"
    # A title supplied while launching a tmux session is only a startup
    # fallback.  `/rename` is authoritative once Codex appends an explicit
    # thread name to session_index.jsonl.
    startup_title = tmux_session_option(config, tmux_session, "@faryo_session_title") if tmux_session else ""
    title = index_titles.get(thread_id) or startup_title or codex_thread_title(item, fallback, index_titles)
    return {"id": thread_id, "title": title, "gitLabel": session_git_label(session_git_cwd(config, tmux_session, cwd), git_labels, bool(tmux_session)), "cwd": short_path(cwd), "createdAt": item.get("created_at") or "", "updatedAt": item.get("updated_at") or "", "updatedTs": updated_ts, "rolloutPath": item.get("rollout_path") or "", "model": item.get("model") or "", "reasoningEffort": item.get("reasoning_effort") or "", "source": "codex-cli", "tmuxSession": tmux_session, "active": bool(tmux_session), "managed": bool(tmux_session and managed_session(config, tmux_session)), "agentRunning": agent_session_running(config, tmux_session)}


def codex_history_filter(history_root: str | None, excluded_ids: set[str]) -> tuple[str, tuple[Any, ...]]:
    where = "source IN ('cli', 'vscode') AND thread_source = 'user' AND COALESCE(archived, 0) = 0"
    params: tuple[Any, ...] = ()
    if excluded_ids:
        placeholders = ",".join("?" for _ in excluded_ids)
        where += f" AND id NOT IN ({placeholders})"
        params += tuple(sorted(excluded_ids))
    if history_root is not None:
        try:
            root = str(Path(history_root).expanduser().resolve()).rstrip(os.sep) or os.sep
        except OSError:
            root = str(Path(history_root).expanduser()).rstrip(os.sep) or os.sep
        escaped = root.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        prefix = (escaped.rstrip(os.sep) + os.sep + "%") if root != os.sep else os.sep + "%"
        where += " AND (cwd = ? OR cwd LIKE ? ESCAPE '\\')"
        params += (root, prefix)
    return where, params


def codex_history_page(config: Config, limit: int, offset: int = 0, history_root: str | None = None, excluded_ids: set[str] | None = None) -> tuple[list[dict[str, Any]], int]:
    where, params = codex_history_filter(history_root, excluded_ids or set())
    total = codex_count(where, params)
    index_titles = codex_session_index_titles(); git_labels: dict[str, str] = {}
    rows = codex_rows(where, params, max(1, limit), max(0, offset))
    return [codex_session_item(config, item, index_titles, git_labels) for item in rows], total


def codex_history_items(config: Config, history_root: str | None = None) -> list[dict[str, Any]]:
    active, superseded = active_codex_thread_state(config); index_titles = codex_session_index_titles(); items = []; git_labels: dict[str, str] = {}
    for item in codex_rows("source IN ('cli', 'vscode') AND thread_source = 'user' AND COALESCE(archived, 0) = 0", ()):
        cwd = str(item.get("cwd") or "")
        if history_root is not None and not path_under_root(cwd, history_root): continue
        thread_id = str(item.get("id") or ""); tmux_session = active.get(thread_id, "")
        if thread_id in superseded: continue
        items.append(codex_session_item(config, item, index_titles, git_labels, tmux_session))
    return items


def active_agent_session_items(config: Config, history_root: str | None = None, codex_state: tuple[dict[str, str], set[str]] | None = None) -> tuple[list[dict[str, Any]], set[str]]:
    active_codex, superseded = codex_state or active_codex_thread_state(config)
    index_titles = codex_session_index_titles(); git_labels: dict[str, str] = {}; items: list[dict[str, Any]] = []
    rows_by_id: dict[str, dict[str, Any]] = {}
    if active_codex:
        placeholders = ",".join("?" for _ in active_codex)
        rows_by_id = {str(row.get("id") or ""): row for row in codex_rows(f"id IN ({placeholders})", tuple(active_codex))}
    seen_tmux: set[str] = set()
    for thread_id, tmux_session in active_codex.items():
        item = rows_by_id.get(thread_id)
        if not item:
            continue
        cwd = str(item.get("cwd") or "")
        if history_root is not None and not path_under_root(cwd, history_root):
            continue
        items.append(codex_session_item(config, item, index_titles, git_labels, tmux_session))
        seen_tmux.add(tmux_session)
    for name in tmux_sessions(config):
        if name in seen_tmux:
            continue
        target = target_config(config, name)
        profile = agent_profile_in_pane(target)
        if not profile:
            continue
        cwd = get_pane_cwd(target)
        if history_root is not None and not path_under_root(cwd, history_root):
            continue
        thread = active_agent_thread(target, cwd)
        thread_id = str((thread or {}).get("id") or tmux_session_option(config, name, "@faryo_agent_session_id") or name)
        updated_ts = session_created_ts(target); updated_at = iso_from_ts(updated_ts) if updated_ts else ""
        title = index_titles.get(thread_id) or tmux_session_option(config, name, "@faryo_session_title") or (codex_thread_title(thread, short_path(cwd) or name, index_titles) if thread else short_path(cwd) or name)
        items.append({"id": thread_id, "title": title, "gitLabel": session_git_label(session_git_cwd(config, name, cwd), git_labels), "cwd": short_path(cwd), "createdAt": "", "updatedAt": updated_at, "updatedTs": updated_ts, "rolloutPath": (thread or {}).get("rollout_path") or "", "model": (thread or {}).get("model") or "", "reasoningEffort": (thread or {}).get("reasoning_effort") or "", "source": profile.source, "tmuxSession": name, "active": True, "managed": managed_session(config, name), "agentRunning": agent_session_running(config, name)})
        seen_tmux.add(name)
    return sorted(items, key=lambda item: float(item.get("updatedTs") or 0), reverse=True), set(active_codex) | superseded


def agent_session_page(config: Config, limit: int, offset: int = 0, history_root: str | None = None) -> dict[str, Any]:
    page_limit = max(1, limit); start = max(0, offset)
    codex_state = active_codex_thread_state(config)
    active, excluded_ids = active_agent_session_items(config, history_root, codex_state)
    sessions, history_total = codex_history_page(config, page_limit, start, history_root, excluded_ids)
    return {"activeSessions": active, "sessions": sessions, "historyTotal": history_total, "historyOffset": start, "historyLimit": page_limit}


def agent_session_items(config: Config, history_root: str | None = None) -> list[dict[str, Any]]:
    items = codex_history_items(config, history_root)
    seen_tmux = {item.get("tmuxSession") for item in items if item.get("tmuxSession")}
    git_labels: dict[str, str] = {}; index_titles = codex_session_index_titles()
    for name in tmux_sessions(config):
        if name in seen_tmux: continue
        target = target_config(config, name)
        profile = agent_profile_in_pane(target)
        if not profile: continue
        cwd = get_pane_cwd(target)
        if history_root is not None and not path_under_root(cwd, history_root): continue
        thread = active_agent_thread(target, cwd) or {}; thread_id = str(thread.get("id") or name)
        updated_ts = session_created_ts(target); updated_at = iso_from_ts(updated_ts) if updated_ts else ""
        title = index_titles.get(thread_id) or tmux_session_option(config, name, "@faryo_session_title") or (codex_thread_title(thread, short_path(cwd) or name, index_titles) if thread else short_path(cwd) or name)
        items.append({"id": thread_id, "title": title, "gitLabel": session_git_label(session_git_cwd(config, name, cwd), git_labels), "cwd": short_path(cwd), "createdAt": "", "updatedAt": updated_at, "updatedTs": updated_ts, "rolloutPath": "", "model": "", "reasoningEffort": "", "source": profile.source, "tmuxSession": name, "active": True, "managed": managed_session(config, name), "agentRunning": agent_session_running(config, name)})
    return sorted(items, key=lambda item: float(item.get("updatedTs") or 0), reverse=True)


def codex_thread_by_id(thread_id: str) -> dict[str, Any] | None:
    rows = codex_rows("id = ? AND source IN ('cli', 'vscode') AND COALESCE(archived, 0) = 0", (thread_id,), 1)
    return rows[0] if rows else None


def agent_launch_executable(command: str) -> str:
    configured = os.environ.get("FARYO_CODEX_BIN", "").strip() if command == "codex" else ""
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise OwnerError("configured Codex executable is missing or not executable", HTTPStatus.BAD_GATEWAY)
        return str(path)
    executable = shutil.which(command)
    if not executable:
        raise OwnerError("Codex executable was not found in the Owner environment", HTTPStatus.BAD_GATEWAY)
    return executable


def codex_cli_argv(*args: str) -> list[str]:
    """Build a Codex command that also works outside a login shell."""
    executable = Path(agent_launch_executable("codex")).expanduser()
    try:
        resolved = executable.resolve()
    except OSError:
        resolved = executable
    if resolved.suffix == ".js":
        # NVM installs codex.js below <version>/lib/node_modules and node below
        # <version>/bin. A systemd/tmux Owner may not inherit that bin directory
        # in PATH, so invoke the matching runtime explicitly when available.
        for parent in resolved.parents:
            node = parent / "bin" / "node"
            if node.is_file() and os.access(node, os.X_OK):
                return [str(node), str(resolved), *args]
    return [str(executable), *args]


def codex_app_server_argv(*args: str) -> list[str]:
    return codex_cli_argv(*args)


def agent_login_shell() -> str:
    candidates = [
        os.environ.get("FARYO_AGENT_SHELL", "").strip(),
        os.environ.get("SHELL", "").strip(),
        shutil.which("zsh") or "",
        shutil.which("bash") or "",
        shutil.which("sh") or "",
        "/bin/bash",
        "/bin/sh",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser() if "/" in candidate else Path(shutil.which(candidate) or "")
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise OwnerError("no executable login shell is available", HTTPStatus.BAD_GATEWAY)


def next_faryo_session_name(config: Config) -> str:
    used = {
        int(match.group(1))
        for name in tmux_sessions(config)
        if (match := FARYO_MANAGED_SESSION_RE.fullmatch(name))
    }
    index = 1
    while index in used:
        index += 1
    return f"faryo{index}"


def start_agent_runtime(config: Config, cwd: Path, command: str, args: list[str], max_running: int = 0, wait_ready: bool = True, agent_id: str = "", title: str = "") -> str:
    with RUNTIME_LOCK:
        if max_running and active_agent_count(config) >= max_running: raise OwnerError("running agent limit reached", HTTPStatus.CONFLICT)
        name = next_faryo_session_name(config)
        shell = agent_login_shell()
        argv = codex_cli_argv(*args) if command == "codex" else [agent_launch_executable(command), *args]
        launch = f"{shlex.join(argv)}; exec {shlex.quote(shell)} -l"
        res = tmux(config, ["new-session", "-d", "-s", name, "-c", str(cwd), shell, "-lc", launch], timeout=5)
        if res.returncode != 0: raise OwnerError(res.stderr.strip() or "tmux session start failed", HTTPStatus.INTERNAL_SERVER_ERROR)
        if source := AGENT_SOURCE_BY_COMMAND.get(command): tmux_session_option(config, name, "@faryo_agent_source", source)
        if title:
            tmux_session_option(config, name, "@faryo_session_title", clean_session_title(title))
        if agent_id:
            tmux_session_option(config, name, "@faryo_agent_session_id", agent_id)
    if not wait_ready:
        return name
    target = Config(name, config.token, config.pane_width); deadline = time.monotonic() + AGENT_START_READY_TIMEOUT
    while time.monotonic() < deadline:
        if has_session(target) and codex_cli_in_pane(target): ensure_pane_width(target); return name
        time.sleep(0.2)
    tmux(config, ["kill-session", "-t", name], timeout=3)
    raise OwnerError("agent runtime did not become ready", HTTPStatus.BAD_GATEWAY)


def resume_codex_thread_session(config: Config, thread_id: str, max_running: int = 0, history_root: str | None = None) -> str:
    clean_id = clean_agent_session_id(thread_id)
    if not clean_id: raise OwnerError("invalid agent session id")
    with RUNTIME_LOCK:
        active = active_codex_thread_map(config).get(clean_id)
        if active: return active
        thread = codex_thread_by_id(clean_id)
        if not thread: raise OwnerError("agent session not found", HTTPStatus.NOT_FOUND)
        if history_root is not None and not path_under_root(str(thread.get("cwd") or ""), history_root): raise OwnerError("agent session not found", HTTPStatus.NOT_FOUND)
        cwd = Path(str(thread.get("cwd") or Path.home())).expanduser(); cwd = cwd if cwd.is_dir() else Path.home()
        return start_agent_runtime(config, cwd, "codex", ["resume", clean_id], max_running, agent_id=clean_id)

def resume_agent_session(config: Config, session_id: str, source: str, max_running: int = 0, history_root: str | None = None) -> str:
    if source == "codex-cli":
        return resume_codex_thread_session(config, session_id, max_running, history_root)
    raise OwnerError("unsupported agent source", HTTPStatus.BAD_REQUEST)

def target_config(config: Config, session: str | None) -> Config:
    if not session or session == config.session:
        return config
    if session not in tmux_sessions(config):
        raise OwnerError(f"tmux session not found: {session}", HTTPStatus.NOT_FOUND)
    return Config(session, config.token, config.pane_width)



def managed_session(config: Config, name: str | None) -> bool:
    if not name or name not in tmux_sessions(config):
        return False
    return bool(tmux_session_option(config, name, "@faryo_agent_source"))


def session_idle_seconds(config: Config) -> float:
    res = tmux(config, ["display-message", "-p", "-t", tmux_target(config), "#{session_activity}"], timeout=2)
    try: return max(0.0, time.time() - float(res.stdout.strip())) if res.returncode == 0 else 0.0
    except ValueError: return 0.0


def session_created_ts(config: Config) -> float:
    res = tmux(config, ["display-message", "-p", "-t", tmux_target(config), "#{session_created}"], timeout=2)
    try: return float(res.stdout.strip()) if res.returncode == 0 else 0.0
    except ValueError: return 0.0


def iso_from_ts(value: float) -> str:
    return _dt.datetime.fromtimestamp(value, _dt.timezone.utc).astimezone().isoformat(timespec="seconds") if value else ""


def cleanup_managed_sessions(config: Config, agent_idle_seconds: int = 0) -> None:
    for name in tmux_sessions(config):
        target = Config(name, config.token, config.pane_width)
        if not managed_session(config, name):
            continue
        profile = agent_profile_in_pane(target)
        has_agent = profile is not None
        idle = session_idle_seconds(target)
        if (not has_agent and idle >= EMPTY_MANAGED_SESSION_TTL_SECONDS) or (agent_idle_seconds and profile and agent_ready_for_input(target, profile) and idle >= agent_idle_seconds):
            tmux(config, ["kill-session", "-t", name], timeout=3)


def active_agent_count(config: Config) -> int:
    cleanup_managed_sessions(config)
    return sum(1 for name in tmux_sessions(config) if agent_in_pane(Config(name, config.token, config.pane_width)))


def bounded_max_running(payload: dict[str, Any]) -> int:
    return int(payload.get("max_running") or payload.get("maxRunning") or 0)


def agent_tail_ignorable(line: str, profile: AgentProfile) -> bool:
    return agent_meta_line(line, profile)


def agent_ready_for_input(config: Config, profile: AgentProfile = CODEX_PROFILE) -> bool:
    res = tmux(config, ["capture-pane", "-p", "-J", "-t", tmux_target(config), "-S", "-40"], timeout=3)
    if res.returncode != 0: return False
    text = CONTROL_RE.sub("", res.stdout.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if any("esc to interrupt" in line.lower() for line in lines[-12:]): return False
    while lines and agent_tail_ignorable(lines[-1].strip(), profile):
        lines.pop()
    return bool(lines and profile.input_prompt_re.match(lines[-1]))


def close_shell_session(config: Config, session: str | None) -> None:
    name = clean_tmux_session_name(session)
    if not managed_session(config, name):
        raise OwnerError("tmux session not found", HTTPStatus.NOT_FOUND)
    res = tmux(config, ["kill-session", "-t", name], timeout=3)
    if res.returncode != 0:
        raise OwnerError(res.stderr.strip() or "tmux kill-session failed", HTTPStatus.INTERNAL_SERVER_ERROR)


TMUX_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
FARYO_MANAGED_SESSION_RE = re.compile(r"^faryo([1-9][0-9]*)$")
CODEX_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
CLIENT_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,128}$")


def clean_tmux_session_name(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return value if TMUX_SESSION_NAME_RE.fullmatch(value) else None


def clean_agent_session_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return value if CODEX_THREAD_ID_RE.fullmatch(value) else None


def clean_client_message_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return value if CLIENT_MESSAGE_ID_RE.fullmatch(value) else None


def clean_agent_launch_command(value: str | None) -> str | None:
    command = Path(str(value or "").strip()).name.lower()
    return command if command in AGENT_LAUNCH_COMMANDS else None


def has_session(config: Config) -> bool:
    res = tmux(config, ["has-session", "-t", tmux_target(config)], timeout=2)
    return res.returncode == 0


def get_pane_pid(config: Config) -> int | None:
    res = tmux(config, ["display-message", "-p", "-t", tmux_target(config), "#{pane_pid}"], timeout=2)
    if res.returncode != 0:
        return None
    text = res.stdout.strip()
    return int(text) if text.isdigit() else None


def get_pane_width(config: Config) -> int | None:
    res = tmux(config, ["display-message", "-p", "-t", tmux_target(config), "#{pane_width}"], timeout=2)
    if res.returncode != 0:
        return None
    text = res.stdout.strip()
    return int(text) if text.isdigit() else None


def ensure_pane_width(config: Config) -> None:
    if config.pane_width <= 0 or not has_session(config):
        return
    # Codex compact chat is sourced from App Server, so widening its live TUI
    # no longer improves transcript fidelity.  More importantly,
    # resize-window switches tmux to manual sizing: a narrower attached client
    # would then view a wide Codex screen and lines would appear not to wrap.
    # Leave Codex windows under tmux/client size control.
    if codex_cli_in_pane(config):
        return
    current_width = get_pane_width(config)
    if current_width is not None and current_width >= config.pane_width:
        return
    res = tmux(config, ["resize-window", "-t", tmux_target(config), "-x", str(config.pane_width)], timeout=3)
    if res.returncode != 0:
        raise OwnerError(res.stderr.strip() or "tmux resize-window failed", HTTPStatus.INTERNAL_SERVER_ERROR)


def get_pane_current_command(config: Config) -> str | None:
    res = tmux(config, ["display-message", "-p", "-t", tmux_target(config), "#{pane_current_command}"], timeout=2)
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def get_pane_cwd(config: Config) -> str | None:
    res = tmux(config, ["display-message", "-p", "-t", tmux_target(config), "#{pane_current_path}"], timeout=2)
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def process_table() -> dict[int, tuple[int, str]]:
    res = run_cmd(["ps", "-eo", "pid=,ppid=,args="], timeout=3)
    table: dict[int, tuple[int, str]] = {}
    if res.returncode != 0:
        return table
    for line in res.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        cmd = parts[2] if len(parts) > 2 else ""
        table[pid] = (ppid, cmd)
    return table


def descendants(root_pid: int, table: dict[int, tuple[int, str]]) -> list[tuple[int, str]]:
    children: dict[int, list[int]] = {}
    for pid, (ppid, _cmd) in table.items():
        children.setdefault(ppid, []).append(pid)
    out: list[tuple[int, str]] = []
    stack = list(children.get(root_pid, []))
    while stack:
        pid = stack.pop()
        cmd = table.get(pid, (0, ""))[1]
        out.append((pid, cmd))
        stack.extend(children.get(pid, []))
    return out


def agent_in_pane(config: Config) -> bool:
    return agent_profile_in_pane(config) is not None


def agent_session_running(config: Config, session: str | None) -> bool:
    if not session:
        return False
    try:
        target = target_config(config, session)
        profile = agent_profile_in_pane(target)
        return bool(profile and not agent_ready_for_input(target, profile))
    except OwnerError:
        return False


def agent_profile_in_pane(config: Config) -> AgentProfile | None:
    pane_pid = get_pane_pid(config)
    if pane_pid is None:
        return None
    pane_cmd = get_pane_current_command(config) or ""
    children = descendants(pane_pid, process_table())
    for profile in AGENT_PROFILES:
        if agent_profile_matches_cmd(profile, pane_cmd) or any(agent_profile_matches_cmd(profile, cmd) for _pid, cmd in children):
            return profile
    return None


def agent_profile_matches_cmd(profile: AgentProfile, cmd: str) -> bool:
    return profile is CODEX_PROFILE and is_codex_cli_cmd(cmd)


def codex_cli_in_pane(config: Config) -> bool:
    pane_pid = get_pane_pid(config)
    if pane_pid is None:
        return False
    pane_cmd = get_pane_current_command(config) or ""
    if agent_profile_matches_cmd(CODEX_PROFILE, pane_cmd):
        return True
    return any(agent_profile_matches_cmd(CODEX_PROFILE, cmd) for _pid, cmd in descendants(pane_pid, process_table()))


def is_codex_cli_cmd(cmd: str) -> bool:
    lowered = cmd.lower()
    if "playwright-mcp" in lowered:
        return False
    return "codex" in lowered and ("@openai/codex" in lowered or "/codex" in lowered or "bin/codex" in lowered or lowered.strip() == "codex")


def clean_capture(text: str, *, strip_input_tail: bool = True, profile: AgentProfile = CODEX_PROFILE) -> str:
    text = CONTROL_RE.sub("", text)
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    normalized: list[str] = []
    blank_count = 0
    for line in lines:
        if profile.placeholder_re.match(line):
            blank_count += 1
            if blank_count <= 1:
                normalized.append("")
            continue

        match = profile.boundary_re.match(line.strip())
        if match:
            normalized.append(match.group(1).strip())
            blank_count = 0
            continue
        if SEPARATOR_RE.match(line.strip()) or SEPARATOR_OUTPUT_RE.match(line) or LONG_SEPARATOR_RE.search(line):
            continue

        if not line.strip():
            blank_count += 1
            if blank_count <= 1:
                normalized.append("")
            continue

        blank_count = 0
        normalized.append(line)
    lines = strip_agent_input_tail(normalized, lambda line: line, profile) if strip_input_tail else normalized
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def agent_meta_line(line: str, profile: AgentProfile = CODEX_PROFILE) -> tuple[str, str] | None:
    match = profile.meta_re.match(line)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def strip_agent_input_tail(lines: list[str], plain: Callable[[str], str], profile: AgentProfile = CODEX_PROFILE) -> list[str]:
    end = len(lines)
    while end and not plain(lines[end - 1]).strip():
        end -= 1
    if not end:
        return lines

    scan_end = end
    while scan_end and agent_tail_ignorable(plain(lines[scan_end - 1]).strip(), profile):
        scan_end -= 1
        while scan_end and not plain(lines[scan_end - 1]).strip():
            scan_end -= 1

    prompt_index: int | None = None
    search_start = max(0, scan_end - 12)
    for index in range(scan_end - 1, search_start - 1, -1):
        line = plain(lines[index])
        if profile.input_prompt_re.match(line):
            prompt_index = index
            break

    if prompt_index is None:
        return lines
    if any(plain(line).strip() for line in lines[prompt_index + 1 : scan_end]):
        return lines
    return lines[:prompt_index]


def strip_agent_meta_lines(text: str, profile: AgentProfile = CODEX_PROFILE) -> str:
    lines = [line for line in text.split("\n") if not agent_meta_line(line, profile)]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def latest_agent_meta(text: str, profile: AgentProfile = CODEX_PROFILE) -> tuple[str, str] | None:
    for line in reversed(text.splitlines()):
        meta = agent_meta_line(line, profile)
        if meta:
            return meta
    return None


def meta_cwd_path(value: str | None) -> str | None:
    return str(value).split(" · ", 1)[0].strip() if value else None


def reasoning_effort_from_model_status(text: str | None) -> str | None:
    if not text:
        return None
    match = REASONING_EFFORT_SUFFIX_RE.search(text.strip())
    return match.group("effort").lower() if match else None


def normalize_fast_state(value: str | bool | None) -> str | None:
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"on", "true", "enabled", "yes", "1"}:
        return "on"
    if normalized in {"off", "false", "disabled", "no", "0"}:
        return "off"
    return None


def latest_fast_status(text: str) -> str | None:
    status = None
    for match in FAST_STATUS_RE.finditer(text):
        status = normalize_fast_state(match.group("state"))
    return status


def find_fast_config_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).replace("_", "-").lower()
            if normalized_key in FAST_CONFIG_KEYS:
                state = normalize_fast_state(child)
                if state:
                    return state
            state = find_fast_config_value(child)
            if state:
                return state
    elif isinstance(value, list):
        for child in value:
            state = find_fast_config_value(child)
            if state:
                return state
    return None


def configured_fast_status() -> str | None:
    config_path = Path.home() / ".codex" / "config.toml"
    try:
        with config_path.open("rb") as fh:
            config = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return find_fast_config_value(config)


def rollout_thread_id_from_path(value: str) -> str | None:
    match = ROLLOUT_THREAD_ID_RE.search(Path(value).name) or ROLLOUT_THREAD_ID_RE.search(value)
    return match.group("id") if match else None


def proc_rollout_thread_ids(pid: int) -> list[str]:
    fd_dir = Path("/proc") / str(pid) / "fd"
    thread_ids: list[str] = []
    try:
        entries = list(fd_dir.iterdir())
    except OSError:
        return thread_ids
    for entry in entries:
        try:
            target = os.readlink(entry).removesuffix(" (deleted)")
        except OSError:
            continue
        if thread_id := rollout_thread_id_from_path(target):
            thread_ids.append(thread_id)
    return thread_ids


def lsof_rollout_thread_ids(pid: int) -> list[str]:
    if not shutil.which("lsof"):
        return []
    res = run_cmd(["lsof", "-nP", "-p", str(pid)], timeout=2)
    if res.returncode != 0:
        return []
    return [thread_id for line in res.stdout.splitlines() if (thread_id := rollout_thread_id_from_path(line))]


def open_rollout_thread_ids(pid: int) -> list[str]:
    return proc_rollout_thread_ids(pid) or lsof_rollout_thread_ids(pid)


def active_agent_threads(config: Config, cwd: str | None) -> list[dict[str, Any]]:
    pane_pid = get_pane_pid(config)
    if pane_pid is None or not AGENT_STATE_DB.exists():
        return []

    process_ids: list[int] = []
    if agent_profile_matches_cmd(CODEX_PROFILE, get_pane_current_command(config) or ""):
        process_ids.append(pane_pid)
    process_ids.extend(pid for pid, cmd in descendants(pane_pid, process_table()) if agent_profile_matches_cmd(CODEX_PROFILE, cmd))

    thread_ids = list(dict.fromkeys(tid for pid in process_ids for tid in open_rollout_thread_ids(pid)))
    if not thread_ids:
        return []

    placeholders = ",".join("?" for _ in thread_ids)
    rows = agent_state_rows(f"SELECT {THREAD_COLUMNS} FROM threads WHERE id IN ({placeholders})", tuple(thread_ids))

    interactive_rows = [dict(row) for row in rows if row.get("source") in INTERACTIVE_CODEX_THREAD_SOURCES and row.get("thread_source") == "user"]
    matches = [row for row in interactive_rows if cwd is None or row["cwd"] == cwd]
    return sorted(matches or interactive_rows, key=lambda row: parse_sqlite_timestamp(row.get("updated_at")), reverse=True)

def active_agent_thread(config: Config, cwd: str | None) -> dict[str, Any] | None:
    threads = active_agent_threads(config, cwd)
    if threads:
        thread = threads[0]
        thread_id = str(thread.get("id") or "")
        if thread_id and has_session(config):
            tmux_session_option(config, config.session, "@faryo_agent_source", CODEX_PROFILE.source)
            tmux_session_option(config, config.session, "@faryo_agent_session_id", thread_id)
        return thread

    # Codex may close the rollout file while idle. Reuse the last thread id
    # observed while the pane was active so structured clients do not fall
    # back to the lossy terminal screen between turns.
    if not codex_cli_in_pane(config):
        return None
    thread_id = tmux_session_option(config, config.session, "@faryo_agent_session_id")
    thread = codex_thread_by_id(thread_id) if thread_id else None
    if not thread:
        return None
    thread_cwd = str(thread.get("cwd") or "")
    return thread if cwd is None or not thread_cwd or thread_cwd == cwd else None


def latest_context_usage(history_path: str | None) -> dict[str, int | float] | None:
    state = codex_rollout_state(history_path)
    usage = state.get("contextUsage") if state else None
    return dict(usage) if isinstance(usage, dict) else None


def codex_context_usage_from_info(latest_info: Any) -> dict[str, int | float] | None:
    if not isinstance(latest_info, dict):
        return None
    try:
        last_usage = latest_info.get("last_token_usage")
        if not isinstance(last_usage, dict):
            return None
        input_tokens = int(last_usage.get("input_tokens") or 0)
        output_tokens = int(last_usage.get("output_tokens") or 0)
        used_tokens = int(last_usage.get("total_tokens") or (input_tokens + output_tokens))
        context_window = int(latest_info.get("model_context_window") or 0)
    except (TypeError, ValueError):
        return None
    if used_tokens <= 0 or context_window <= 0:
        return None

    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "usedTokens": used_tokens,
        "contextWindow": context_window,
        "contextWindowSource": "agent-reported",
        "percent": round((used_tokens / context_window) * 100, 1),
    }


def codex_rollout_context_usage(event: Any) -> dict[str, int | float] | None:
    if not isinstance(event, dict):
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    return codex_context_usage_from_info(payload.get("info"))


def send_app_server_message(process: subprocess.Popen[str], message: dict[str, Any]) -> bool:
    if process.stdin is None:
        return False
    try:
        process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        process.stdin.flush()
    except OSError:
        return False
    return True


def read_app_server_message(process: subprocess.Popen[str], deadline: float) -> dict[str, Any] | None:
    if process.stdout is None:
        return None

    remaining = deadline - time.monotonic()
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


def _stop_codex_app_server_locked() -> None:
    global _codex_app_server_process
    process = _codex_app_server_process
    _codex_app_server_process = None
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


def stop_codex_app_server() -> None:
    with _codex_app_server_lock:
        _stop_codex_app_server_locked()


def _start_codex_app_server_locked(timeout: float) -> subprocess.Popen[str] | None:
    global _codex_app_server_process, _codex_app_server_request_id
    process = _codex_app_server_process
    if process is not None and process.poll() is None:
        return process
    _stop_codex_app_server_locked()
    try:
        process = subprocess.Popen(
            codex_app_server_argv("app-server", "--listen", "stdio://"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    _codex_app_server_process = process
    _codex_app_server_request_id += 1
    request_id = _codex_app_server_request_id
    if not send_app_server_message(
        process,
        {
            "id": request_id,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "local-tmux-owner", "title": "Faryo Owner", "version": release_version() or "0"},
                "capabilities": {},
            },
        },
    ):
        _stop_codex_app_server_locked()
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = read_app_server_message(process, deadline)
        if message is None:
            break
        if message.get("id") != request_id:
            continue
        if isinstance(message.get("result"), dict):
            if not send_app_server_message(process, {"method": "initialized", "params": {}}):
                break
            return process
        break
    _stop_codex_app_server_locked()
    return None


def codex_app_server_request(method: str, params: dict[str, Any], timeout: float = 2.5) -> dict[str, Any] | None:
    global _codex_app_server_request_id
    with _codex_app_server_lock:
        for _attempt in range(2):
            process = _start_codex_app_server_locked(timeout)
            if process is None:
                continue
            _codex_app_server_request_id += 1
            request_id = _codex_app_server_request_id
            if not send_app_server_message(process, {"id": request_id, "method": method, "params": params}):
                _stop_codex_app_server_locked()
                continue
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                message = read_app_server_message(process, deadline)
                if message is None:
                    break
                if message.get("id") != request_id:
                    continue
                result = message.get("result")
                return result if isinstance(result, dict) else None
            _stop_codex_app_server_locked()
    return None


def cached_codex_thread(thread_id: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _codex_thread_cache_lock:
        cached = _codex_thread_cache.get(thread_id)
        if cached and now - cached[0] < CODEX_TRANSCRIPT_CACHE_TTL:
            return cached[1]

    # Never hold the cache lock during an app-server round trip. A large
    # thread/read can otherwise block structured capture for every session.
    result = codex_app_server_request("thread/read", {"threadId": thread_id, "includeTurns": True})
    thread = result.get("thread") if isinstance(result, dict) else None
    if not isinstance(thread, dict):
        # A stale structured transcript is preferable to a lossy tmux fallback
        # while the app-server is restarting or temporarily busy.
        return cached[1] if cached else None
    with _codex_thread_cache_lock:
        _codex_thread_cache[thread_id] = (time.monotonic(), thread)
    return thread


def codex_user_message_text(item: dict[str, Any]) -> str:
    values: list[str] = []
    for content in item.get("content") or []:
        if not isinstance(content, dict):
            continue
        if text := str(content.get("text") or "").strip():
            values.append(text)
        elif path := str(content.get("path") or content.get("url") or "").strip():
            values.append(f"Attachment: {path}")
    return "\n".join(values).strip()


def turn_exceeds_recent_budget(
    selected_count: int,
    used_lines: int,
    used_chars: int,
    turn_lines: int,
    turn_chars: int,
    *,
    line_budget: int,
    char_budget: int,
    min_turns: int,
) -> bool:
    """Apply a soft line budget, a minimum turn window, and a hard char cap."""
    if selected_count <= 0:
        return False
    if used_chars + turn_chars > char_budget:
        return True
    return selected_count >= min_turns and used_lines + turn_lines > line_budget


def codex_thread_transcript(thread: dict[str, Any], max_lines: int) -> str:
    turns: list[str] = []
    for turn in thread.get("turns") or []:
        if not isinstance(turn, dict):
            continue
        messages: list[str] = []
        for item in turn.get("items") or []:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "userMessage":
                if text := codex_user_message_text(item):
                    messages.append(f"› {text}")
            elif item_type == "agentMessage":
                if text := str(item.get("text") or "").strip():
                    messages.append(f"• {text}")
            elif item_type == "plan":
                if text := str(item.get("text") or "").strip():
                    messages.append(f"• Updated Plan\n{text}")
        if messages:
            turns.append("\n\n".join(messages))

    selected: list[str] = []
    used_lines = 0
    used_chars = 0
    for turn in reversed(turns):
        if len(selected) >= CODEX_TRANSCRIPT_PAGE_TURNS:
            break
        turn_lines = turn.count("\n") + 1
        turn_chars = len(turn)
        if turn_exceeds_recent_budget(
            len(selected),
            used_lines,
            used_chars,
            turn_lines,
            turn_chars,
            line_budget=max_lines,
            char_budget=CODEX_TRANSCRIPT_CHAR_BUDGET,
            min_turns=CODEX_TRANSCRIPT_MIN_TURNS,
        ):
            break
        selected.append(turn)
        used_lines += turn_lines
        used_chars += turn_chars
    return "\n\n".join(reversed(selected)).strip()


def codex_rollout_message(event: Any) -> tuple[str, str] | None:
    """Extract one displayable user/assistant message from a Codex rollout."""
    if not isinstance(event, dict) or event.get("type") != "response_item":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "message":
        return None
    role = str(payload.get("role") or "")
    if role not in {"user", "assistant"}:
        return None

    values: list[str] = []
    for item in payload.get("content") or []:
        if not isinstance(item, dict):
            continue
        content_type = str(item.get("type") or "")
        if content_type in {"input_text", "output_text", "text"}:
            if text := str(item.get("text") or "").strip():
                values.append(text)
        elif role == "user":
            if path := str(item.get("path") or item.get("url") or "").strip():
                values.append(f"Attachment: {path}")
    text = "\n".join(values).strip()
    return (role, text) if text else None


def codex_history_preview(text: str, max_chars: int = CODEX_HISTORY_PREVIEW_CHARS) -> str:
    compact = " ".join(str(text or "").split()) or "Untitled question"
    limit = max(8, int(max_chars))
    return compact if len(compact) <= limit else compact[:limit - 1] + "…"


def codex_history_revision(identity: tuple[int, ...]) -> str:
    value = ":".join(str(part) for part in identity).encode("ascii")
    return hashlib.sha256(value).hexdigest()[:16]


def codex_history_cursor(revision: str, before: int) -> str:
    return f"{revision}.{max(0, int(before)):x}"


def decode_codex_history_cursor(cursor: str, revision: str) -> int:
    match = re.fullmatch(r"([0-9a-f]{16})\.([0-9a-f]+)", str(cursor or "").strip().lower())
    if not match:
        raise OwnerError("invalid conversation history cursor")
    if not secrets.compare_digest(match.group(1), revision):
        raise OwnerError("conversation history cursor expired", HTTPStatus.CONFLICT)
    return int(match.group(2), 16)


def store_codex_history_cache(key: str, state: dict[str, Any]) -> None:
    with _codex_history_cache_lock:
        _codex_history_cache.pop(key, None)
        _codex_history_cache[key] = state
        while len(_codex_history_cache) > CODEX_HISTORY_INDEX_MAX_PATHS:
            _codex_history_cache.pop(next(iter(_codex_history_cache)))


def cached_codex_history_state(key: str) -> dict[str, Any] | None:
    with _codex_history_cache_lock:
        state = _codex_history_cache.pop(key, None)
        if state is not None:
            _codex_history_cache[key] = state
        return state


def copy_codex_history_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity": state.get("identity"),
        "revision": state.get("revision"),
        "offset": int(state.get("offset") or 0),
        "turns": [
            {
                "index": int(turn.get("index") or 0),
                "key": str(turn.get("key") or ""),
                "preview": str(turn.get("preview") or ""),
                "records": [tuple(record) for record in turn.get("records") or []],
            }
            for turn in state.get("turns") or []
        ],
    }


def append_codex_history_index(path: Path, state: dict[str, Any], target_size: int) -> None:
    offset = int(state.get("offset") or 0)
    complete_offset = offset
    turns = state.setdefault("turns", [])
    revision = str(state.get("revision") or "")
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            while handle.tell() < target_size:
                start = handle.tell()
                raw_line = handle.readline(target_size - start)
                if not raw_line.endswith(b"\n"):
                    break
                complete_offset = handle.tell()
                message, _usage = parse_codex_rollout_event(raw_line.rstrip(b"\n"))
                if message is None:
                    continue
                role, text = message
                if role == "user":
                    index = len(turns)
                    turns.append({
                        "index": index,
                        "key": f"q-{revision}-{index:x}",
                        "preview": codex_history_preview(text),
                        "records": [],
                    })
                if turns:
                    turns[-1]["records"].append((start, complete_offset))
    except OSError:
        return
    state["offset"] = complete_offset


def codex_history_state(history_path: str | None) -> dict[str, Any] | None:
    if not history_path:
        return None
    path = Path(history_path).expanduser()
    key = str(path)
    with _codex_history_cache_lock:
        path_lock = _codex_history_path_locks.setdefault(key, threading.Lock())
    with path_lock:
        cached = cached_codex_history_state(key)
        try:
            stat = path.stat()
        except OSError:
            return copy_codex_history_state(cached) if cached else None
        identity = (stat.st_dev, stat.st_ino)
        offset = int(cached.get("offset") or 0) if cached else 0
        reset_existing = cached is not None and (cached.get("identity") != identity or stat.st_size < offset)
        if cached is None or reset_existing:
            revision_seed = (*identity, stat.st_mtime_ns, stat.st_size) if reset_existing else identity
            cached = {
                "identity": identity,
                "revision": codex_history_revision(revision_seed),
                "offset": 0,
                "turns": [],
            }
        if stat.st_size > int(cached.get("offset") or 0):
            append_codex_history_index(path, cached, stat.st_size)
        store_codex_history_cache(key, cached)
        return copy_codex_history_state(cached)


def codex_history_turn_text(handle: Any, turn: dict[str, Any]) -> str:
    blocks: list[str] = []
    for start, end in turn.get("records") or []:
        try:
            handle.seek(int(start))
            raw_line = handle.read(max(0, int(end) - int(start))).rstrip(b"\n")
        except OSError:
            continue
        message, _usage = parse_codex_rollout_event(raw_line)
        if message is None:
            continue
        role, text = message
        blocks.append(f"› {text}" if role == "user" else f"• {text}")
    return "\n\n".join(blocks).strip()


def codex_conversation_history_page(
    history_path: str | None,
    *,
    limit: int = CODEX_HISTORY_PAGE_TURNS,
    cursor: str = "",
    around: int | None = None,
) -> dict[str, Any]:
    state = codex_history_state(history_path)
    if not state or not history_path:
        raise OwnerError("structured conversation history is unavailable", HTTPStatus.NOT_FOUND)
    revision = str(state.get("revision") or "")
    turns = list(state.get("turns") or [])
    total = len(turns)
    page_limit = max(1, min(int(limit), CODEX_HISTORY_MAX_PAGE_TURNS))
    if cursor and around is not None:
        raise OwnerError("choose either a history cursor or an around index")
    if around is not None:
        if around < 0 or around >= total:
            raise OwnerError("conversation history index out of range")
        start = max(0, around - page_limit // 2)
        end = min(total, start + page_limit)
        start = max(0, end - page_limit)
    else:
        end = decode_codex_history_cursor(cursor, revision) if cursor else total
        end = max(0, min(total, end))
        start = max(0, end - page_limit)

    selected = turns[start:end]
    path = Path(history_path).expanduser()
    rendered: list[dict[str, Any]] = []
    try:
        with path.open("rb") as handle:
            for turn in selected:
                rendered.append({
                    "index": int(turn["index"]),
                    "key": str(turn["key"]),
                    "preview": str(turn["preview"]),
                    "text": codex_history_turn_text(handle, turn),
                })
    except OSError as exc:
        raise OwnerError("structured conversation history is unavailable", HTTPStatus.NOT_FOUND) from exc

    target_index = around if around is not None else max(start, end - 1)
    while len(rendered) > 1 and sum(len(item["text"]) for item in rendered) > CODEX_HISTORY_PAGE_CHAR_BUDGET:
        if around is None:
            rendered.pop(0)
        elif abs(rendered[0]["index"] - target_index) >= abs(rendered[-1]["index"] - target_index):
            rendered.pop(0)
        else:
            rendered.pop()
    if rendered:
        start = int(rendered[0]["index"])
        end = int(rendered[-1]["index"]) + 1

    return {
        "ok": True,
        "source": "codex-jsonl",
        "revision": revision,
        "totalTurns": total,
        "start": start,
        "end": end,
        "hasOlder": start > 0,
        "hasNewer": end < total,
        "olderCursor": codex_history_cursor(revision, start) if start > 0 else "",
        "newerCursor": codex_history_cursor(revision, min(total, end + page_limit)) if end < total else "",
        "questions": [
            {"index": int(turn["index"]), "key": str(turn["key"]), "preview": str(turn["preview"])}
            for turn in turns
        ],
        "turns": rendered,
        "pageChars": sum(len(item["text"]) for item in rendered),
        "oversized": any(len(item["text"]) > CODEX_HISTORY_PAGE_CHAR_BUDGET for item in rendered),
        "updatedAt": now_iso(),
    }


def codex_history_page_for_config(
    config: Config,
    *,
    limit: int = CODEX_HISTORY_PAGE_TURNS,
    cursor: str = "",
    around: int | None = None,
) -> dict[str, Any]:
    cwd = get_pane_cwd(config)
    thread = active_agent_thread(config, cwd)
    history_path = str(thread.get("rollout_path") or "") if thread else ""
    return codex_conversation_history_page(history_path, limit=limit, cursor=cursor, around=around)


def bounded_codex_rollout_messages(messages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Keep recent complete turns within explicit line and character budgets."""
    turns: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for role, text in messages:
        if role == "user" and current:
            turns.append(current)
            current = []
        current.append((role, text))
    if current:
        turns.append(current)

    selected: list[list[tuple[str, str]]] = []
    used_lines = 0
    used_chars = 0
    for turn in reversed(turns):
        if len(selected) >= CODEX_TRANSCRIPT_PAGE_TURNS:
            break
        turn_lines = sum(text.count("\n") + 1 for _role, text in turn)
        turn_chars = sum(len(text) for _role, text in turn)
        if turn_exceeds_recent_budget(
            len(selected),
            used_lines,
            used_chars,
            turn_lines,
            turn_chars,
            line_budget=CODEX_ROLLOUT_CACHE_LINE_BUDGET,
            char_budget=CODEX_ROLLOUT_CACHE_CHAR_BUDGET,
            min_turns=CODEX_ROLLOUT_CACHE_MIN_TURNS,
        ):
            break
        selected.append(turn)
        used_lines += turn_lines
        used_chars += turn_chars
    return [message for turn in reversed(selected) for message in turn]


def store_codex_rollout_cache(key: str, state: dict[str, Any]) -> None:
    """Store a most-recently-used bounded set of rollout states."""
    with _codex_rollout_cache_lock:
        _codex_rollout_cache.pop(key, None)
        _codex_rollout_cache[key] = state
        while len(_codex_rollout_cache) > CODEX_ROLLOUT_CACHE_MAX_PATHS:
            _codex_rollout_cache.pop(next(iter(_codex_rollout_cache)))


def cached_codex_rollout_state(key: str) -> dict[str, Any] | None:
    with _codex_rollout_cache_lock:
        state = _codex_rollout_cache.pop(key, None)
        if state is not None:
            _codex_rollout_cache[key] = state
        return state


def parse_codex_rollout_event(raw_line: bytes) -> tuple[tuple[str, str] | None, dict[str, int | float] | None]:
    try:
        event = json.loads(raw_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    return codex_rollout_message(event), codex_rollout_context_usage(event)


def initial_codex_rollout_state(path: Path, identity: tuple[int, int]) -> dict[str, Any]:
    """Build a bounded state by scanning complete JSONL records from the tail."""
    messages_reversed: list[tuple[str, str]] = []
    context_usage: dict[str, int | float] | None = None
    line_budget = 0
    char_budget = 0
    turn_count = 0
    complete_end = 0
    try:
        with path.open("rb") as fh:
            if os.fstat(fh.fileno()).st_size <= 0:
                return {"identity": identity, "offset": 0, "messages": [], "contextUsage": None}
            with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                size = len(mapped)
                if size <= 0:
                    return {"identity": identity, "offset": 0, "messages": [], "contextUsage": None}
                if mapped[size - 1] == 0x0A:
                    complete_end = size
                else:
                    final_newline = mapped.rfind(b"\n", 0, size)
                    if final_newline < 0:
                        return {"identity": identity, "offset": 0, "messages": [], "contextUsage": None}
                    complete_end = final_newline + 1

                scan_floor = max(0, complete_end - CODEX_ROLLOUT_TAIL_SCAN_BYTES)
                cursor = complete_end
                while cursor > scan_floor:
                    line_end = cursor - 1 if mapped[cursor - 1] == 0x0A else cursor
                    previous_newline = mapped.rfind(b"\n", scan_floor, line_end)
                    if previous_newline < 0:
                        if scan_floor > 0:
                            break
                        line_start = 0
                    else:
                        line_start = previous_newline + 1
                    raw_line = mapped[line_start:line_end]
                    cursor = line_start
                    if not raw_line:
                        continue
                    message, usage = parse_codex_rollout_event(raw_line)
                    if context_usage is None and usage is not None:
                        context_usage = usage
                    if message is not None:
                        messages_reversed.append(message)
                        line_budget += message[1].count("\n") + 1
                        char_budget += len(message[1])
                        if message[0] == "user":
                            turn_count += 1
                        if (
                            message[0] == "user"
                            and context_usage is not None
                            and (
                                turn_count >= CODEX_TRANSCRIPT_PAGE_TURNS
                                or char_budget >= CODEX_ROLLOUT_CACHE_CHAR_BUDGET
                                or (
                                    line_budget >= CODEX_ROLLOUT_CACHE_LINE_BUDGET
                                    and turn_count >= CODEX_ROLLOUT_CACHE_MIN_TURNS
                                )
                            )
                        ):
                            break
    except (OSError, ValueError):
        return {"identity": identity, "offset": 0, "messages": [], "contextUsage": None}

    messages = bounded_codex_rollout_messages(list(reversed(messages_reversed)))
    return {
        "identity": identity,
        "offset": complete_end,
        "messages": messages,
        "contextUsage": context_usage,
    }


def codex_rollout_state(history_path: str | None) -> dict[str, Any] | None:
    """Return a bounded, incrementally updated state for a durable rollout."""
    if not history_path:
        return None
    path = Path(history_path).expanduser()
    key = str(path)
    with _codex_rollout_cache_lock:
        path_lock = _codex_rollout_path_locks.setdefault(key, threading.Lock())

    # One large conversation never serializes unrelated session reads.
    with path_lock:
        cached = cached_codex_rollout_state(key)
        try:
            stat = path.stat()
        except OSError:
            return cached

        identity = (stat.st_dev, stat.st_ino)
        offset = int(cached.get("offset") or 0) if cached else 0
        rebuild = (
            cached is None
            or cached.get("identity") != identity
            or stat.st_size < offset
            or stat.st_size - offset > CODEX_ROLLOUT_MAX_CATCHUP_BYTES
        )
        if rebuild:
            cached = initial_codex_rollout_state(path, identity)
            store_codex_rollout_cache(key, cached)
            return cached

        if stat.st_size == offset:
            store_codex_rollout_cache(key, cached)
            return cached

        try:
            with path.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read(stat.st_size - offset)
        except OSError:
            return cached

        # Leave a partial final record unread until Codex appends its newline.
        complete_end = chunk.rfind(b"\n")
        if complete_end < 0:
            store_codex_rollout_cache(key, cached)
            return cached

        messages = list(cached.get("messages") or [])
        context_usage = cached.get("contextUsage")
        for raw_line in chunk[:complete_end].splitlines():
            message, usage = parse_codex_rollout_event(raw_line)
            if message is not None:
                messages.append(message)
            if usage is not None:
                context_usage = usage
        cached = {
            "identity": identity,
            "offset": offset + complete_end + 1,
            "messages": bounded_codex_rollout_messages(messages),
            "contextUsage": context_usage,
        }
        store_codex_rollout_cache(key, cached)
        return cached


def codex_rollout_messages(history_path: str | None) -> list[tuple[str, str]]:
    state = codex_rollout_state(history_path)
    return list(state.get("messages") or []) if state else []


def codex_message_transcript(messages: list[tuple[str, str]], max_lines: int) -> str:
    """Group chronological rollout messages into intact recent turns."""
    turns: list[list[str]] = []
    current: list[str] = []
    for role, text in messages:
        block = f"› {text}" if role == "user" else f"• {text}"
        if role == "user" and current:
            turns.append(current)
            current = []
        current.append(block)
    if current:
        turns.append(current)

    selected: list[str] = []
    used_lines = 0
    used_chars = 0
    for turn_blocks in reversed(turns):
        if len(selected) >= CODEX_TRANSCRIPT_PAGE_TURNS:
            break
        turn = "\n\n".join(turn_blocks)
        turn_lines = turn.count("\n") + 1
        turn_chars = len(turn)
        if turn_exceeds_recent_budget(
            len(selected),
            used_lines,
            used_chars,
            turn_lines,
            turn_chars,
            line_budget=max_lines,
            char_budget=CODEX_TRANSCRIPT_CHAR_BUDGET,
            min_turns=CODEX_TRANSCRIPT_MIN_TURNS,
        ):
            break
        selected.append(turn)
        used_lines += turn_lines
        used_chars += turn_chars
    return "\n\n".join(reversed(selected)).strip()


def codex_rollout_transcript(history_path: str | None, max_lines: int) -> str:
    return codex_message_transcript(codex_rollout_messages(history_path), max_lines)


def codex_structured_capture(config: Config, lines: int) -> tuple[str, str, str] | None:
    cwd = get_pane_cwd(config)
    thread = active_agent_thread(config, cwd)
    thread_id = str(thread.get("id") or "") if thread else ""
    if not thread_id:
        return None

    # The rollout is the durable source that Codex itself writes. Reading it
    # incrementally avoids repeated full thread/read calls for large histories
    # and preserves the original Markdown and TeX verbatim.
    history_path = str(thread.get("rollout_path") or "") if thread else ""
    if text := codex_rollout_transcript(history_path, lines):
        return text, thread_id, "codex-jsonl"

    # Older/imported sessions may not expose a rollout path; retain the Codex
    # app-server as a structured compatibility fallback.
    stored = cached_codex_thread(thread_id)
    if not stored:
        return None
    text = codex_thread_transcript(stored, lines)
    return (text, thread_id, "codex-app-server") if text else None


def rate_limit_from_response(result: dict[str, Any]) -> dict[str, Any] | None:
    snapshots = result.get("rateLimitsByLimitId")
    snapshot = snapshots.get("codex") if isinstance(snapshots, dict) else None
    if not isinstance(snapshot, dict):
        snapshot = result.get("rateLimits")
    if not isinstance(snapshot, dict):
        return None

    primary = snapshot.get("primary")
    secondary = snapshot.get("secondary")
    weekly = secondary if isinstance(secondary, dict) else None
    if weekly and weekly.get("windowDurationMins") not in (None, 10080):
        weekly = None
    if weekly is None and isinstance(primary, dict):
        weekly = primary
    if not isinstance(weekly, dict):
        return None

    try:
        used_percent = float(weekly["usedPercent"])
    except (KeyError, TypeError, ValueError):
        return None

    return {
        "usedPercent": round(used_percent, 1),
        "windowDurationMins": weekly.get("windowDurationMins"),
        "resetsAt": weekly.get("resetsAt"),
        "limitId": snapshot.get("limitId"),
        "planType": snapshot.get("planType"),
    }


def fetch_weekly_rate_limit(timeout: float = 6.0) -> dict[str, Any] | None:
    # Reuse the Owner's serialized app-server channel instead of maintaining a
    # second short-lived protocol client. Structured history uses JSONL in the
    # normal path, so this low-frequency request does not contend with capture.
    result = codex_app_server_request("account/rateLimits/read", {}, timeout=timeout)
    return rate_limit_from_response(result) if isinstance(result, dict) else None


def refresh_weekly_rate_limit_cache() -> None:
    global _rate_limit_cache, _rate_limit_cache_at, _rate_limit_refreshing
    fresh = None
    try:
        fresh = fetch_weekly_rate_limit()
    except Exception:
        # Quota is optional status data. A transient CLI/subprocess failure
        # must not poison the singleton refresh flag forever.
        pass
    finally:
        with _rate_limit_lock:
            if fresh is not None:
                _rate_limit_cache = fresh
                _rate_limit_cache_at = time.monotonic()
            _rate_limit_refreshing = False


def cached_weekly_rate_limit() -> dict[str, Any] | None:
    global _rate_limit_refreshing

    now = time.monotonic()
    launch_refresh = False
    with _rate_limit_lock:
        if _rate_limit_cache is not None and now - _rate_limit_cache_at < RATE_LIMIT_CACHE_TTL:
            return _rate_limit_cache
        if not _rate_limit_refreshing:
            _rate_limit_refreshing = True
            launch_refresh = True
        cached = _rate_limit_cache
    if launch_refresh:
        try:
            threading.Thread(target=refresh_weekly_rate_limit_cache, name="faryo-codex-rate-limit", daemon=True).start()
        except Exception:
            with _rate_limit_lock:
                _rate_limit_refreshing = False
    return cached


def ansi_plain(line: str) -> str:
    if RichText is None:
        return line
    return RichText.from_ansi(line).plain


def clean_ansi_capture(text: str, profile: AgentProfile = CODEX_PROFILE) -> str:
    text = ANSI_CONTROL_RE.sub("", text)
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    normalized: list[str] = []
    blank_count = 0
    for line in lines:
        plain = ansi_plain(line).rstrip()
        if profile.placeholder_re.match(plain):
            blank_count += 1
            if blank_count <= 1:
                normalized.append("")
            continue

        match = profile.boundary_re.match(plain.strip())
        if match:
            normalized.append(match.group(1).strip())
            blank_count = 0
            continue
        if SEPARATOR_RE.match(plain.strip()) or SEPARATOR_OUTPUT_RE.match(plain) or LONG_SEPARATOR_RE.search(plain):
            continue

        if not plain.strip():
            blank_count += 1
            if blank_count <= 1:
                normalized.append("")
            continue

        blank_count = 0
        normalized.append(line)
    lines = strip_agent_input_tail(normalized, ansi_plain, profile)
    while lines and not ansi_plain(lines[0]).strip():
        lines.pop(0)
    while lines and not ansi_plain(lines[-1]).strip():
        lines.pop()
    return "\n".join(lines)


def sanitize_style_attr(match: re.Match[str]) -> str:
    kept: list[str] = []
    for raw_decl in match.group(1).split(";"):
        if ":" not in raw_decl:
            continue
        prop, value = raw_decl.split(":", 1)
        prop = prop.strip().lower()
        value = value.strip()
        normalized_value = value.lower().replace(" ", "")
        if prop in {"background", "background-color", "text-decoration-color"}:
            continue
        if prop == "color" and normalized_value in BLACK_VALUES | WHITE_VALUES:
            continue
        if prop == "color" and normalized_value in LOW_CONTRAST_TERMINAL_VALUES:
            value = USER_INPUT_COLOR
        kept.append(f"{prop}: {value}")
    return f' style="{"; ".join(kept)}"' if kept else ""


def sanitize_rich_html(html_fragment: str) -> str:
    match = RICH_PRE_RE.match(html_fragment)
    if match:
        html_fragment = match.group(1)
    return STYLE_ATTR_RE.sub(sanitize_style_attr, html_fragment)


def force_line_color(html_line: str, color: str) -> str:
    def replace_style(match: re.Match[str]) -> str:
        kept: list[str] = []
        for raw_decl in match.group(1).split(";"):
            if ":" not in raw_decl:
                continue
            prop, value = raw_decl.split(":", 1)
            prop = prop.strip().lower()
            value = value.strip()
            if prop == "color":
                kept.append("color: inherit")
            else:
                kept.append(f"{prop}: {value}")
        return f' style="{"; ".join(kept)}"'

    normalized = STYLE_ATTR_RE.sub(replace_style, html_line)
    return f'<span style="color: {color}">{normalized or " "}</span>'


def color_user_input_lines(html_fragment: str, plain_text: str, profile: AgentProfile = CODEX_PROFILE) -> str:
    html_lines = html_fragment.split("\n")
    text_lines = plain_text.split("\n")
    if len(html_lines) != len(text_lines):
        return html_fragment
    in_user_input = False
    out: list[str] = []
    for html_line, plain_line in zip(html_lines, text_lines):
        if profile.user_prompt_re.match(plain_line):
            in_user_input = True
        elif not plain_line.strip():
            in_user_input = False

        out.append(force_line_color(html_line, USER_INPUT_COLOR) if in_user_input else html_line)
    return "\n".join(out)


def strip_agent_meta_html_lines(html_fragment: str, plain_text: str, profile: AgentProfile = CODEX_PROFILE) -> str:
    html_lines = html_fragment.split("\n")
    text_lines = plain_text.split("\n")
    if len(html_lines) != len(text_lines):
        return html_fragment
    return "\n".join(html_line for html_line, plain_line in zip(html_lines, text_lines) if not agent_meta_line(plain_line, profile))


def capture_text(config: Config, lines: int = CAPTURE_DEFAULT_LINES, profile: AgentProfile = CODEX_PROFILE) -> str:
    if not has_session(config):
        raise OwnerError(f"tmux session not found: {config.session}", HTTPStatus.NOT_FOUND)
    safe_lines = max(20, min(lines, CAPTURE_MAX_LINES))
    res = tmux(config, ["capture-pane", "-p", "-J", "-t", tmux_target(config), "-S", f"-{safe_lines}"], timeout=3)
    if res.returncode != 0:
        raise OwnerError(res.stderr.strip() or "tmux capture failed", HTTPStatus.INTERNAL_SERVER_ERROR)
    return strip_agent_meta_lines(clean_capture(res.stdout, profile=profile), profile)


def codex_live_tail(text: str, max_lines: int = CODEX_LIVE_TAIL_LINES) -> str:
    lines = text.splitlines()
    user_starts = [index for index, line in enumerate(lines) if CODEX_PROFILE.user_prompt_re.match(line)]
    running_starts = [index for index, line in enumerate(lines) if re.match(r"^\s*•\s+Running\b", line)]
    starts = user_starts + running_starts
    selected = lines[max(starts):] if starts else lines[-min(len(lines), 24):]
    selected = selected[-max(1, max_lines):]
    redacted = [
        re.sub(r"(?i)(\bAccount:\s*).*$", r"\1<redacted>", line)
        for line in selected
    ]
    return "\n".join(redacted).strip()


def capture_html(config: Config, lines: int = CAPTURE_DEFAULT_LINES, profile: AgentProfile = CODEX_PROFILE) -> str | None:
    if RichConsole is None or RichText is None:
        return None
    if not has_session(config):
        raise OwnerError(f"tmux session not found: {config.session}", HTTPStatus.NOT_FOUND)
    safe_lines = max(20, min(lines, CAPTURE_MAX_LINES))
    res = tmux(config, ["capture-pane", "-p", "-e", "-J", "-t", tmux_target(config), "-S", f"-{safe_lines}"], timeout=3)
    if res.returncode != 0:
        raise OwnerError(res.stderr.strip() or "tmux capture failed", HTTPStatus.INTERNAL_SERVER_ERROR)
    ansi_text = clean_ansi_capture(res.stdout, profile)
    console = RichConsole(record=True, file=io.StringIO(), force_terminal=False, color_system="truecolor", width=4096)
    console.print(RichText.from_ansi(ansi_text), no_wrap=True, end="")
    match = HTML_CODE_RE.search(console.export_html(inline_styles=True, clear=False))
    if not match:
        return None
    plain_text = ansi_plain(ansi_text)
    html = color_user_input_lines(sanitize_rich_html(match.group(1)), plain_text, profile)
    return strip_agent_meta_html_lines(html, plain_text, profile)


def compact_capture_for_probe(text: str) -> str:
    return " ".join(clean_capture(text, strip_input_tail=False).split())


def tmux_capture_compact(config: Config, lines: int = 100) -> str:
    res = tmux(config, ["capture-pane", "-p", "-J", "-t", tmux_target(config), "-S", f"-{lines}"], timeout=2)
    return compact_capture_for_probe(res.stdout) if res.returncode == 0 else ""


def tmux_cursor_position(config: Config) -> tuple[int, int] | None:
    res = tmux(config, ["display-message", "-p", "-t", tmux_target(config), "#{cursor_x}\t#{cursor_y}"], timeout=2)
    if res.returncode != 0:
        return None
    try:
        x, y = res.stdout.strip().split("\t", 1)
        return int(x), int(y)
    except (TypeError, ValueError):
        return None


def tmux_current_capture(config: Config) -> str:
    res = tmux(config, ["capture-pane", "-p", "-J", "-t", tmux_target(config)], timeout=2)
    return CONTROL_RE.sub("", res.stdout.replace("\r\n", "\n").replace("\r", "\n")) if res.returncode == 0 else ""


def tmux_current_ansi_capture(config: Config) -> str:
    res = tmux(config, ["capture-pane", "-p", "-e", "-J", "-t", tmux_target(config)], timeout=2)
    return ANSI_CONTROL_RE.sub("", res.stdout.replace("\r\n", "\n").replace("\r", "\n")) if res.returncode == 0 else ""


def paste_tail_probe(text: str) -> str:
    compacted = " ".join(text.split())
    if len(compacted) <= PASTE_READY_MIN_PROBE_CHARS:
        return compacted
    return compacted[-min(80, len(compacted)):]


def last_agent_prompt_block_from_text(text: str, profile: AgentProfile = CODEX_PROFILE) -> str:
    lines = text.splitlines()
    prompt_index = next((index for index in range(len(lines) - 1, -1, -1) if profile.input_prompt_re.match(lines[index].strip())), None)
    if prompt_index is None:
        return ""
    return compact_capture_for_probe("\n".join(lines[prompt_index:]))


def last_agent_prompt_block(config: Config, profile: AgentProfile = CODEX_PROFILE) -> str:
    return last_agent_prompt_block_from_text(tmux_current_capture(config), profile)


def ansi_visible_cells(text: str) -> list[tuple[str, bool]]:
    """Return visible characters paired with the active ANSI dim state."""
    cells: list[tuple[str, bool]] = []
    dim = False
    cursor = 0
    for match in ANSI_SGR_RE.finditer(text):
        cells.extend((char, dim) for char in text[cursor:match.start()])
        raw_codes = match.group(1)
        codes = [0] if raw_codes == "" else [int(value or 0) for value in raw_codes.split(";")]
        for code in codes:
            if code == 0:
                dim = False
            elif code == 2:
                dim = True
            elif code == 22:
                dim = False
        cursor = match.end()
    cells.extend((char, dim) for char in text[cursor:])
    return cells


def ansi_prompt_has_real_text(line: str, profile: AgentProfile = CODEX_PROFILE) -> bool | None:
    """Distinguish a real Codex draft from its dim rotating placeholder."""
    cells = ansi_visible_cells(line)
    plain = "".join(char for char, _dim in cells)
    match = profile.input_prompt_re.match(plain)
    if not match:
        return None
    for char, dim in cells[match.end():]:
        if char.isspace():
            continue
        return not dim
    return False


def codex_composer_has_draft(config: Config) -> bool:
    ansi_capture = tmux_current_ansi_capture(config)
    for line in reversed(ansi_capture.splitlines()):
        has_text = ansi_prompt_has_real_text(line)
        if has_text is not None:
            return has_text
    # Minimal environments without styled capture retain the old conservative
    # cursor fallback. Wrapped and multiline drafts are handled by the ANSI
    # path used by the deployed Owner.
    cursor = tmux_cursor_position(config)
    return bool(cursor and cursor[0] > 2)


def codex_submission_key(config: Config) -> str:
    """Queue a new web message while Codex works; otherwise submit it."""
    # Codex 0.147 gives the active working composer its own `»` glyph.  Reading
    # that glyph is safer than searching the surrounding screen for status
    # text: completed output can still contain an old "esc to interrupt" line.
    for line in reversed(tmux_current_capture(config).splitlines()):
        stripped = line.strip()
        if CODEX_PROFILE.input_prompt_re.match(stripped):
            return "Tab" if stripped.startswith("»") else "Enter"
    return "Enter"


def codex_composer_contains_text(config: Config, text: str) -> bool:
    probe = paste_tail_probe(text)
    prompt = last_agent_prompt_block(config, CODEX_PROFILE)
    return bool(probe and probe in prompt)


def codex_queued_followup_count(capture: str, text: str) -> int:
    lines = capture.splitlines()
    marker = next((index for index in range(len(lines) - 1, -1, -1) if "queued follow-up inputs" in lines[index].lower()), None)
    probe = paste_tail_probe(text)
    if marker is None or not probe:
        return 0
    queued_lines: list[str] = []
    for line in lines[marker + 1:]:
        if CODEX_PROFILE.input_prompt_re.match(line.strip()):
            break
        queued_lines.append(line)
    return compact_capture_for_probe("\n".join(queued_lines)).count(probe)


def release_version() -> str:
    global RELEASE_VERSION_CACHE
    if RELEASE_VERSION_CACHE is not None:
        return RELEASE_VERSION_CACHE
    try:
        for line in RELEASE_FILE.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key == "version":
                RELEASE_VERSION_CACHE = value.strip()
                return RELEASE_VERSION_CACHE
    except OSError:
        pass
    RELEASE_VERSION_CACHE = ""
    return RELEASE_VERSION_CACHE


def wait_for_paste_tail(
    config: Config,
    text: str,
    baseline: str,
    baseline_cursor: tuple[int, int] | None = None,
) -> bool:
    probe = paste_tail_probe(text)
    if not probe:
        return True
    baseline_cursor = baseline_cursor or tmux_cursor_position(config)
    deadline = time.monotonic() + PASTE_READY_TIMEOUT
    while time.monotonic() < deadline:
        captured = tmux_capture_compact(config)
        if captured.count(probe) > baseline.count(probe):
            return True
        cursor = tmux_cursor_position(config)
        if cursor and baseline_cursor and cursor != baseline_cursor and cursor[0] > 2:
            return True
        time.sleep(PASTE_READY_POLL_INTERVAL)
    return False


def codex_rollout_submission_probe(config: Config) -> tuple[Path, int] | None:
    """Return the active rollout and its current EOF for exact delivery checks."""
    try:
        thread = active_agent_thread(config, get_pane_cwd(config))
        path_value = str(thread.get("rollout_path") or "") if thread else ""
        path = Path(path_value).expanduser()
        return (path, path.stat().st_size) if path_value and path.is_file() else None
    except OSError:
        return None


def codex_rollout_probe_state(probe: tuple[Path, int] | None) -> dict[str, int]:
    if probe is None:
        return {}
    path, offset = probe
    try:
        stat = path.stat()
    except OSError:
        return {}
    return {
        "rolloutDevice": int(stat.st_dev),
        "rolloutInode": int(stat.st_ino),
        "rolloutOffset": int(offset),
    }


def codex_rollout_probe_from_state(config: Config, state: dict[str, Any]) -> tuple[Path, int] | None:
    try:
        expected_device = int(state.get("rolloutDevice"))
        expected_inode = int(state.get("rolloutInode"))
        offset = int(state.get("rolloutOffset"))
    except (TypeError, ValueError):
        return None
    current = codex_rollout_submission_probe(config)
    if current is None or offset < 0:
        return None
    path, _current_offset = current
    try:
        stat = path.stat()
    except OSError:
        return None
    if int(stat.st_dev) != expected_device or int(stat.st_ino) != expected_inode:
        return None
    return path, offset


def codex_rollout_user_message(event: Any) -> str:
    if not isinstance(event, dict) or event.get("type") != "response_item":
        return ""
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "message" or payload.get("role") != "user":
        return ""
    values: list[str] = []
    for item in payload.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "input_text":
            values.append(str(item.get("text") or ""))
    return "\n".join(values).replace("\r\n", "\n").replace("\r", "\n").strip()


def codex_rollout_has_user_message(probe: tuple[Path, int] | None, text: str) -> bool:
    if probe is None:
        return False
    path, offset = probe
    expected = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    try:
        with path.open("rb") as fh:
            if offset > path.stat().st_size:
                return False
            fh.seek(offset)
            for raw_line in fh:
                try:
                    event = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if codex_rollout_user_message(event) == expected:
                    return True
    except OSError:
        return False
    return False


def wait_for_codex_submission(
    config: Config,
    text: str,
    timeout: float = SEND_ACCEPT_TIMEOUT,
    rollout_probe: tuple[Path, int] | None = None,
    queued_baseline: int | None = 0,
    allow_composer_disappearance: bool = True,
) -> str | None:
    probe = paste_tail_probe(text)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if codex_rollout_has_user_message(rollout_probe, text):
            return "recorded"
        capture = tmux_current_capture(config)
        if queued_baseline is not None and codex_queued_followup_count(capture, text) > queued_baseline:
            return "queued"
        prompt = last_agent_prompt_block_from_text(capture, CODEX_PROFILE)
        # A submitted message remains visible in transcript history, so the
        # pane as a whole is not a valid confirmation signal.  The active
        # composer is: once its exact tail disappears, Enter/Tab was accepted.
        # This also works while Codex is starting MCP servers, where rollout
        # persistence can lag several seconds behind the TUI.
        if allow_composer_disappearance and prompt and (not probe or probe not in prompt):
            return "submitted"
        time.sleep(PASTE_READY_POLL_INTERVAL)
    return None


def status_payload(config: Config) -> dict[str, Any]:
    tmux_alive = has_session(config)
    profile = agent_profile_in_pane(config) if tmux_alive else None
    capture_profile = profile or RUNTIME_PROFILE
    text = ""
    model = None
    reasoning_effort = None
    fast_status = None
    meta_cwd = None
    if tmux_alive:
        try:
            text = capture_text(config, 80, capture_profile)
        except OwnerError:
            text = ""
        try:
            raw_text = clean_capture(
                tmux(config, ["capture-pane", "-p", "-J", "-t", tmux_target(config), "-S", "-80"], timeout=3).stdout,
                strip_input_tail=False,
                profile=capture_profile,
            )
            meta = latest_agent_meta(raw_text, capture_profile)
            fast_status = latest_fast_status(raw_text)
            if meta:
                model = meta[0]
                reasoning_effort = reasoning_effort_from_model_status(model)
                meta_cwd = meta_cwd_path(meta[1])
        except Exception:
            pass
    if fast_status is None:
        fast_status = configured_fast_status()
    if fast_status is None:
        fast_status = "off"
    cwd = get_pane_cwd(config) if tmux_alive else None
    thread = active_agent_thread(config, cwd) if tmux_alive else None
    context_usage = latest_context_usage(thread.get("rollout_path") if thread else None)
    weekly_rate_limit = None
    if tmux_alive and profile is CODEX_PROFILE:
        try:
            weekly_rate_limit = cached_weekly_rate_limit()
        except Exception:
            weekly_rate_limit = None
    agent_active = profile is not None
    agent_running = bool(agent_active and not agent_ready_for_input(config, capture_profile))
    target_alive = tmux_alive
    session_title = codex_thread_title(thread, str(thread.get("id") or "Untitled session")) if thread else None
    return {
        "ok": tmux_alive,
        "tmuxAlive": tmux_alive,
        "targetAlive": target_alive,
        "releaseVersion": release_version(),
        "session": config.session,
        "ownerLabel": owner_label(),
        "paneWidth": get_pane_width(config) if tmux_alive else None,
        "cwd": cwd,
        "displayCwd": meta_cwd or short_path(cwd),
        "shortCwd": short_path(cwd) or meta_cwd,
        "model": model,
        "reasoningEffort": reasoning_effort,
        "fastStatus": fast_status,
        "gitStatus": git_status(session_git_cwd(config, config.session, cwd)),
        "sessionTitle": session_title,
        "sessionId": thread.get("id") if thread else None,
        "contextUsage": context_usage,
        "weeklyRateLimit": weekly_rate_limit,
        "agentRunning": agent_running,
        "paneCommand": get_pane_current_command(config) if tmux_alive else None,
        "agentSource": profile.source if profile else "",
        "agentProfile": profile.key if profile else "",
        "updatedAt": now_iso(),
    }


def attachment_suffix(filename: str | None, content_type: str | None, data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"heic", b"heix", b"hevc", b"hevx", b"heif", b"mif1", b"msf1"}:
        return ".heic"
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    mime_suffix = IMAGE_MIME_SUFFIXES.get(mime) or DOCUMENT_MIME_SUFFIXES.get(mime)
    if mime_suffix:
        return mime_suffix
    suffix = Path(filename or "").suffix.lower()
    if suffix in ALLOWED_ATTACHMENT_SUFFIXES:
        return ".jpg" if suffix == ".jpeg" else suffix
    raise OwnerError("unsupported attachment type; use image, pdf, office, md, txt, csv, or json")


def cleanup_old_uploads(root: Path) -> None:
    cutoff = _dt.datetime.now().date() - _dt.timedelta(days=UPLOAD_RETENTION_DAYS - 1)
    try:
        children = list(root.iterdir())
    except FileNotFoundError:
        return
    for child in children:
        if not child.is_dir():
            continue
        try:
            day = _dt.date.fromisoformat(child.name)
        except ValueError:
            continue
        if day < cutoff:
            try:
                shutil.rmtree(child)
            except OSError:
                pass


def save_uploaded_attachment(file_item: Any, root_override: str | None = None) -> tuple[Path, int, str]:
    filename = Path(getattr(file_item, "filename", "") or "attachment").name
    file_obj = getattr(file_item, "file", None)
    if file_obj is None:
        raise OwnerError("missing attachment file")
    data = file_obj.read(MAX_ATTACHMENT_UPLOAD_BYTES + 1)
    if not data:
        raise OwnerError("empty attachment")
    if len(data) > MAX_ATTACHMENT_UPLOAD_BYTES:
        raise OwnerError("attachment too large; max 25 MB", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    suffix = attachment_suffix(filename, getattr(file_item, "type", None), data)
    root_value = root_override or env_value("FARYO_OWNER_INBOX_DIR", "FARYO_OWNER_FILE_INBOX", default=str(FILE_INBOX_ROOT))
    root = Path(root_value).expanduser()
    cleanup_old_uploads(root)
    target_dir = root / _dt.datetime.now().strftime("%Y-%m-%d")
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for _ in range(10):
        path = target_dir / f"{stamp}-{secrets.token_hex(3)}{suffix}"
        try:
            with path.open("xb") as fh:
                fh.write(data)
            return path, len(data), "image" if suffix in IMAGE_SUFFIXES else "file"
        except FileExistsError:
            continue
    raise OwnerError("failed to allocate attachment path", HTTPStatus.INTERNAL_SERVER_ERROR)


def clean_local_path(value: str | None) -> str:
    text = (value or "").strip()
    if (text.startswith("<") and text.endswith(">")) or (text[:1] in {"'", '"', "`"} and text[-1:] == text[:1]):
        text = text[1:-1].strip()
    if not text or "\x00" in text:
        raise OwnerError("missing file path")
    return text


def resolve_local_path(path_value: str | None, config: Config, suffixes: set[str], workspace_root: str | None = None) -> Path:
    raw = Path(clean_local_path(path_value)).expanduser()
    bases = [get_pane_cwd(config), workspace_root, str(FILE_INBOX_ROOT)]
    candidates = [raw] if raw.is_absolute() else [Path(base).expanduser() / raw for base in bases if base]
    for candidate in candidates:
        try:
            path = candidate.resolve()
        except OSError:
            continue
        if path.is_file() and path.suffix.lower() in suffixes:
            return path
    raise OwnerError("file not found", HTTPStatus.NOT_FOUND)


def resolve_local_image_path(path_value: str | None, config: Config, workspace_root: str | None = None) -> Path:
    return resolve_local_path(path_value, config, IMAGE_SUFFIXES, workspace_root)


def start_directory_roots(workspace_root: str | None = None) -> list[Path]:
    values = []
    for name in ("FARYO_START_DIRECTORY_ROOTS", "FARYO_PROJECT_WORKBENCH_ALLOWED_ROOTS"):
        values.extend(part for part in os.environ.get(name, "").split(os.pathsep) if part.strip())
    if workspace_root:
        values.append(workspace_root)
    if not values:
        values.append(str(Path.home()))
    roots: list[Path] = []
    for value in values:
        try:
            root = Path(os.path.expandvars(value)).expanduser().resolve()
        except OSError:
            continue
        if root.is_dir() and root not in roots:
            roots.append(root)
    return roots


def resolve_start_directory(path_value: str | None, workspace_root: str | None = None) -> tuple[Path, list[Path]]:
    roots = start_directory_roots(workspace_root)
    if not roots:
        raise OwnerError("no start-directory roots are configured", HTTPStatus.FORBIDDEN)
    raw = str(path_value or "").strip()
    try:
        path = (Path(os.path.expandvars(raw)).expanduser() if raw else roots[0]).resolve()
    except OSError as exc:
        raise OwnerError("working directory is unavailable", HTTPStatus.NOT_FOUND) from exc
    if not any(path == root or path.is_relative_to(root) for root in roots):
        raise OwnerError("working directory is outside the configured roots", HTTPStatus.FORBIDDEN)
    if not path.is_dir():
        raise OwnerError("working directory is unavailable", HTTPStatus.NOT_FOUND)
    return path, roots


def directory_selection_token(config: Config, path: Path) -> str:
    return hmac.new(config.token.encode("utf-8"), f"cwd:{path}".encode("utf-8"), hashlib.sha256).hexdigest()


def directory_browser_payload(config: Config, path_value: str | None, workspace_root: str | None = None) -> dict[str, Any]:
    path, roots = resolve_start_directory(path_value, workspace_root)
    parent = path.parent if path.parent != path and any(path.parent == root or path.parent.is_relative_to(root) for root in roots) else None
    directories = []
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name.casefold())
    except OSError as exc:
        raise OwnerError("working directory cannot be listed", HTTPStatus.FORBIDDEN) from exc
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            resolved = child.resolve()
        except OSError:
            continue
        if not resolved.is_dir() or not any(resolved == root or resolved.is_relative_to(root) for root in roots):
            continue
        directories.append({"name": child.name, "path": str(resolved), "displayPath": short_path(str(resolved))})
        if len(directories) >= START_DIRECTORY_MAX_ENTRIES:
            break
    return {
        "ok": True,
        "path": str(path),
        "displayPath": short_path(str(path)) or str(path),
        "selectionToken": directory_selection_token(config, path),
        "parent": str(parent) if parent else "",
        "parentDisplayPath": short_path(str(parent)) if parent else "",
        "directories": directories,
        "roots": [{"path": str(root), "displayPath": short_path(str(root)) or str(root)} for root in roots],
        "truncated": len(directories) >= START_DIRECTORY_MAX_ENTRIES,
        "updatedAt": now_iso(),
    }


def compact_text(value: Any) -> str:
    return wb_state.compact_text(value)


def clean_session_title(value: Any) -> str:
    return compact_text(value)[:48]


def project_slug(value: Any) -> str:
    return wb_state.project_slug(value)


def project_workbench_enabled() -> bool:
    return env_value("FARYO_PROJECT_WORKBENCH_ENABLE", default="1").strip().lower() not in {"0", "false", "no", "off"}


def clean_project_item(item: dict[str, Any], index: int) -> dict[str, str]:
    return wb_state.clean_item(item, index)


def clean_project_workbench(project: dict[str, Any]) -> dict[str, Any]:
    return wb_state.clean_project(project)


def project_workbench_root(project: dict[str, Any]) -> Path:
    root_value = env_value("FARYO_PROJECT_WORKBENCH_PROJECTS_ROOT").strip() or str(Path.home() / "brain" / "projects")
    root = Path(root_value).expanduser()
    keys = {project_slug(project.get("id")), project_slug(project.get("name"))}
    try:
        for child in root.iterdir():
            if child.is_dir() and project_slug(child.name) in keys:
                return child
    except OSError as exc:
        raise OwnerError("project root not found", HTTPStatus.NOT_FOUND) from exc
    raise OwnerError(f"project not found: {project.get('name') or project.get('id')}", HTTPStatus.NOT_FOUND)


def project_workbench_allowed_roots() -> list[Path]:
    default = os.pathsep.join([str(Path.home() / "brain" / "projects"), str(Path.home() / "brain" / "tools"), str(Path.home() / ".faryo" / "projects")])
    raw_roots = env_value("FARYO_PROJECT_WORKBENCH_ALLOWED_ROOTS").strip() or default
    roots = []
    for chunk in raw_roots.split(os.pathsep):
        item = chunk.strip()
        if item:
            roots.append(Path(item).expanduser().resolve())
    return roots


def ensure_project_workbench_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.name != "workbench.json":
        resolved = resolved / "00-system" / "workbench.json"
    allowed_roots = project_workbench_allowed_roots()
    if not allowed_roots or not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise OwnerError("project workbench path is outside allowed roots", HTTPStatus.FORBIDDEN)
    return resolved


def project_workbench_path(project: dict[str, Any]) -> Path:
    raw_path = compact_text(project.get("workbench_path"))
    if raw_path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return ensure_project_workbench_path(path)
        roots = project_workbench_allowed_roots()
        if not roots:
            raise OwnerError("project workbench allowed roots not configured", HTTPStatus.FORBIDDEN)
        return ensure_project_workbench_path(roots[0] / path)
    return project_workbench_root(project) / "00-system" / "workbench.json"


def project_workbench_import_path(raw_path: str) -> tuple[Path, Path]:
    if not raw_path:
        raise OwnerError("missing project_root")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        roots = project_workbench_allowed_roots()
        if not roots:
            raise OwnerError("project workbench allowed roots not configured", HTTPStatus.FORBIDDEN)
        path = roots[0] / path
    workbench_path = ensure_project_workbench_path(path)
    project_root = workbench_path.parent.parent if workbench_path.parent.name == "00-system" else workbench_path.parent
    if not project_root.is_dir():
        raise OwnerError("project root not found", HTTPStatus.NOT_FOUND)
    return project_root, workbench_path


def project_workbench_text(project: dict[str, Any]) -> str:
    return json.dumps(project, ensure_ascii=False, indent=2) + "\n"


def write_project_workbench_file(path: Path, project: dict[str, Any]) -> Path:
    tmp = stage_project_workbench_file(path, project)
    os.replace(tmp, path)
    return path


def stage_project_workbench_file(path: Path, project: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not path.is_file():
        raise OwnerError("project workbench path is not a file", HTTPStatus.BAD_REQUEST)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(project_workbench_text(project), encoding="utf-8")
    return tmp


def update_project_workbench_summary(path: Path, project: dict[str, Any]) -> dict[str, Any]:
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(source, dict):
            source = {}
    except (OSError, json.JSONDecodeError):
        source = {}
    updated = dict(source)
    updated["id"] = compact_text(updated.get("id") or project.get("id"))
    for key in ("name", "brief", "current_d"):
        if key in project:
            updated[key] = compact_text(project.get(key))
    updated = clean_project_workbench(updated)
    write_project_workbench_file(path, updated)
    return updated


def cleanup_staged_project_workbenches(staged: list[tuple[Path, Path]]) -> None:
    for _path, tmp in staged:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def project_definition_path(project_root: Path) -> Path:
    return project_root / "00-system" / "conops.md"


def project_definition_text(project_root: Path, project: dict[str, Any]) -> str:
    name = compact_text(project.get("name")) or project_root.name
    brief = compact_text(project.get("brief")) or "Not defined."
    current_goal = compact_text(project.get("current_d")) or "Not set."
    owner = owner_label()
    return "\n".join([
        f"# {name}",
        "",
        "## Purpose",
        brief,
        "",
        "## Control",
        f"- Owner: {owner}",
        f"- Project root: {project_root}",
        "- Current state file: `00-system/workbench.json`",
        "",
        "## Current Goal",
        current_goal,
        "",
        "## Worker Contract",
        "- Treat `00-system/workbench.json` as a generated current-state projection.",
        "- Submit state changes through the workbench transition flow before closing a managed work session.",
        "- Do not treat this file as the live task board; it is the stable project definition.",
        "",
    ]) + "\n"


def ensure_project_definition_file(project_root: Path, project: dict[str, Any]) -> Path:
    path = project_definition_path(project_root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(project_definition_text(project_root, project), encoding="utf-8")
        os.replace(tmp, path)
    return path


def initial_project_definition(project: dict[str, Any]) -> dict[str, Any]:
    return pd_state.clean_project_definition({
        "current_stage_id": "stage-1",
        "current_stage_title": "项目定义",
        "stage_goal": compact_text(project.get("current_d") or project.get("brief")) or "完成项目定义。",
        "stage_state": "stage_to_define",
    })


def project_definition_root_from_payload(payload: dict[str, Any]) -> Path:
    raw_root = compact_text(payload.get("project_root") or payload.get("cwd"))
    if raw_root:
        return project_root_from_payload(payload)
    project_root, _workbench_path = project_workbench_import_path(compact_text(payload.get("workbench_path") or payload.get("path")))
    return project_root


def project_definition_payload(payload: dict[str, Any]) -> dict[str, Any]:
    path = project_definition_path(project_definition_root_from_payload(payload))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OwnerError("conops.md not found", HTTPStatus.NOT_FOUND) from exc
    return {"ok": True, "definition": pd_state.parse_project_definition(text), "updatedAt": now_iso()}


def project_root_from_workbench_file(path: Path) -> Path:
    return path.parent.parent if path.parent.name == "00-system" else path.parent


def apply_project_definition_downlink(path: Path, project: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    return sync_project_definition({**project, "project_root": str(project_root_from_workbench_file(path)), "definition": definition})["definition"]


def project_downlink_truth(project: dict[str, Any], definition: dict[str, Any] | None = None) -> dict[str, Any]:
    truth = clean_project_workbench(project)
    if isinstance(definition, dict):
        clean_definition = pd_state.project_definition_hash_payload(definition)
        if clean_definition:
            truth["definition"] = clean_definition
    return truth


def project_downlink_hash(project: dict[str, Any], definition: dict[str, Any] | None = None) -> str:
    return project_workbench_hash(project_downlink_truth(project, definition))


def sync_project_definition(payload: dict[str, Any]) -> dict[str, Any]:
    if not project_workbench_enabled():
        raise OwnerError("project workbench is disabled", HTTPStatus.FORBIDDEN)
    definition = pd_state.clean_project_definition(payload.get("definition"))
    if not definition:
        raise OwnerError("missing project definition")
    project_root = project_definition_root_from_payload(payload)
    path = ensure_project_definition_file(project_root, clean_project_workbench(payload))
    pd_state.write_project_definition(path, definition)
    return {"ok": True, "definition": pd_state.parse_project_definition(path.read_text(encoding="utf-8")), "updatedAt": now_iso()}


def project_workbench_hash(project: dict[str, Any]) -> str:
    body = json.dumps(project, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def project_root_from_payload(payload: dict[str, Any]) -> Path:
    raw_root = compact_text(payload.get("project_root") or payload.get("cwd"))
    if not raw_root:
        raise OwnerError("missing project_root")
    root = Path(raw_root).expanduser().resolve()
    if not root.is_dir():
        raise OwnerError("project root not found", HTTPStatus.NOT_FOUND)
    allowed_roots = project_workbench_allowed_roots()
    if not allowed_roots or not any(root == allowed or allowed in root.parents for allowed in allowed_roots):
        raise OwnerError("project root is outside allowed roots", HTTPStatus.FORBIDDEN)
    return root


def project_git_status(payload: dict[str, Any]) -> dict[str, Any]:
    root = project_root_from_payload(payload)
    return {"ok": True, "gitStatus": git_status(str(root)), "updatedAt": now_iso()}


def clean_workorder_id(value: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-")
    return cleaned[:80]


def new_workorder_id() -> str:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"wo-{stamp}-{secrets.token_hex(4)}"


def project_git_exclude_info(project_root: Path) -> tuple[Path, str] | None:
    exclude_result = run_cmd(["git", "-C", str(project_root), "rev-parse", "--git-path", "info/exclude"], timeout=2)
    root_result = run_cmd(["git", "-C", str(project_root), "rev-parse", "--show-toplevel"], timeout=2)
    if exclude_result.returncode != 0 or root_result.returncode != 0:
        return None
    raw_path = exclude_result.stdout.strip()
    raw_root = root_result.stdout.strip()
    if not raw_path:
        return None
    git_root = Path(raw_root).expanduser().resolve() if raw_root else project_root
    path = Path(raw_path)
    exclude_path = path if path.is_absolute() else project_root / path
    try:
        workorders_rel = (project_root / "00-system" / "workorders").resolve().relative_to(git_root)
    except ValueError:
        return None
    marker = "/" + workorders_rel.as_posix().rstrip("/") + "/"
    return exclude_path, marker


def ensure_workorders_git_ignored(project_root: Path) -> bool:
    info = project_git_exclude_info(project_root)
    if info is None:
        return False
    path, marker = info
    try:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if marker in current.splitlines():
            return True
        path.parent.mkdir(parents=True, exist_ok=True)
        suffix = "" if current.endswith("\n") or not current else "\n"
        path.write_text(current + suffix + marker + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def workbench_file(project_root: Path, name: str) -> Path:
    return project_root / "00-system" / name


def read_project_workbench_file(project_root: Path) -> dict[str, Any]:
    path = workbench_file(project_root, "workbench.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OwnerError("invalid or missing workbench.json", HTTPStatus.BAD_REQUEST) from exc
    if not isinstance(payload, dict):
        raise OwnerError("workbench must be a JSON object", HTTPStatus.BAD_REQUEST)
    return clean_project_workbench(payload)


def apply_workbench_transition(payload: dict[str, Any]) -> dict[str, Any]:
    if not project_workbench_enabled():
        raise OwnerError("project workbench is disabled", HTTPStatus.FORBIDDEN)
    project_root = project_root_from_payload(payload)
    project = read_project_workbench_file(project_root)
    try:
        project, events, history_rows, item_ids = wb_state.apply_transition(project, payload)
        wb_state.write_project(workbench_file(project_root, "workbench.json"), project)
        wb_state.append_jsonl(workbench_file(project_root, "workbench.events.jsonl"), events)
        wb_state.append_jsonl(workbench_file(project_root, "workbench.history.jsonl"), history_rows)
    except LookupError as exc:
        raise OwnerError(str(exc), HTTPStatus.NOT_FOUND) from exc
    except ValueError as exc:
        status = HTTPStatus.CONFLICT if str(exc).startswith("invalid transition:") or str(exc) == "item already exists" else HTTPStatus.BAD_REQUEST
        raise OwnerError(str(exc), status) from exc
    except OSError as exc:
        raise OwnerError("failed to write workbench transition", HTTPStatus.INTERNAL_SERVER_ERROR) from exc
    return {
        "ok": True,
        "project": project,
        "eventCount": len(events),
        "historyRows": len(history_rows),
        "itemIds": item_ids,
        "workbenchHash": project_workbench_hash(project),
        "updatedAt": now_iso(),
    }


def project_workbench_status(payload: dict[str, Any]) -> dict[str, Any]:
    if not project_workbench_enabled():
        raise OwnerError("project workbench is disabled", HTTPStatus.FORBIDDEN)
    project_root = project_root_from_payload(payload)
    project = read_project_workbench_file(project_root)
    return {
        "ok": True,
        "project": project,
        "workbenchHash": project_workbench_hash(project),
        "updatedAt": now_iso(),
    }


def read_project_workorder_state(project_root: Path, workorder_id: str) -> tuple[bool, bool, dict[str, Any], list[str]]:
    if not workorder_id:
        raise OwnerError("missing workorder_id")
    workorder_path = project_root / "00-system" / "workorders" / f"{workorder_id}.md"
    if not workorder_path.is_file():
        raise OwnerError("workorder not found", HTTPStatus.NOT_FOUND)
    text = workorder_path.read_text(encoding="utf-8")
    workbench_path = project_root / "00-system" / "workbench.json"
    try:
        project = clean_project_workbench(json.loads(workbench_path.read_text(encoding="utf-8")))
        workbench_ok = True
    except (OSError, json.JSONDecodeError):
        project = {}
        workbench_ok = False
    item_ids = [item["id"] for item in project.get("items", []) if compact_text(item.get("workorder_id")) == workorder_id]
    return "## Receipt" in text and "- Status: pending" not in text, workbench_ok, project, item_ids


def project_workorder_status(payload: dict[str, Any]) -> dict[str, Any]:
    if not project_workbench_enabled():
        raise OwnerError("project workbench is disabled", HTTPStatus.FORBIDDEN)
    project_root = project_root_from_payload(payload)
    receipt_ready, workbench_ok, project, item_ids = read_project_workorder_state(project_root, clean_workorder_id(payload.get("workorder_id")))
    return {
        "ok": True,
        "receiptReady": receipt_ready,
        "workbenchOk": workbench_ok,
        "workbenchHash": project_workbench_hash(project) if workbench_ok else "",
        "itemIds": item_ids,
        "updatedAt": now_iso(),
    }


def create_project_workorder(payload: dict[str, Any]) -> dict[str, Any]:
    if not project_workbench_enabled():
        raise OwnerError("project workbench is disabled", HTTPStatus.FORBIDDEN)
    project_root = project_root_from_payload(payload)
    workorder_id = clean_workorder_id(payload.get("workorder_id")) or new_workorder_id()
    text = str(payload.get("content") or "")
    if not text.strip():
        raise OwnerError("missing workorder content")
    workorders_root = project_root / "00-system" / "workorders"
    path = workorders_root / f"{workorder_id}.md"
    if path.exists():
        raise OwnerError("workorder already exists", HTTPStatus.CONFLICT)
    workorders_root.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise OwnerError("failed to write workorder", HTTPStatus.INTERNAL_SERVER_ERROR) from exc
    ignored = ensure_workorders_git_ignored(project_root)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "ok": True,
        "id": workorder_id,
        "path": str(path),
        "relative_path": str(path.relative_to(project_root)),
        "sha256": digest,
        "gitIgnored": ignored,
        "updatedAt": now_iso(),
    }


def verify_history_jsonl(path: Path, workorder_id: str) -> tuple[int, list[str]]:
    if not path.exists():
        return 0, []
    errors: list[str] = []
    count = 0
    required = {"ts", "project_id", "item_id", "type", "title", "final_status", "summary", "evidence", "actor"}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"history line {line_no} is invalid JSON")
            continue
        if isinstance(record, dict) and record.get("workorder_id") == workorder_id:
            count += 1
            missing = [key for key in required if not compact_text(record.get(key))]
            if missing:
                errors.append(f"history line {line_no} missing {','.join(missing)}")
    return count, errors


def verify_project_workorder(payload: dict[str, Any]) -> dict[str, Any]:
    project_root = project_root_from_payload(payload)
    workorder_id = clean_workorder_id(payload.get("workorder_id"))
    receipt_ready, workbench_ok, workbench, item_ids = read_project_workorder_state(project_root, workorder_id)
    review_result = compact_text(payload.get("result")).lower()
    if review_result == "pass":
        event_type = "controller_verify_pass"
        final_status = "completed"
        default_summary = "Workorder receipt verified by Faryo controller."
    elif review_result == "fail":
        event_type = "controller_verify_fail"
        final_status = "needs_fix"
        default_summary = "Workorder receipt needs fixes after Faryo controller review."
    else:
        raise OwnerError("invalid verify result", HTTPStatus.BAD_REQUEST)
    transitioned = False
    transition_error = ""
    if receipt_ready and workbench_ok and item_ids:
        try:
            transition = apply_workbench_transition({
                "project_root": str(project_root),
                "event_type": event_type,
                "item_ids": item_ids,
                "workorder_id": workorder_id,
                "actor": compact_text(payload.get("actor")) or "faryo-controller",
                "source": "workorder-verify",
                "summary": compact_text(payload.get("summary")) or default_summary,
                "evidence": compact_text(payload.get("evidence")) or "Receipt present and workbench parsed.",
                "final_status": final_status,
            })
            workbench = transition.get("project") if isinstance(transition.get("project"), dict) else read_project_workbench_file(project_root)
            transitioned = True
        except OwnerError as exc:
            transition_error = str(exc)
    history_count, history_errors = verify_history_jsonl(project_root / "00-system" / "workbench.history.jsonl", workorder_id)
    expected_history_rows = len(item_ids) if item_ids else 1
    closed = review_result == "pass" and receipt_ready and workbench_ok and history_count >= expected_history_rows and not history_errors and not transition_error
    needs_fix = review_result == "fail" and receipt_ready and workbench_ok and transitioned and not transition_error
    return {
        "ok": True,
        "closed": closed,
        "needsFix": needs_fix,
        "reviewResult": "fail" if event_type == "controller_verify_fail" else "pass",
        "receiptReady": receipt_ready,
        "workbenchOk": workbench_ok,
        "workbenchHash": project_workbench_hash(workbench) if workbench_ok else "",
        "project": workbench if workbench_ok else {},
        "historyRows": history_count,
        "historyErrors": history_errors,
        "transitioned": transitioned,
        "transitionError": transition_error,
        "updatedAt": now_iso(),
    }


def import_project_workbench(payload: dict[str, Any]) -> dict[str, Any]:
    if not project_workbench_enabled():
        raise OwnerError("project workbench is disabled", HTTPStatus.FORBIDDEN)
    project_root, path = project_workbench_import_path(compact_text(payload.get("project_root") or payload.get("path")))
    if path.is_file():
        try:
            source = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise OwnerError("invalid workbench.json", HTTPStatus.BAD_REQUEST) from exc
        if not isinstance(source, dict):
            raise OwnerError("workbench must be a JSON object", HTTPStatus.BAD_REQUEST)
        project = clean_project_workbench(source)
    else:
        project = clean_project_workbench({
            "id": project_slug(project_root.name),
            "name": project_root.name,
            "brief": "",
            "current_d": "",
            "items": [],
        })
        write_project_workbench_file(path, project)
    definition_path = ensure_project_definition_file(project_root, project)
    definition = pd_state.parse_project_definition(definition_path.read_text(encoding="utf-8"))
    if not definition:
        pd_state.write_project_definition(definition_path, initial_project_definition(project))
        definition = pd_state.parse_project_definition(definition_path.read_text(encoding="utf-8"))
    row = dict(project)
    row["path"] = str(path)
    row["workbench_path"] = str(path)
    row["definition"] = definition
    return {"ok": True, "project": row, "updatedAt": now_iso()}


def gateway_json_request(config: Config, gateway_url: str, path: str, payload: dict[str, Any], timeout: float = 20) -> dict[str, Any]:
    base = gateway_url.rstrip("/")
    if not base:
        raise OwnerError("missing gateway_url")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        base + path,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Owner-Token": config.token,
            "X-Faryo-Owner-Label": quote(owner_label().strip()[:32], safe="-._~"),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OwnerError(f"gateway HTTP {exc.code}: {detail}", HTTPStatus.BAD_GATEWAY) from exc
    except urllib.error.URLError as exc:
        raise OwnerError(f"gateway unreachable: {exc.reason}", HTTPStatus.BAD_GATEWAY) from exc
    try:
        result = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise OwnerError("gateway returned invalid JSON", HTTPStatus.BAD_GATEWAY) from exc
    if not isinstance(result, dict) or not result.get("ok"):
        raise OwnerError(str((result or {}).get("error") or "gateway request failed"), HTTPStatus.BAD_GATEWAY)
    return result


def apply_project_workbench_downlink(config: Config, payload: dict[str, Any]) -> dict[str, Any]:
    if not project_workbench_enabled():
        raise OwnerError("project workbench is disabled", HTTPStatus.FORBIDDEN)
    gateway_url = compact_text(payload.get("gateway_url") or env_value("FARYO_PROJECT_WORKBENCH_GATEWAY_URL"))
    package_id = compact_text(payload.get("package_id"))
    if not package_id:
        raise OwnerError("missing package_id")
    claim = gateway_json_request(config, gateway_url, "/api/project-workbench/downlink/claim", {"package_id": package_id})
    package = claim.get("package") if isinstance(claim.get("package"), dict) else {}
    projects = package.get("projects") if isinstance(package.get("projects"), list) else []
    if not projects:
        raise OwnerError("downlink package has no projects")
    scope = compact_text(package.get("scope")) or "project"
    if scope not in {"project", "definition"}:
        raise OwnerError("invalid downlink scope", HTTPStatus.BAD_REQUEST)
    raw_projects = [project for project in projects if isinstance(project, dict)]
    if scope == "definition" and any(not isinstance(project.get("definition"), dict) for project in raw_projects):
        raise OwnerError("missing project definition", HTTPStatus.BAD_REQUEST)
    targets = [(project_workbench_path(project), clean_project_workbench(project), project.get("definition") if isinstance(project.get("definition"), dict) else None) for project in raw_projects]
    paths = [path for path, _project, _definition in targets]
    if len({str(path) for path in paths}) != len(paths):
        raise OwnerError("duplicate project workbench target", HTTPStatus.BAD_REQUEST)
    expected_hashes = {project_slug(project.get("id") or project.get("name")): compact_text(project.get("hash")) for project in raw_projects}
    staged: list[tuple[Path, Path]] = []
    if scope == "project":
        try:
            staged = [(path, stage_project_workbench_file(path, project)) for path, project, _definition in targets]
            for path, tmp in staged:
                os.replace(tmp, path)
        except OSError as exc:
            cleanup_staged_project_workbenches(staged)
            raise OwnerError("failed to write project workbench", HTTPStatus.INTERNAL_SERVER_ERROR) from exc
    else:
        for path, project, _definition in targets:
            try:
                update_project_workbench_summary(path, project)
            except OSError as exc:
                raise OwnerError("failed to write project workbench summary", HTTPStatus.INTERNAL_SERVER_ERROR) from exc
    hashes = {}
    for path, project, definition in targets:
        if isinstance(definition, dict):
            actual_definition = apply_project_definition_downlink(path, project, definition)
        else:
            actual_definition = None
        if scope == "definition":
            expected_definition = pd_state.project_definition_hash_payload(definition)
            actual_definition = pd_state.project_definition_hash_payload(actual_definition)
            hashes[project["id"]] = pd_state.project_definition_downlink_hash(project["id"], {key: actual_definition.get(key) for key in expected_definition})
        else:
            stored = json.loads(path.read_text(encoding="utf-8"))
            actual = clean_project_workbench(stored if isinstance(stored, dict) else {})
            hashes[project["id"]] = project_downlink_hash(actual, actual_definition)
    mismatched = [project_id for project_id, digest in expected_hashes.items() if digest and hashes.get(project_id) != digest]
    ok = not mismatched
    ack = gateway_json_request(config, gateway_url, "/api/project-workbench/downlink/ack", {
        "package_id": package_id,
        "ok": ok,
        "status": "applied" if ok else "failed",
        "applied": len(targets) if ok else 0,
        "hashes": hashes,
        "message": ("hash mismatch: " + ", ".join(mismatched)) if mismatched else "",
    })
    if not ok:
        raise OwnerError("downlink hash mismatch: " + ", ".join(mismatched), HTTPStatus.CONFLICT)
    return {"ok": True, "status": "applied", "package_id": package_id, "applied": len(targets), "ack_ok": bool(ack.get("ok")), "updatedAt": now_iso()}


class MultipartFile:
    def __init__(self, filename: str, content_type: str, data: bytes) -> None:
        self.filename = filename
        self.type = content_type
        self.file = io.BytesIO(data)


def send_delivery_record_path(delivery_id: str) -> Path | None:
    clean_id = clean_client_message_id(delivery_id)
    return SEND_DELIVERY_ROOT / f"{clean_id}.json" if clean_id else None


def cleanup_persisted_send_deliveries(now_epoch: float | None = None, *, force: bool = False) -> None:
    global _send_delivery_cleanup_at
    monotonic_now = time.monotonic()
    if not force and monotonic_now - _send_delivery_cleanup_at < SEND_DELIVERY_CLEANUP_INTERVAL_SECONDS:
        return
    _send_delivery_cleanup_at = monotonic_now
    cutoff = (now_epoch if now_epoch is not None else time.time()) - SEND_DELIVERY_TTL_SECONDS
    try:
        paths = list(SEND_DELIVERY_ROOT.iterdir())
    except OSError:
        return
    for path in paths:
        if path.suffix != ".json" or clean_client_message_id(path.stem) != path.stem:
            continue
        try:
            stat = path.lstat()
            if path.is_symlink() or stat.st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def persist_send_delivery(delivery_id: str, state: dict[str, Any]) -> bool:
    path = send_delivery_record_path(delivery_id)
    status = str(state.get("status") or "")
    receipt = state.get("receipt")
    if path is None or status not in {"pasted", "accepted"}:
        return False
    if status == "accepted" and not isinstance(receipt, dict):
        return False
    record = {
        "version": 2,
        "deliveryId": delivery_id,
        "session": str(state.get("session") or ""),
        "digest": str(state.get("digest") or ""),
        "status": status,
        "updatedEpoch": float(state.get("updatedEpoch") or time.time()),
    }
    if status == "accepted":
        record["receipt"] = receipt
    else:
        record["pasteReady"] = bool(state.get("pasteReady"))
        try:
            record["queuedBaseline"] = max(0, int(state.get("queuedBaseline") or 0))
        except (TypeError, ValueError):
            record["queuedBaseline"] = 0
        for key in ("rolloutDevice", "rolloutInode", "rolloutOffset"):
            try:
                value = int(state.get(key))
            except (TypeError, ValueError):
                continue
            if value >= 0:
                record[key] = value
    tmp_path: str | None = None
    try:
        SEND_DELIVERY_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(SEND_DELIVERY_ROOT, 0o700)
        fd, tmp_path = tempfile.mkstemp(prefix=".delivery-", suffix=".tmp", dir=SEND_DELIVERY_ROOT)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, separators=(",", ":"))
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
        try:
            directory_fd = os.open(SEND_DELIVERY_ROOT, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return True
    except OSError:
        return False
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def load_persisted_send_delivery(delivery_id: str, now_epoch: float | None = None) -> dict[str, Any] | None:
    path = send_delivery_record_path(delivery_id)
    if path is None:
        return None
    try:
        stat = path.lstat()
        if path.is_symlink() or stat.st_size > 16 * 1024:
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    updated_epoch = record.get("updatedEpoch")
    try:
        updated_epoch = float(updated_epoch)
    except (TypeError, ValueError):
        return None
    if (now_epoch if now_epoch is not None else time.time()) - updated_epoch > SEND_DELIVERY_TTL_SECONDS:
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
        "updatedAt": time.monotonic(),
        "updatedEpoch": updated_epoch,
    }
    if status == "accepted":
        state["receipt"] = receipt
    else:
        state["pasteReady"] = bool(record.get("pasteReady"))
        try:
            state["queuedBaseline"] = max(0, int(record.get("queuedBaseline") or 0))
        except (TypeError, ValueError):
            state["queuedBaseline"] = 0
        for key in ("rolloutDevice", "rolloutInode", "rolloutOffset"):
            try:
                value = int(record.get(key))
            except (TypeError, ValueError):
                continue
            if value >= 0:
                state[key] = value
    return state


def remember_accepted_send_delivery(delivery_id: str, state: dict[str, Any]) -> None:
    state["updatedAt"] = time.monotonic()
    state["updatedEpoch"] = time.time()
    _send_deliveries[delivery_id] = state
    persist_send_delivery(delivery_id, state)


def remember_pasted_send_delivery(delivery_id: str, state: dict[str, Any]) -> None:
    state["updatedAt"] = time.monotonic()
    state["updatedEpoch"] = time.time()
    _send_deliveries[delivery_id] = state
    persist_send_delivery(delivery_id, state)


def prune_send_deliveries(now: float | None = None) -> None:
    with _send_delivery_lock:
        cutoff = (now if now is not None else time.monotonic()) - SEND_DELIVERY_TTL_SECONDS
        for delivery_id in [key for key, value in _send_deliveries.items() if float(value.get("updatedAt") or 0) < cutoff]:
            _send_deliveries.pop(delivery_id, None)
        cleanup_persisted_send_deliveries()


def send_delivery_receipt(delivery_id: str, config: Config, state: str, enter_attempts: int, *, duplicate: bool = False) -> dict[str, Any]:
    return {
        "deliveryId": delivery_id,
        "delivery": "accepted",
        "deliveryState": state,
        "session": config.session,
        "enterAttempts": enter_attempts,
        "duplicate": duplicate,
    }


def send_text(config: Config, text: str, client_message_id: str | None = None) -> dict[str, Any]:
    if not has_session(config):
        raise OwnerError(f"tmux session not found: {config.session}", HTTPStatus.NOT_FOUND)
    if not text.strip():
        raise OwnerError("empty text")
    if len(text) > MAX_SEND_CHARS:
        raise OwnerError(f"text too long: {len(text)} > {MAX_SEND_CHARS}", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    if client_message_id and not clean_client_message_id(client_message_id):
        raise OwnerError("invalid client message id")
    delivery_id = clean_client_message_id(client_message_id) or uuid.uuid4().hex
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    line = text.strip()
    words = line.split()
    launch_command = Path(words[0]).name.lower() if words else ""
    shell_prep = bool(words and (launch_command in AGENT_LAUNCH_COMMANDS or SHELL_PREP_RE.fullmatch(line)))
    with send_session_delivery_lock(config.session), send_message_delivery_lock(delivery_id):
        now = time.monotonic()
        prune_send_deliveries(now)
        existing = _send_deliveries.get(delivery_id) or load_persisted_send_delivery(delivery_id)
        if existing and delivery_id not in _send_deliveries:
            _send_deliveries[delivery_id] = existing
        if existing and (existing.get("session") != config.session or existing.get("digest") != digest):
            raise OwnerError("client message id was already used for different content", HTTPStatus.CONFLICT)
        if existing and existing.get("status") == "accepted":
            receipt = dict(existing["receipt"])
            receipt["duplicate"] = True
            existing["updatedAt"] = now
            existing["updatedEpoch"] = time.time()
            persist_send_delivery(delivery_id, existing)
            return receipt

        if shell_prep and not agent_in_pane(config):
            for keys in (["-l", line], ["Enter"]):
                res = tmux(config, ["send-keys", "-t", tmux_target(config), *keys], timeout=3)
                if res.returncode != 0:
                    raise OwnerError(res.stderr.strip() or "tmux send shell prep failed", HTTPStatus.INTERNAL_SERVER_ERROR)
            receipt = send_delivery_receipt(delivery_id, config, "shell", 1)
            remember_accepted_send_delivery(delivery_id, {"session": config.session, "digest": digest, "status": "accepted", "receipt": receipt})
            return receipt

        profile = agent_profile_in_pane(config)
        continuing_paste = bool(existing and existing.get("status") == "pasted")
        if profile is CODEX_PROFILE and not continuing_paste and codex_composer_has_draft(config):
            raise OwnerError("Codex TUI already has an unsent draft; the browser draft was kept", HTTPStatus.CONFLICT)
        fresh_rollout_probe = codex_rollout_submission_probe(config) if profile is CODEX_PROFILE else None
        rollout_probe = (
            codex_rollout_probe_from_state(config, existing)
            if profile is CODEX_PROFILE and continuing_paste and existing
            else fresh_rollout_probe
        )
        if profile is CODEX_PROFILE and rollout_probe is None:
            rollout_probe = fresh_rollout_probe
        queued_baseline = max(0, int(existing.get("queuedBaseline") or 0)) if continuing_paste and existing else 0

        if not continuing_paste:
            buffer_name = f"local-tmux-owner-{secrets.token_hex(4)}"
            tmp_path: str | None = None
            try:
                baseline = tmux_capture_compact(config)
                baseline_cursor = tmux_cursor_position(config)
                queued_baseline = codex_queued_followup_count(tmux_current_capture(config), text) if profile is CODEX_PROFILE else 0
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, prefix="local-tmux-owner-", suffix=".txt") as tmp:
                    tmp.write(text)
                    tmp_path = tmp.name
                res = tmux(config, ["load-buffer", "-b", buffer_name, tmp_path], timeout=3)
                if res.returncode != 0:
                    raise OwnerError(res.stderr.strip() or "tmux load-buffer failed", HTTPStatus.INTERNAL_SERVER_ERROR)
                paste_args = ["paste-buffer", "-d", "-r", "-b", buffer_name, "-t", tmux_target(config)]
                paste_args.insert(2, "-p")
                res = tmux(config, paste_args, timeout=3)
                if res.returncode != 0:
                    raise OwnerError(res.stderr.strip() or "tmux paste-buffer failed", HTTPStatus.INTERNAL_SERVER_ERROR)
                paste_ready = wait_for_paste_tail(config, text, baseline, baseline_cursor)
                if not paste_ready:
                    raise OwnerError("text paste could not be confirmed; the browser draft was kept", HTTPStatus.GATEWAY_TIMEOUT)
                pasted_state = {
                    "session": config.session,
                    "digest": digest,
                    "status": "pasted",
                    "pasteReady": True,
                    "queuedBaseline": queued_baseline,
                    **codex_rollout_probe_state(rollout_probe),
                }
                remember_pasted_send_delivery(delivery_id, pasted_state)
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except FileNotFoundError:
                        pass
                tmux(config, ["delete-buffer", "-b", buffer_name], timeout=1)
            time.sleep(PASTE_SETTLE_SECONDS)
        elif profile is CODEX_PROFILE and not codex_composer_contains_text(config, text):
            recovered_state = wait_for_codex_submission(
                config,
                text,
                timeout=0.35,
                rollout_probe=rollout_probe,
                queued_baseline=queued_baseline,
                allow_composer_disappearance=False,
            )
            if not recovered_state:
                existing["updatedAt"] = time.monotonic()
                existing["updatedEpoch"] = time.time()
                persist_send_delivery(delivery_id, existing)
                raise OwnerError(
                    "previous delivery is still ambiguous; no rollout or new queue evidence was found and nothing was sent again",
                    HTTPStatus.GATEWAY_TIMEOUT,
                )
            receipt = send_delivery_receipt(delivery_id, config, recovered_state, 0)
            existing.update({"status": "accepted", "receipt": receipt})
            remember_accepted_send_delivery(delivery_id, existing)
            return receipt

        enter_attempts = 0
        accepted_state: str | None = None
        key_attempts = SEND_KEY_MAX_ATTEMPTS if profile is CODEX_PROFILE else 1
        for _attempt in range(key_attempts):
            enter_attempts += 1
            key = codex_submission_key(config) if profile is CODEX_PROFILE else "C-m"
            res = tmux(config, ["send-keys", "-t", tmux_target(config), key], timeout=3)
            if res.returncode != 0:
                raise OwnerError(res.stderr.strip() or f"tmux send {key} failed", HTTPStatus.INTERNAL_SERVER_ERROR)
            if profile is CODEX_PROFILE:
                accepted_state = wait_for_codex_submission(
                    config,
                    text,
                    rollout_probe=rollout_probe,
                    queued_baseline=queued_baseline,
                    allow_composer_disappearance=key != "Tab",
                )
                if accepted_state:
                    break
                time.sleep(SEND_ACCEPT_RETRY_DELAY)
            else:
                accepted_state = "sent"
                break

        if not accepted_state:
            state = _send_deliveries[delivery_id]
            state["updatedAt"] = time.monotonic()
            state["updatedEpoch"] = time.time()
            persist_send_delivery(delivery_id, state)
            raise OwnerError("Codex did not accept the submit key; the browser and TUI drafts were kept for retry", HTTPStatus.GATEWAY_TIMEOUT)

        receipt = send_delivery_receipt(delivery_id, config, accepted_state, enter_attempts)
        remember_accepted_send_delivery(delivery_id, {
            "session": config.session,
            "digest": digest,
            "status": "accepted",
            "receipt": receipt,
        })
        return receipt


def send_key(config: Config, key: str) -> None:
    if not has_session(config):
        raise OwnerError(f"tmux session not found: {config.session}", HTTPStatus.NOT_FOUND)
    res = tmux(config, ["send-keys", "-t", tmux_target(config), key], timeout=3)
    if res.returncode != 0:
        raise OwnerError(res.stderr.strip() or f"tmux send {key} failed", HTTPStatus.INTERNAL_SERVER_ERROR)


class Handler(SimpleHTTPRequestHandler):
    server_version = "FaryoOwner/0.1"

    def __init__(self, *args: Any, directory: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    @property
    def config(self) -> Config:
        return self.server.config  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        message = fmt % args
        message = re.sub(r"([?&]token=)[^&\s]+", r"\1<redacted>", message)
        sys.stderr.write("[%s] %s\n" % (now_iso(), message))

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "; ".join([
                "default-src 'self'",
                "script-src 'self'",
                "script-src-attr 'none'",
                "style-src 'self' 'unsafe-inline'",
                "img-src 'self' data: blob:",
                "font-src 'self'",
                "connect-src 'self'",
                "worker-src 'self'",
                "object-src 'none'",
                "base-uri 'none'",
                "frame-ancestors 'none'",
                "form-action 'self'",
            ]),
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        super().end_headers()

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/events":
                self.require_token(parsed)
                self.write_events(parsed)
                return
            if parsed.path == "/api/status":
                self.require_token(parsed)
                target = self.target_from_query(parsed)
                ensure_pane_width(target)
                payload = status_payload(target)
                header_label = clean_owner_label(self.headers.get("X-Faryo-Owner-Label"))
                if header_label:
                    payload["ownerLabel"] = header_label
                self.write_json(payload)
                return
            if parsed.path == "/api/agent-sessions":
                self.require_token(parsed)
                query = parse_qs(parsed.query)
                try:
                    limit = max(1, min(int(query.get("limit", [str(AGENT_SESSION_LIST_LIMIT)])[0]), AGENT_SESSION_QUERY_LIMIT))
                    offset = max(0, int(query.get("offset", ["0"])[0]))
                except ValueError as exc:
                    raise OwnerError("invalid agent session pagination") from exc
                if query.get("view", [""])[0] == "split":
                    payload = agent_session_page(self.config, limit, offset, self.history_root())
                else:
                    items = self.agent_session_items()
                    payload = {"sessions": items[offset:offset + limit]}
                self.write_json({"ok": True, **payload, "activeCount": active_agent_count(self.config), "updatedAt": now_iso()})
                return
            if parsed.path == "/api/conversation-history":
                self.require_token(parsed)
                query = parse_qs(parsed.query)
                target = self.target_from_query(parsed)
                try:
                    limit = int(query.get("limit", [str(CODEX_HISTORY_PAGE_TURNS)])[0])
                    around_value = query.get("around", [""])[0]
                    around = int(around_value) if around_value != "" else None
                except ValueError as exc:
                    raise OwnerError("invalid conversation history pagination") from exc
                self.write_json(codex_history_page_for_config(
                    target,
                    limit=limit,
                    cursor=query.get("cursor", [""])[0],
                    around=around,
                ))
                return
            if parsed.path == "/api/directories":
                self.require_token(parsed)
                query = parse_qs(parsed.query)
                self.write_json(directory_browser_payload(
                    self.config,
                    query.get("path", [""])[0],
                    self.workspace_root(),
                ))
                return
            if parsed.path == "/api/capture":
                self.require_token(parsed)
                query = parse_qs(parsed.query)
                target = self.target_from_query(parsed)
                ensure_pane_width(target)
                try:
                    lines = int(query.get("lines", [str(CAPTURE_DEFAULT_LINES)])[0])
                except ValueError:
                    lines = CAPTURE_DEFAULT_LINES
                profile = agent_profile_in_pane(target) or RUNTIME_PROFILE
                want_html = query.get("format", [""])[0] == "html" or query.get("html", [""])[0].lower() in {"1", "true", "yes"}
                text = capture_text(target, lines, profile)
                terminal_text = text
                agent_running = bool(profile is not RUNTIME_PROFILE and not agent_ready_for_input(target, profile))
                capture_source = "tmux"
                thread_id = ""
                live_text = ""
                if profile is CODEX_PROFILE and not want_html:
                    structured = codex_structured_capture(target, lines)
                    if structured:
                        text, thread_id, capture_source = structured
                        if agent_running:
                            live_text = codex_live_tail(terminal_text)
                payload = {
                    "ok": True,
                    "text": text,
                    "agentRunning": agent_running,
                    "agentSource": profile.source,
                    "agentProfile": profile.key,
                    "captureSource": capture_source,
                    "updatedAt": now_iso(),
                }
                if thread_id:
                    payload.update(codex_capture_session_metadata(thread_id))
                if live_text:
                    payload["liveText"] = live_text
                if want_html:
                    payload["html"] = capture_html(target, lines, profile)
                self.write_json(payload)
                return
            if parsed.path == "/api/local-image":
                self.require_token(parsed)
                query = parse_qs(parsed.query)
                path = resolve_local_image_path(query.get("path", [""])[0], self.target_from_query(parsed), self.workspace_root())
                self.write_file(path, IMAGE_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"))
                return
            if parsed.path == "/api/local-file":
                self.require_token(parsed)
                query = parse_qs(parsed.query)
                path = resolve_local_path(query.get("path", [""])[0], self.target_from_query(parsed), LOCAL_FILE_SUFFIXES, self.workspace_root())
                self.write_file(path, LOCAL_FILE_CONTENT_TYPES[path.suffix.lower()], query.get("download", [""])[0] in {"1", "true", "yes"})
                return
            if parsed.path == "/api/local-file/view":
                self.require_token(parsed)
                query = parse_qs(parsed.query)
                self.write_local_file_view(query.get("path", [""])[0], self.target_from_query(parsed), query.get("token", [None])[0], query.get("session", [None])[0])
                return
            if parsed.path == "/health":
                self.write_json({"ok": True, "updatedAt": now_iso()})
                return
            if parsed.path in {"/", "/index.html"}:
                self.write_index()
                return
            if parsed.path.lstrip("/") in SHARED_STATIC_FILES:
                filename = parsed.path.lstrip("/")
                self.write_file(SHARED_STATIC_DIR / filename, SHARED_STATIC_FILES[filename])
                return
            return super().do_GET()
        except OwnerError as exc:
            self.write_json({"ok": False, "error": str(exc), "updatedAt": now_iso()}, status=exc.status)

    def send_event(self, event: str, payload: dict[str, Any]) -> bool:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return False

    def send_event_heartbeat(self) -> bool:
        try:
            self.wfile.write(b": keepalive\n\n")
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return False

    def write_events(self, parsed: Any) -> None:
        query = parse_qs(parsed.query)
        target = self.target_from_query(parsed)
        server = self.server
        assert isinstance(server, OwnerServer)
        if not server.begin_event_stream():
            self.write_json({"ok": False, "error": "too many event streams", "updatedAt": now_iso()}, status=HTTPStatus.TOO_MANY_REQUESTS)
            return
        try:
            lines = int(query.get("lines", [str(CAPTURE_COMPACT_LINES)])[0])
        except ValueError:
            lines = CAPTURE_COMPACT_LINES
        lines = max(40, min(lines, CAPTURE_MAX_LINES))
        ensure_pane_width(target)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-transform")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last_hash = ""
        last_running = None
        last_write = time.monotonic()
        deadline = time.monotonic() + EVENT_STREAM_MAX_SECONDS
        try:
            while time.monotonic() < deadline:
                try:
                    profile = agent_profile_in_pane(target); capture_profile = profile or RUNTIME_PROFILE
                    text = capture_text(target, lines, capture_profile)
                    terminal_text = text
                    capture_source = "tmux"
                    thread_id = ""
                    live_text = ""
                    agent_running = bool(profile and not agent_ready_for_input(target, capture_profile))
                    if profile is CODEX_PROFILE:
                        structured = codex_structured_capture(target, lines)
                        if structured:
                            text, thread_id, capture_source = structured
                            if agent_running:
                                live_text = codex_live_tail(terminal_text)
                    session_metadata = codex_capture_session_metadata(thread_id)
                    digest = capture_event_digest(text, live_text, session_metadata)
                    if digest != last_hash or agent_running != last_running:
                        last_hash = digest
                        last_running = agent_running
                        payload = {"ok": True, "text": text, "agentRunning": agent_running, "agentSource": capture_profile.source, "agentProfile": capture_profile.key, "captureSource": capture_source, "updatedAt": now_iso()}
                        if thread_id:
                            payload.update(session_metadata)
                        if live_text:
                            payload["liveText"] = live_text
                        if not self.send_event("capture", payload):
                            return
                        last_write = time.monotonic()
                    elif time.monotonic() - last_write >= EVENT_STREAM_HEARTBEAT_SECONDS:
                        if not self.send_event_heartbeat():
                            return
                        last_write = time.monotonic()
                except OwnerError:
                    return
                time.sleep(1.0)
        finally:
            server.end_event_stream()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            self.require_token(parsed)
            if parsed.path == "/api/attachment":
                form = self.read_multipart_form()
                if "file" not in form:
                    raise OwnerError("missing file field: file")
                file_item = form["file"]
                if isinstance(file_item, list):
                    file_item = file_item[0] if file_item else None
                if file_item is None or not getattr(file_item, "filename", ""):
                    raise OwnerError("missing file field: file")
                path, size, kind = save_uploaded_attachment(file_item, self.file_inbox_root())
                self.write_json({"ok": True, "path": str(path), "bytes": size, "kind": kind, "updatedAt": now_iso()})
                return
            payload = self.read_json()
            if parsed.path == "/api/agent/new":
                workspace_root = self.workspace_root()
                raw_cwd = compact_text(payload.get("cwd") or payload.get("project_root"))
                if raw_cwd:
                    cwd, _roots = resolve_start_directory(raw_cwd, workspace_root)
                    cwd_token = str(payload.get("cwd_token") or payload.get("cwdToken") or "").strip()
                    if cwd_token and not hmac.compare_digest(cwd_token, directory_selection_token(self.config, cwd)):
                        raise OwnerError("working directory selection expired", HTTPStatus.CONFLICT)
                else:
                    cwd = Path(workspace_root or get_pane_cwd(self.config) or str(Path.home())).expanduser(); cwd = cwd if cwd.is_dir() else Path.home()
                command = clean_agent_launch_command(str(payload.get("command") or ""))
                if not command:
                    raise OwnerError("invalid launch command")
                title = clean_session_title(payload.get("title"))
                name = start_agent_runtime(self.config, cwd, command, [], bounded_max_running(payload), wait_ready=True, title=title)
                self.write_json({"ok": True, "session": name, "updatedAt": now_iso()})
                return
            if parsed.path == "/api/agent/cleanup-idle":
                idle_seconds = max(60, min(int(payload.get("idle_seconds") or payload.get("idleSeconds") or 0), MAX_MANAGED_AGENT_IDLE_SECONDS))
                cleanup_managed_sessions(self.config, idle_seconds)
                self.write_json({"ok": True, "updatedAt": now_iso()})
                return
            if parsed.path == "/api/project-workbench/downlink/apply":
                self.write_json(apply_project_workbench_downlink(self.config, payload))
                return
            if parsed.path == "/api/project-workbench/definition":
                self.write_json(project_definition_payload(payload))
                return
            if parsed.path == "/api/project-workbench/definition-sync":
                self.write_json(sync_project_definition(payload))
                return
            if parsed.path == "/api/workbench/transition":
                self.write_json(apply_workbench_transition(payload))
                return
            if parsed.path == "/api/workbench/status":
                self.write_json(project_workbench_status(payload))
                return
            if parsed.path == "/api/project-workbench/git-status":
                self.write_json(project_git_status(payload))
                return
            if parsed.path == "/api/workorder/create":
                self.write_json(create_project_workorder(payload))
                return
            if parsed.path == "/api/workorder/status":
                self.write_json(project_workorder_status(payload))
                return
            if parsed.path == "/api/workorder/verify":
                self.write_json(verify_project_workorder(payload))
                return
            if parsed.path == "/api/project-workbench/import":
                self.write_json(import_project_workbench(payload))
                return
            if parsed.path == "/api/session/close":
                close_shell_session(self.config, str(payload.get("session") or ""))
                self.write_json({"ok": True, "updatedAt": now_iso()})
                return
            if parsed.path == "/api/agent/resume":
                agent_session_id = clean_agent_session_id(str(payload.get("agent_session_id") or ""))
                source = str(payload.get("source") or "")
                if not agent_session_id:
                    raise OwnerError("missing agent session id")
                if not source:
                    raise OwnerError("missing agent source")
                session = resume_agent_session(self.config, agent_session_id, source, bounded_max_running(payload), self.history_root())
                self.write_json({"ok": True, "session": session, "updatedAt": now_iso()})
                return
            target = self.target_from_payload(payload)
            ensure_pane_width(target)
            if parsed.path == "/api/send":
                receipt = send_text(target, str(payload.get("text", "")), str(payload.get("clientMessageId") or ""))
                self.write_json({"ok": True, **receipt, "updatedAt": now_iso()})
                return
            if parsed.path == "/api/interrupt":
                profile = agent_profile_in_pane(target)
                on = bool(profile and not agent_ready_for_input(target, profile))
                if on: send_key(target, "Escape")
                self.write_json({"ok": True, "interrupted": on, "updatedAt": now_iso()})
                return
            if parsed.path == "/api/approve":
                send_key(target, "C-m")
                self.write_json({"ok": True, "updatedAt": now_iso()})
                return
            if parsed.path == "/api/up":
                send_key(target, "Up")
                self.write_json({"ok": True, "updatedAt": now_iso()})
                return
            if parsed.path == "/api/down":
                send_key(target, "Down")
                self.write_json({"ok": True, "updatedAt": now_iso()})
                return
        except OwnerError as exc:
            self.write_json({"ok": False, "error": str(exc), "updatedAt": now_iso()}, status=exc.status)
            return
        self.send_error(HTTPStatus.NOT_FOUND)


    def file_inbox_root(self) -> str | None:
        value = self.headers.get("X-Faryo-File-Inbox-Root")
        return value.strip() if value and value.strip() else None

    def workspace_root(self) -> str | None:
        value = self.headers.get("X-Faryo-Workspace-Root")
        return value.strip() if value and value.strip() else None

    def history_root(self) -> str | None: return (self.workspace_root() or "") if self.headers.get("X-Faryo-History-Scope", "").strip().lower() == "workspace" else None

    def target_from_query(self, parsed: Any) -> Config:
        session = parse_qs(parsed.query).get("session", [None])[0]
        return target_config(self.config, session)

    def target_from_payload(self, payload: dict[str, Any]) -> Config:
        session = str(payload.get("session") or "")
        return target_config(self.config, session)

    def agent_session_items(self) -> list[dict[str, Any]]:
        return agent_session_items(self.config, self.history_root())

    def read_multipart_form(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            raise OwnerError("expected multipart/form-data")
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError as exc:
            raise OwnerError("invalid content length") from exc
        if length <= 0:
            raise OwnerError("empty request")
        if length > MAX_ATTACHMENT_UPLOAD_BYTES + 1_000_000:
            raise OwnerError("request too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        raw = self.rfile.read(length)
        message = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + content_type.encode("utf-8") + b"\r\n\r\n" + raw
        )
        form: dict[str, Any] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            item = MultipartFile(
                part.get_filename() or "",
                part.get_content_type(),
                part.get_payload(decode=True) or b"",
            )
            if name in form:
                form[name] = form[name] + [item] if isinstance(form[name], list) else [form[name], item]
            else:
                form[name] = item
        return form

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 1_000_000:
            raise OwnerError("request too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OwnerError(f"invalid json: {exc}") from exc
        if not isinstance(data, dict):
            raise OwnerError("json body must be an object")
        return data

    def require_token(self, parsed: Any) -> None:
        expected = self.config.token
        query = parse_qs(parsed.query)
        got = self.headers.get("X-Owner-Token") or query.get("token", [None])[0]
        if not got or not secrets.compare_digest(got, expected):
            raise OwnerError("unauthorized", HTTPStatus.UNAUTHORIZED)

    def write_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "").lower()
        compressed = False
        if accepts_gzip and len(body) >= 1024:
            body = gzip.compress(body, compresslevel=6)
            compressed = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Accept-Encoding")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def write_file(self, path: Path, content_type: str, download: bool = False) -> None:
        try:
            size = path.stat().st_size
            fh = path.open("rb")
        except OSError as exc:
            raise OwnerError("file not found", HTTPStatus.NOT_FOUND) from exc
        with fh:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            filename = re.sub(r"[^A-Za-z0-9._-]", "_", path.name) or "file"
            disposition = "attachment" if download else "inline"
            self.send_header("Content-Disposition", f"{disposition}; filename=\"{filename}\"; filename*=UTF-8''{quote(path.name)}")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                shutil.copyfileobj(fh, self.wfile)
            except (BrokenPipeError, ConnectionResetError):
                return

    def write_index(self) -> None:
        try:
            html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        except OSError as exc:
            raise OwnerError("file not found", HTTPStatus.NOT_FOUND) from exc
        version = _html.escape(release_version() or "unknown", quote=True)
        body = html.replace("__FARYO_RELEASE_VERSION__", version).replace("__FARYO_RELEASE_NUMBER__", version.removeprefix("v")).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def write_local_file_view(self, raw: str, target: Config, token: str | None = None, session: str | None = None) -> None:
        path = resolve_local_path(raw, target, LOCAL_FILE_SUFFIXES, self.workspace_root())
        query = {"path": str(path)}
        if token:
            query["token"] = token
        if session:
            query["session"] = session
        raw_url = f"../local-file?{urlencode(query)}"
        download_url = f"../local-file?{urlencode({**query, 'download': '1'})}"
        suffix = path.suffix.lower()
        title = _html.escape(path.name)
        if suffix in EXTERNAL_VIEWER_SUFFIXES:
            body = f"<section class='notice'><p>This file type opens best in the browser or a local app.</p><p><a class='pill' href='{raw_url}'>Open file</a> <a class='pill' href='{download_url}' download>Download</a></p></section>"
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            if suffix == ".json":
                try:
                    text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    pass
            body = f"<pre>{_html.escape(text)}</pre>"
        html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#F6F7F9"><title>{title}</title><style>
body{{margin:0;background:#F6F7F9;color:#202228;font:16px/1.58 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-text-size-adjust:100%}}
header{{position:sticky;top:0;z-index:2;display:flex;align-items:center;gap:8px;padding:calc(env(safe-area-inset-top) + 8px) 10px 8px;background:rgba(255,255,255,.96);border-bottom:1px solid #DDE1E8;backdrop-filter:blur(12px)}}
h1{{min-width:0;flex:1;margin:0;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
button,.pill{{min-height:34px;padding:0 10px;border:1px solid #DDE1E8;border-radius:999px;background:#FFFFFF;color:#202228;font:600 14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;text-decoration:none}}
main{{padding:14px 14px calc(env(safe-area-inset-bottom) + 22px)}}
pre{{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.58 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
.notice{{padding:12px;border:1px solid #DDE1E8;border-radius:12px;background:#FFFFFF}}
@media (prefers-color-scheme: dark){{body{{background:#0F1115;color:#ECEEF3}}header{{background:rgba(23,26,32,.96);border-color:#2C313B}}button,.pill,.notice{{background:#171A20;color:#ECEEF3;border-color:#2C313B}}}}
</style></head><body><header><button id="backButton" type="button">Back</button><h1>{title}</h1><a class="pill" href="{raw_url}">Raw</a><a class="pill" href="{download_url}" download>Download</a></header><main>{body}</main><script src="../../local-file-view.js"></script></body></html>"""
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_error(self, code: int | HTTPStatus, message: str | None = None, explain: str | None = None) -> None:
        status = HTTPStatus(code)
        self.write_json({"ok": False, "error": message or status.phrase, "updatedAt": now_iso()}, status=status)


class OwnerServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    config: Config

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._event_streams = 0
        self._event_streams_lock = threading.Lock()

    def begin_event_stream(self) -> bool:
        with self._event_streams_lock:
            if self._event_streams >= EVENT_STREAM_MAX_CONNECTIONS:
                return False
            self._event_streams += 1
            return True

    def end_event_stream(self) -> None:
        with self._event_streams_lock:
            self._event_streams = max(0, self._event_streams - 1)

    def server_bind(self) -> None:
        # http.server.HTTPServer normally calls socket.getfqdn(host) here.
        # On non-loopback bind addresses, reverse lookup can block startup
        # for several seconds, so keep binding deterministic and local.
        if self.allow_reuse_address:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Tmux Owner mobile web bridge")
    parser.add_argument("--host", default=env_value("FARYO_OWNER_HOST", default="127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(env_value("FARYO_OWNER_PORT", default=str(DEFAULT_PORT))))
    parser.add_argument("--session", default=env_value("FARYO_OWNER_DIRECT_SESSION", default=DEFAULT_SESSION))
    parser.add_argument("--token", default=env_value("FARYO_OWNER_TOKEN", default=""))
    parser.add_argument("--pane-width", type=int, default=int(env_value("FARYO_OWNER_PANE_WIDTH", default=str(DEFAULT_PANE_WIDTH))))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = args.token or secrets.token_urlsafe(24)
    config = Config(
        session=args.session,
        token=token,
        pane_width=args.pane_width,
    )
    try:
        ensure_pane_width(config)
    except OwnerError as exc:
        print(f"warning: {exc}", file=sys.stderr, flush=True)
    server = OwnerServer((args.host, args.port), Handler)
    server.config = config

    def stop(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    print(f"Local Tmux Owner listening on http://{args.host}:{args.port}/?token=<private-token>", flush=True)
    print(
        f"session={args.session} pane_width={config.pane_width}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopping", flush=True)
    finally:
        stop_codex_app_server()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
