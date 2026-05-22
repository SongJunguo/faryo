#!/usr/bin/env python3
"""Local Tmux Owner: tiny HTTP bridge from mobile browser to a fixed tmux pane.

This server intentionally exposes only fixed tmux operations:
status, capture, send text, interrupt, approve, and navigation keys.
"""

from __future__ import annotations

import argparse
import datetime as _dt
from email import policy
from email.parser import BytesParser
import gzip
import hashlib
import html as _html
import io
import json
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
import urllib.error
import urllib.request
from urllib.parse import parse_qs, quote, urlencode, urlparse

try:
    from rich.console import Console as RichConsole
    from rich.text import Text as RichText
except ImportError:  # pragma: no cover - runtime fallback for minimal environments
    RichConsole = None
    RichText = None

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
RELEASE_FILE = APP_DIR.parent / "RELEASE"
AGENT_STATE_DB = Path.home() / ".codex" / "state_5.sqlite"
CODEX_SESSION_INDEX = Path.home() / ".codex" / "session_index.jsonl"
CLAUDE_PROJECTS_ROOT = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).expanduser() / "projects"
DEFAULT_SESSION = "__faryo_no_default__"
DEFAULT_PORT = 8765
DEFAULT_PANE_WIDTH = 500
FALLBACK_OWNER_LABEL = "TMUX"
MAX_SEND_CHARS = 120_000
PASTE_READY_TIMEOUT = 1.2
PASTE_READY_POLL_INTERVAL = 0.05
PASTE_READY_MIN_PROBE_CHARS = 8
CAPTURE_COMPACT_LINES = 320
CAPTURE_FULL_LINES = 800
CAPTURE_DEFAULT_LINES = CAPTURE_FULL_LINES
CAPTURE_MAX_LINES = CAPTURE_FULL_LINES
EVENT_STREAM_MAX_SECONDS = 75
EVENT_STREAM_MAX_CONNECTIONS = 6
RATE_LIMIT_CACHE_TTL = 120.0
THREAD_COLUMNS = "id, title, rollout_path, tokens_used, model, reasoning_effort, cwd, updated_at, source, thread_source"
AGENT_SESSION_LIST_LIMIT = 20
EMPTY_MANAGED_SESSION_TTL_SECONDS = 60
MAX_MANAGED_AGENT_IDLE_SECONDS = 24 * 60 * 60
RUNTIME_LOCK = threading.RLock()
RELEASE_VERSION_CACHE: str | None = None
FARYO_OWNER_DATA = Path(os.environ.get("FARYO_OWNER_DATA", str(Path.home() / ".faryo" / "owner" / "data"))).expanduser()
FILE_INBOX_ROOT = Path(os.environ.get("FARYO_OWNER_INBOX_DIR", str(FARYO_OWNER_DATA / "inbox"))).expanduser()
CACHE_ROOT = Path(os.environ.get("FARYO_OWNER_CACHE_DIR", str(FARYO_OWNER_DATA / "cache"))).expanduser()
LOGS_ROOT = Path(os.environ.get("FARYO_OWNER_LOGS_DIR", str(FARYO_OWNER_DATA / "logs"))).expanduser()
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
PROJECT_ITEM_TYPES = {"decision", "action", "watch"}
PROJECT_DONE_STATUSES = {"accepted", "paused", "done", "skipped", "seen"}
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
}
LOCAL_FILE_SUFFIXES = set(LOCAL_FILE_CONTENT_TYPES)
EXTERNAL_VIEWER_SUFFIXES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".odp", ".ods", ".rtf"}
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
ANSI_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f]")
HTML_CODE_RE = re.compile(r"<code[^>]*>(.*)</code>", re.S)
RICH_PRE_RE = re.compile(r"^\s*<pre\b[^>]*>(.*)</pre>\s*$", re.S)
STYLE_ATTR_RE = re.compile(r'\sstyle="([^"]*)"')
SEPARATOR_RE = re.compile(r"^[\s─━═\-—_]{20,}$")
SEPARATOR_OUTPUT_RE = re.compile(r"^\s*(?:[└│]\s*)?(?:\d+:)?[\s─━═\-—_]{4,}$")
LONG_SEPARATOR_RE = re.compile(r"[─━═]{20,}")
AGENT_BOUNDARY_RE = re.compile(r"^[\s─━═\-—_]*(Worked for .*?)[\s─━═\-—_]*$", re.I)
AGENT_PLACEHOLDER_RE = re.compile(r"^\s*[›>]\s*Write tests for @filename\s*$", re.I)
USER_PROMPT_RE = re.compile(r"^\s*›\s+")
AGENT_INPUT_PROMPT_RE = re.compile(r"^\s*[›>](?:\s|$)")
AGENT_META_RE = re.compile(r"^\s*((?:gpt|o\d|claude)[\w.\- ]*)\s*·\s+(.+?)\s*$", re.I)
CLAUDE_USER_PROMPT_RE = re.compile(r"^\s*(?:[›>❯]\s+|[│┃]\s*[›>❯]\s+)")
CLAUDE_INPUT_PROMPT_RE = re.compile(r"^\s*(?:[›>❯](?:\s|$)|[│┃]\s*[›>❯](?:\s|$))")
CLAUDE_PROMPT_HINT_RE = re.compile(r"^\s*\? for shortcuts\b.*$", re.I)
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
SESSION_TITLE_NOISE_RE = re.compile(r"^(?:📁 |Ctx |(?:gpt|o\d|claude)[\w.\- ]+\s+(?:low|medium|high|xhigh)$)", re.I)
class AgentProfile(NamedTuple):
    key: str
    command: str
    source: str
    process_names: frozenset[str] = frozenset()
    input_prompt_re: Any = AGENT_INPUT_PROMPT_RE
    user_prompt_re: Any = USER_PROMPT_RE
    meta_re: Any = AGENT_META_RE
    boundary_re: Any = AGENT_BOUNDARY_RE
    placeholder_re: Any = AGENT_PLACEHOLDER_RE
    prompt_hint_re: Any = NO_AGENT_META_RE


CODEX_PROFILE = AgentProfile("codex", "codex", "codex-cli")
CLAUDE_PROFILE = AgentProfile("claude", "claude", "claude-code", frozenset({"claude"}), CLAUDE_INPUT_PROMPT_RE, CLAUDE_USER_PROMPT_RE, NO_AGENT_META_RE, AGENT_BOUNDARY_RE, AGENT_PLACEHOLDER_RE, CLAUDE_PROMPT_HINT_RE)
RUNTIME_PROFILE = AgentProfile("runtime", "", "runtime", frozenset(), NO_AGENT_META_RE, NO_AGENT_META_RE, NO_AGENT_META_RE, NO_AGENT_META_RE, NO_AGENT_META_RE, NO_AGENT_META_RE)
AGENT_PROFILES = (CODEX_PROFILE, CLAUDE_PROFILE)
AGENT_LAUNCH_COMMANDS = {profile.command for profile in AGENT_PROFILES}
AGENT_SOURCE_BY_COMMAND = {profile.command: profile.source for profile in AGENT_PROFILES}
_CLAUDE_DEEPSEEK_LAUNCHER = os.environ.get("FARYO_CLAUDE_DEEPSEEK_LAUNCHER", "").strip()
CLAUDE_DEEPSEEK_LAUNCHER = Path(_CLAUDE_DEEPSEEK_LAUNCHER).expanduser() if _CLAUDE_DEEPSEEK_LAUNCHER else None
BLACK_VALUES = {"#000", "#000000", "black", "rgb(0,0,0)", "rgb(0, 0, 0)"}
USER_INPUT_COLOR = "var(--user-input-color, #E0C29D)"
LOW_CONTRAST_TERMINAL_VALUES = {"#000080", "#0000aa", "#0000cd", "#0000ff", "blue"}
_rate_limit_cache: dict[str, Any] | None = None
_rate_limit_cache_at = 0.0
_rate_limit_lock = threading.Lock()


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
    labels = {owner_label(), "GCP", "HP", "PC", FALLBACK_OWNER_LABEL}
    lines = [line.strip() for line in str(value or "").replace("\r", "\n").split("\n") if line.strip()]
    topic = next((line for line in lines if line not in labels and not line.startswith(SESSION_GIT_PREFIXES) and not SESSION_TITLE_NOISE_RE.match(line)), "")
    return topic or fallback


def session_index_title(value: Any) -> str:
    return " ".join(str(value or "").replace("\r", "\n").split())


def session_git_label(cwd: str | None, cache: dict[str, str]) -> str:
    if not cwd:
        return ""
    if cwd not in cache:
        cache[cwd] = str((git_status(cwd) or {}).get("label") or "")
    return cache[cwd]


def env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None:
            return value
    return default


def env_flag(*names: str, default: bool = False) -> bool:
    value = env_value(*names, default="").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def default_owner_label() -> str:
    hostname = socket.gethostname().strip().lower()
    if not hostname:
        return FALLBACK_OWNER_LABEL
    if "hp" in hostname:
        return "HP"
    if hostname == "sl" or hostname.startswith("sl-") or hostname.endswith("-sl") or "-sl-" in hostname:
        return "PC"
    if "cloud" in hostname or "gcp" in hostname:
        return "GCP"
    return (hostname.split(".", 1)[0][:16] or FALLBACK_OWNER_LABEL).upper()


def owner_label() -> str:
    label = env_value("FARYO_OWNER_LABEL", default="").strip()
    return label or default_owner_label()


def clean_owner_label(label: str | None) -> str | None:
    if not label:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", label.strip())
    return cleaned[:16] or None


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
        if managed_session(config, name):
            source = tmux_session_option(config, name, "@faryo_agent_source")
            session_id = tmux_session_option(config, name, "@faryo_agent_session_id")
            if source == CODEX_PROFILE.source and session_id:
                active[session_id] = name
                continue
            target = target_config(config, name); cwd = get_pane_cwd(target)
            threads = active_agent_threads(target, cwd)
            if not threads:
                continue
            thread_id = str(threads[0].get("id") or "")
            if thread_id: active[thread_id] = name
            superseded.update(str(row.get("id") or "") for row in threads[1:] if row.get("id"))
    return active, superseded

def active_codex_thread_map(config: Config) -> dict[str, str]:
    active, _superseded = active_codex_thread_state(config)
    return active

def tmux_session_option(config: Config, session: str, key: str, value: str | None = None) -> str:
    if value is not None:
        tmux(config, ["set-option", "-q", "-t", session, key, value], timeout=2); return value
    res = tmux(config, ["show-options", "-qv", "-t", session, key], timeout=2); return res.stdout.strip() if res.returncode == 0 else ""

def active_claude_session_map(config: Config) -> dict[str, str]:
    active: dict[str, str] = {}
    for name in tmux_sessions(config):
        if managed_session(config, name) and tmux_session_option(config, name, "@faryo_agent_source") == "claude-code" and agent_in_pane(Config(name, config.token, config.pane_width)):
            if session_id := (tmux_session_option(config, name, "@faryo_agent_session_id") or tmux_session_option(config, name, "@faryo_agent_id")): active[session_id] = name
    return active


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


def codex_rows(where: str, params: tuple[Any, ...], limit: int | None = None) -> list[dict[str, Any]]:
    sql = f"SELECT {THREAD_COLUMNS}, created_at FROM threads WHERE {where} ORDER BY updated_at DESC"
    if limit: sql += " LIMIT ?"; params = (*params, limit)
    return agent_state_rows(sql, params)


def codex_session_index_titles() -> dict[str, str]:
    if not CODEX_SESSION_INDEX.exists(): return {}
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
        return {}
    return titles


def codex_thread_title(thread: dict[str, Any], fallback: str = "Untitled session", index_titles: dict[str, str] | None = None) -> str:
    thread_id = str(thread.get("id") or "").strip()
    titles = index_titles if index_titles is not None else codex_session_index_titles()
    return titles.get(thread_id) or session_title_topic(thread.get("title"), fallback)


def path_under_root(path_value: str | None, root_value: str | None) -> bool:
    try: return bool(path_value and root_value and Path(path_value).expanduser().resolve().is_relative_to(Path(root_value).expanduser().resolve()))
    except OSError: return False


def claude_history_items(history_root: str | None = None) -> list[dict[str, Any]]:
    if not CLAUDE_PROJECTS_ROOT.exists(): return []
    try: paths = sorted((path for path in CLAUDE_PROJECTS_ROOT.glob("**/*.jsonl") if path.is_file()), key=lambda path: path.stat().st_mtime, reverse=True)[:AGENT_SESSION_LIST_LIMIT]
    except OSError: return []
    items = []; git_labels: dict[str, str] = {}
    for path in paths:
        try:
            stat = path.stat(); session_id = path.stem; cwd = ""; title = ""; last_prompt = ""
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try: row = json.loads(line)
                    except json.JSONDecodeError: continue
                    if not isinstance(row, dict): continue
                    session_id = str(row.get("sessionId") or row.get("session_id") or session_id)
                    cwd = str(row.get("cwd") or cwd)
                    message = row.get("message") if isinstance(row.get("message"), dict) else row
                    content = message.get("content") if isinstance(message, dict) else ""
                    if isinstance(content, list): content = " ".join(str(part.get("text", "") if isinstance(part, dict) else part) for part in content)
                    text = " ".join(str(content).split())
                    if row.get("type") == "custom-title": title = str(row.get("customTitle") or title).strip()[:80]
                    elif row.get("type") == "last-prompt": last_prompt = str(row.get("lastPrompt") or last_prompt).strip()[:80]
                    elif not title and (row.get("type") == "user" or message.get("role") == "user"): title = text[:80]
        except OSError:
            continue
        if history_root is not None and not path_under_root(cwd, history_root): continue
        updated_at = _dt.datetime.fromtimestamp(stat.st_mtime, _dt.timezone.utc).astimezone().isoformat(timespec="seconds")
        items.append({"id": session_id, "title": session_title_topic(title or last_prompt, short_path(cwd) or session_id or "Untitled session"), "gitLabel": session_git_label(cwd, git_labels), "cwd": short_path(cwd), "createdAt": "", "updatedAt": updated_at, "updatedTs": stat.st_mtime, "historyPath": path.as_posix(), "rolloutPath": "", "model": "", "reasoningEffort": "", "source": "claude-code", "tmuxSession": "", "active": False})
    return items

def codex_history_items(config: Config, history_root: str | None = None) -> list[dict[str, Any]]:
    active, superseded = active_codex_thread_state(config); index_titles = codex_session_index_titles(); items = []; git_labels: dict[str, str] = {}
    for item in codex_rows("source = 'cli' AND thread_source = 'user' AND COALESCE(archived, 0) = 0", (), AGENT_SESSION_LIST_LIMIT):
        cwd = str(item.get("cwd") or "")
        if history_root is not None and not path_under_root(cwd, history_root): continue
        thread_id = str(item.get("id") or ""); tmux_session = active.get(thread_id, "")
        if thread_id in superseded: continue
        updated_ts = parse_sqlite_timestamp(item.get("updated_at"))
        fallback = short_path(cwd) or thread_id or "Untitled session"
        title = codex_thread_title(item, fallback, index_titles)
        if tmux_session:
            title = tmux_session_option(config, tmux_session, "@faryo_session_title") or title
        items.append({"id": thread_id, "title": title, "gitLabel": session_git_label(cwd, git_labels), "cwd": short_path(cwd), "createdAt": item.get("created_at") or "", "updatedAt": item.get("updated_at") or "", "updatedTs": updated_ts, "rolloutPath": item.get("rollout_path") or "", "model": item.get("model") or "", "reasoningEffort": item.get("reasoning_effort") or "", "source": "codex-cli", "tmuxSession": tmux_session, "active": bool(tmux_session)})
    return items


def agent_session_items(config: Config, history_root: str | None = None) -> list[dict[str, Any]]:
    items = codex_history_items(config, history_root)
    seen_tmux = {item.get("tmuxSession") for item in items if item.get("tmuxSession")}
    active = active_claude_session_map(config)
    for item in claude_history_items(history_root):
        if tmux_session := active.get(str(item.get("id") or "")): item.update({"tmuxSession": tmux_session, "active": True}); seen_tmux.add(tmux_session)
        items.append(item)
    git_labels: dict[str, str] = {}
    for name in tmux_sessions(config):
        if not managed_session(config, name) or name in seen_tmux: continue
        target = target_config(config, name)
        if not agent_in_pane(target): continue
        cwd = get_pane_cwd(target); thread = active_agent_thread(target, cwd) or {}; thread_id = str(thread.get("id") or name)
        updated_ts = session_created_ts(target); updated_at = iso_from_ts(updated_ts) if updated_ts else ""
        title = tmux_session_option(config, name, "@faryo_session_title") or (codex_thread_title(thread, short_path(cwd) or name) if thread else short_path(cwd) or name)
        items.append({"id": thread_id, "title": title, "gitLabel": session_git_label(cwd, git_labels), "cwd": short_path(cwd), "createdAt": "", "updatedAt": updated_at, "updatedTs": updated_ts, "rolloutPath": "", "model": "", "reasoningEffort": "", "source": tmux_session_option(config, name, "@faryo_agent_source") or "runtime", "tmuxSession": name, "active": True})
    return sorted(items, key=lambda item: float(item.get("updatedTs") or 0), reverse=True)


def codex_thread_by_id(thread_id: str) -> dict[str, Any] | None:
    rows = codex_rows("id = ? AND source = 'cli' AND COALESCE(archived, 0) = 0", (thread_id,), 1)
    return rows[0] if rows else None


def agent_launch_executable(command: str) -> str:
    if command == "claude" and CLAUDE_DEEPSEEK_LAUNCHER and CLAUDE_DEEPSEEK_LAUNCHER.is_file():
        return str(CLAUDE_DEEPSEEK_LAUNCHER)
    return shutil.which(command) or command


def start_agent_runtime(config: Config, cwd: Path, command: str, args: list[str], max_running: int = 0, wait_ready: bool = True, agent_id: str = "", title: str = "") -> str:
    with RUNTIME_LOCK:
        if max_running and managed_agent_count(config) >= max_running: raise OwnerError("running agent limit reached", HTTPStatus.CONFLICT)
        name = f"faryo-{_dt.datetime.now():%m%d-%H%M%S}-{secrets.token_hex(2)}"; executable = agent_launch_executable(command)
        shell = shutil.which("zsh") or "/usr/bin/zsh"; launch = f"{shlex.join([executable, *args])}; exec {shlex.quote(shell)} -l"
        res = tmux(config, ["new-session", "-d", "-s", name, "-c", str(cwd), shell, "-lc", launch], timeout=5)
        if res.returncode != 0: raise OwnerError(res.stderr.strip() or "tmux session start failed", HTTPStatus.INTERNAL_SERVER_ERROR)
        if source := AGENT_SOURCE_BY_COMMAND.get(command): tmux_session_option(config, name, "@faryo_agent_source", source)
        if title:
            tmux_session_option(config, name, "@faryo_session_title", clean_session_title(title))
        if agent_id:
            tmux_session_option(config, name, "@faryo_agent_session_id", agent_id)
            if command == "claude": tmux_session_option(config, name, "@faryo_agent_id", agent_id)
    if not wait_ready:
        return name
    target = Config(name, config.token, config.pane_width); deadline = time.monotonic() + 10.0
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

def resume_claude_session(config: Config, session_id: str, max_running: int = 0, history_root: str | None = None) -> str:
    if not (clean_id := clean_agent_session_id(session_id)): raise OwnerError("invalid claude session id")
    with RUNTIME_LOCK:
        if active := active_claude_session_map(config).get(clean_id): return active
        if not (item := next((item for item in claude_history_items(history_root) if item.get("id") == clean_id), None)): raise OwnerError("claude session not found", HTTPStatus.NOT_FOUND)
        cwd = Path(str(item.get("cwd") or Path.home())).expanduser(); cwd = cwd if cwd.is_dir() else Path.home(); return start_agent_runtime(config, cwd, "claude", ["--resume", clean_id], max_running, wait_ready=False, agent_id=clean_id)

def resume_agent_session(config: Config, session_id: str, source: str, max_running: int = 0, history_root: str | None = None) -> str:
    if source == "codex-cli":
        return resume_codex_thread_session(config, session_id, max_running, history_root)
    if source == "claude-code":
        return resume_claude_session(config, session_id, max_running, history_root)
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


def managed_agent_count(config: Config) -> int:
    cleanup_managed_sessions(config)
    return sum(1 for name in tmux_sessions(config) if managed_session(config, name) and agent_in_pane(Config(name, config.token, config.pane_width)))


def bounded_max_running(payload: dict[str, Any]) -> int:
    return int(payload.get("max_running") or payload.get("maxRunning") or 0)


def agent_tail_ignorable(line: str, profile: AgentProfile) -> bool:
    if agent_meta_line(line, profile):
        return True
    if profile is not CLAUDE_PROFILE:
        return False
    return bool(profile.prompt_hint_re.match(line) or SEPARATOR_RE.match(line) or SEPARATOR_OUTPUT_RE.match(line) or LONG_SEPARATOR_RE.search(line))


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
CODEX_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


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


def is_agent_cmd(cmd: str) -> bool:
    return any(agent_profile_matches_cmd(profile, cmd) for profile in AGENT_PROFILES)


def agent_profile_matches_cmd(profile: AgentProfile, cmd: str) -> bool:
    return is_codex_cli_cmd(cmd) if profile is CODEX_PROFILE else is_named_tui_cmd(cmd, profile.process_names)


def is_named_tui_cmd(cmd: str, names: set[str]) -> bool:
    parts = cmd.lower().strip().split()
    if not parts:
        return False
    executable = Path(parts[0]).name
    return executable in names or executable.removesuffix(".exe") in names


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

    cli_rows = [dict(row) for row in rows if row.get("source") == "cli" and row.get("thread_source") == "user"]
    matches = [row for row in cli_rows if cwd is None or row["cwd"] == cwd]
    return sorted(matches or cli_rows, key=lambda row: parse_sqlite_timestamp(row.get("updated_at")), reverse=True)

def active_agent_thread(config: Config, cwd: str | None) -> dict[str, Any] | None:
    threads = active_agent_threads(config, cwd)
    return threads[0] if threads else None


def latest_context_usage(history_path: str | None, model: str | None = None) -> dict[str, int | float] | None:
    if not history_path:
        return None

    path = Path(history_path).expanduser()
    if not path.exists():
        return None

    latest_info: dict[str, Any] | None = None
    latest_usage: dict[str, Any] | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload") if isinstance(event, dict) else None
                if isinstance(payload, dict) and payload.get("type") == "token_count":
                    info = payload.get("info")
                    if isinstance(info, dict):
                        latest_info = info
                message = event.get("message") if isinstance(event, dict) else None
                usage = message.get("usage") if isinstance(message, dict) else None
                if isinstance(usage, dict) and any(usage.get(key) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")):
                    latest_usage = usage
    except OSError:
        return None

    try:
        if latest_info:
            last_usage = latest_info.get("last_token_usage")
            if not isinstance(last_usage, dict): return None
            input_tokens = int(last_usage.get("input_tokens") or 0)
            context_window = int(latest_info.get("model_context_window") or 0)
        elif latest_usage:
            input_tokens = sum(int(latest_usage.get(key) or 0) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            context_window = 1_000_000 if "[1m]" in str(model or "").lower() else 200_000
        else:
            return None
    except (TypeError, ValueError):
        return None
    if input_tokens <= 0 or context_window <= 0:
        return None

    return {
        "inputTokens": input_tokens,
        "contextWindow": context_window,
        "percent": round((input_tokens / context_window) * 100, 1),
    }


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
    try:
        process = subprocess.Popen(
            ["codex", "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None

    try:
        deadline = time.monotonic() + timeout
        initialized = send_app_server_message(
            process,
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "local-tmux-owner", "title": None, "version": "0"},
                    "capabilities": {"experimentalApi": True},
                },
            },
        )
        if not initialized:
            return None

        while time.monotonic() < deadline:
            message = read_app_server_message(process, deadline)
            if message is None:
                break
            if message.get("id") == 1:
                break
        else:
            return None

        if not send_app_server_message(process, {"id": 2, "method": "account/rateLimits/read"}):
            return None

        while time.monotonic() < deadline:
            message = read_app_server_message(process, deadline)
            if message is None:
                break
            if message.get("id") != 2:
                continue
            result = message.get("result")
            return rate_limit_from_response(result) if isinstance(result, dict) else None
    finally:
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

    return None


def cached_weekly_rate_limit() -> dict[str, Any] | None:
    global _rate_limit_cache, _rate_limit_cache_at

    now = time.monotonic()
    with _rate_limit_lock:
        if _rate_limit_cache is not None and now - _rate_limit_cache_at < RATE_LIMIT_CACHE_TTL:
            return _rate_limit_cache

    fresh = fetch_weekly_rate_limit()
    with _rate_limit_lock:
        if fresh is not None:
            _rate_limit_cache = fresh
            _rate_limit_cache_at = time.monotonic()
        return _rate_limit_cache


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
        if prop == "color" and normalized_value in BLACK_VALUES:
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


def paste_tail_probe(text: str) -> str:
    compacted = " ".join(text.split())
    if len(compacted) <= PASTE_READY_MIN_PROBE_CHARS:
        return compacted
    return compacted[-min(80, len(compacted)):]


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


def wait_for_paste_tail(config: Config, text: str, baseline: str) -> None:
    probe = paste_tail_probe(text)
    if not probe:
        return
    deadline = time.monotonic() + PASTE_READY_TIMEOUT
    while time.monotonic() < deadline:
        captured = tmux_capture_compact(config)
        if captured.count(probe) > baseline.count(probe):
            return
        time.sleep(PASTE_READY_POLL_INTERVAL)


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
    claude_item = None
    if profile is CLAUDE_PROFILE:
        claude_id = tmux_session_option(config, config.session, "@faryo_agent_id")
        claude_item = next((item for item in claude_history_items() if item.get("id") == claude_id), None)
        model = model or env_value("ANTHROPIC_MODEL", default="deepseek-v4-pro[1m]")
    context_usage = latest_context_usage(thread.get("rollout_path") if thread else (claude_item.get("historyPath") if claude_item else None), model)
    weekly_rate_limit = None
    if tmux_alive and profile is CODEX_PROFILE:
        try:
            weekly_rate_limit = cached_weekly_rate_limit()
        except Exception:
            weekly_rate_limit = None
    agent_active = profile is not None
    agent_running = bool(agent_active and not agent_ready_for_input(config, capture_profile))
    target_alive = tmux_alive
    session_title = codex_thread_title(thread, str(thread.get("id") or "Untitled session")) if thread else (claude_item.get("title") if claude_item else None)
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
        "gitStatus": git_status(cwd),
        "sessionTitle": session_title,
        "sessionId": (thread.get("id") if thread else None) or (claude_item.get("id") if claude_item else None),
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


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def clean_session_title(value: Any) -> str:
    return compact_text(value)[:48]


def project_slug(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "project"


def project_workbench_enabled() -> bool:
    return env_value("FARYO_PROJECT_WORKBENCH_ENABLE", default="1").strip().lower() not in {"0", "false", "no", "off"}


def clean_project_workbench(project: dict[str, Any]) -> dict[str, Any]:
    project_id = project_slug(project.get("id") or project.get("name"))
    items = []
    for index, item in enumerate(project.get("items") if isinstance(project.get("items"), list) else [], 1):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip()
        title = compact_text(item.get("title"))
        status = str(item.get("status") or "open").strip()
        if item_type not in PROJECT_ITEM_TYPES or not title or status in PROJECT_DONE_STATUSES:
            continue
        items.append({
            "id": compact_text(item.get("id")) or f"item-{index}",
            "type": item_type,
            "title": title,
            "body": compact_text(item.get("body")),
            "recommendation": compact_text(item.get("recommendation")),
            "status": status,
        })
    return {
        "id": project_id,
        "name": compact_text(project.get("name") or project_id),
        "brief": compact_text(project.get("brief")),
        "current_d": compact_text(project.get("current_d")),
        "items": items,
    }


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


def write_project_workbench_file(path: Path, project: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def project_definition_path(project_root: Path) -> Path:
    return project_root / "00-system" / "project.md"


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
        "- Keep `00-system/workbench.json` current during project work.",
        "- Update decision, action, and watch items before closing a managed work session.",
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


def project_workbench_hash(project: dict[str, Any]) -> str:
    body = json.dumps(project, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


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
    ensure_project_definition_file(project_root, project)
    row = dict(project)
    row["path"] = str(path)
    row["workbench_path"] = str(path)
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
            "X-Faryo-Owner-Label": owner_label(),
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
    clean_projects = [clean_project_workbench(project) for project in projects if isinstance(project, dict)]
    expected_hashes = {project_slug(project.get("id") or project.get("name")): compact_text(project.get("hash")) for project in projects if isinstance(project, dict)}
    targets = [(project_workbench_path(raw_project), clean_project_workbench(raw_project)) for raw_project in projects if isinstance(raw_project, dict)]
    written = [write_project_workbench_file(path, project) for path, project in targets]
    hashes = {}
    for path, project in zip(written, clean_projects):
        payload = json.loads(path.read_text(encoding="utf-8"))
        actual = clean_project_workbench(payload if isinstance(payload, dict) else {})
        hashes[project["id"]] = project_workbench_hash(actual)
    mismatched = [project_id for project_id, digest in expected_hashes.items() if digest and hashes.get(project_id) != digest]
    ok = not mismatched
    ack = gateway_json_request(config, gateway_url, "/api/project-workbench/downlink/ack", {
        "package_id": package_id,
        "ok": ok,
        "status": "applied" if ok else "failed",
        "applied": len(written) if ok else 0,
        "hashes": hashes,
        "message": ("hash mismatch: " + ", ".join(mismatched)) if mismatched else "",
    })
    if not ok:
        raise OwnerError("downlink hash mismatch: " + ", ".join(mismatched), HTTPStatus.CONFLICT)
    return {"ok": True, "status": "applied", "package_id": package_id, "applied": len(written), "ack_ok": bool(ack.get("ok")), "updatedAt": now_iso()}


class MultipartFile:
    def __init__(self, filename: str, content_type: str, data: bytes) -> None:
        self.filename = filename
        self.type = content_type
        self.file = io.BytesIO(data)


def send_text(config: Config, text: str) -> None:
    if not has_session(config):
        raise OwnerError(f"tmux session not found: {config.session}", HTTPStatus.NOT_FOUND)
    if not text.strip():
        raise OwnerError("empty text")
    if len(text) > MAX_SEND_CHARS:
        raise OwnerError(f"text too long: {len(text)} > {MAX_SEND_CHARS}", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    line = text.strip()
    words = line.split()
    launch_command = Path(words[0]).name.lower() if words else ""
    shell_prep = bool(words and (launch_command in AGENT_LAUNCH_COMMANDS or SHELL_PREP_RE.fullmatch(line)))
    if shell_prep and not agent_in_pane(config):
        for keys in (["-l", line], ["Enter"]):
            res = tmux(config, ["send-keys", "-t", tmux_target(config), *keys], timeout=3)
            if res.returncode != 0:
                raise OwnerError(res.stderr.strip() or "tmux send shell prep failed", HTTPStatus.INTERNAL_SERVER_ERROR)
        return
    profile = agent_profile_in_pane(config)
    buffer_name = f"local-tmux-owner-{secrets.token_hex(4)}"
    tmp_path: str | None = None
    try:
        baseline = tmux_capture_compact(config)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, prefix="local-tmux-owner-", suffix=".txt") as tmp:
            tmp.write(text)
            tmp_path = tmp.name
        res = tmux(config, ["load-buffer", "-b", buffer_name, tmp_path], timeout=3)
        if res.returncode != 0:
            raise OwnerError(res.stderr.strip() or "tmux load-buffer failed", HTTPStatus.INTERNAL_SERVER_ERROR)
        paste_args = ["paste-buffer", "-d", "-r", "-b", buffer_name, "-t", tmux_target(config)]
        if profile is not CLAUDE_PROFILE:
            paste_args.insert(2, "-p")
        res = tmux(config, paste_args, timeout=3)
        if res.returncode != 0:
            raise OwnerError(res.stderr.strip() or "tmux paste-buffer failed", HTTPStatus.INTERNAL_SERVER_ERROR)
        wait_for_paste_tail(config, text, baseline)
        # Some terminal TUIs treat carriage return more reliably than a plain
        # Enter after tmux paste, especially through mobile/browser paths.
        res = tmux(config, ["send-keys", "-t", tmux_target(config), "C-m"], timeout=3)
        if res.returncode != 0:
            raise OwnerError(res.stderr.strip() or "tmux send Enter failed", HTTPStatus.INTERNAL_SERVER_ERROR)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
        tmux(config, ["delete-buffer", "-b", buffer_name], timeout=1)


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
        sys.stderr.write("[%s] %s\n" % (now_iso(), fmt % args))

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
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
                query = parse_qs(parsed.query); limit = max(1, min(int(query.get("limit", [str(AGENT_SESSION_LIST_LIMIT)])[0]), AGENT_SESSION_LIST_LIMIT))
                self.write_json({"ok": True, "sessions": self.agent_session_items(limit), "activeCount": managed_agent_count(self.config), "updatedAt": now_iso()})
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
                text = capture_text(target, lines, profile)
                want_html = query.get("format", [""])[0] == "html" or query.get("html", [""])[0].lower() in {"1", "true", "yes"}
                payload = {
                    "ok": True,
                    "text": text,
                    "agentSource": profile.source,
                    "agentProfile": profile.key,
                    "updatedAt": now_iso(),
                }
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
            if parsed.path == "/":
                self.path = "/index.html" + (("?" + parsed.query) if parsed.query else "")
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
        deadline = time.monotonic() + EVENT_STREAM_MAX_SECONDS
        try:
            while time.monotonic() < deadline:
                try:
                    profile = agent_profile_in_pane(target); capture_profile = profile or RUNTIME_PROFILE
                    text = capture_text(target, lines, capture_profile)
                    agent_running = bool(profile and not agent_ready_for_input(target, capture_profile))
                    digest = hash(text)
                    if digest != last_hash or agent_running != last_running:
                        last_hash = digest
                        last_running = agent_running
                        payload = {"ok": True, "text": text, "agentRunning": agent_running, "agentSource": capture_profile.source, "agentProfile": capture_profile.key, "updatedAt": now_iso()}
                        if not self.send_event("capture", payload):
                            return
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
                    cwd = Path(raw_cwd).expanduser()
                    if not cwd.is_dir():
                        raise OwnerError("cwd not found", HTTPStatus.BAD_REQUEST)
                else:
                    cwd = Path(workspace_root or get_pane_cwd(self.config) or str(Path.home())).expanduser(); cwd = cwd if cwd.is_dir() else Path.home()
                command = clean_agent_launch_command(str(payload.get("command") or ""))
                if not command:
                    raise OwnerError("invalid launch command")
                title = clean_session_title(payload.get("title"))
                agent_id = str(uuid.uuid4()) if command == "claude" else ""; args = ["--session-id", agent_id] if agent_id else []
                name = start_agent_runtime(self.config, cwd, command, args, bounded_max_running(payload), wait_ready=False, agent_id=agent_id, title=title)
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
                send_text(target, str(payload.get("text", "")))
                self.write_json({"ok": True, "updatedAt": now_iso()})
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

    def agent_session_items(self, limit: int = AGENT_SESSION_LIST_LIMIT) -> list[dict[str, Any]]:
        return agent_session_items(self.config, self.history_root())[:limit]

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
        html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#F7F0E5"><title>{title}</title><style>
body{{margin:0;background:#F7F0E5;color:#3E3026;font:16px/1.58 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-text-size-adjust:100%}}
header{{position:sticky;top:0;z-index:2;display:flex;align-items:center;gap:8px;padding:calc(env(safe-area-inset-top) + 8px) 10px 8px;background:rgba(255,253,248,.96);border-bottom:1px solid #D9C9B8;backdrop-filter:blur(12px)}}
h1{{min-width:0;flex:1;margin:0;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
button,.pill{{min-height:34px;padding:0 10px;border:1px solid #D9C9B8;border-radius:999px;background:#FFFDF8;color:#3E3026;font:600 14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;text-decoration:none}}
main{{padding:14px 14px calc(env(safe-area-inset-bottom) + 22px)}}
pre{{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.58 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
.notice{{padding:12px;border:1px solid #D9C9B8;border-radius:12px;background:#FFFDF8}}
@media (prefers-color-scheme: dark){{body{{background:#17130F;color:#F7F0E5}}header{{background:rgba(33,26,21,.96);border-color:#4B3D32}}button,.pill,.notice{{background:#211A15;color:#F7F0E5;border-color:#4B3D32}}}}
</style></head><body><header><button type="button" onclick="history.length>1?history.back():location.href='/'">Back</button><h1>{title}</h1><a class="pill" href="{raw_url}">Raw</a><a class="pill" href="{download_url}" download>Download</a></header><main>{body}</main></body></html>"""
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
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
