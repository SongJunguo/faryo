"""Framework-neutral Codex session catalog and history metadata projection."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable

from faryo_cli import session_backend


@dataclass(frozen=True)
class CatalogBindings:
    """Narrow composition callbacks required by :class:`SessionCatalog`."""

    state_db: Callable[[], Path]
    session_index: Callable[[], Path]
    thread_columns: str
    interactive_top_level_sql: str
    interactive_sources: frozenset[str]
    history_query_max_chars: int
    history_periods: frozenset[str]
    history_archive_filters: frozenset[str]
    config_factory: Callable[[str, str, int], Any]
    short_path: Callable[[str | None], str | None]
    session_index_title: Callable[[Any], str]
    session_title_topic: Callable[[Any, str], str]
    tmux_session_option: Callable[[Any, str, str, str | None], str]
    session_git_label: Callable[[str | None, dict[str, str], bool], str]
    session_git_cwd: Callable[[Any, str | None, str | None], str | None]
    managed_session: Callable[[Any, str | None], bool]
    agent_profile_in_pane: Callable[[Any], Any]
    agent_session_lifecycle: Callable[[Any, str, Any, bool | None], tuple[str, bool]]
    active_codex_thread_state: Callable[[Any], tuple[dict[str, str], set[str]]]
    active_agent_thread: Callable[[Any, str | None], dict[str, Any] | None]
    tmux_sessions: Callable[[Any], list[str]]
    get_pane_cwd: Callable[[Any], str | None]
    session_created_ts: Callable[[Any], float]
    iso_from_ts: Callable[[float], str]


class SessionCatalog:
    """Read and project Codex session metadata without owning HTTP or tmux."""

    def __init__(self, bindings: CatalogBindings) -> None:
        self.bindings = bindings
        self._index_lock = threading.Lock()
        self._index_cache: dict[str, str] = {}
        self._index_signature: tuple[int, int, int, int] | None = None

    def reset_index_cache(self) -> None:
        with self._index_lock:
            self._index_cache = {}
            self._index_signature = None

    @staticmethod
    def parse_sqlite_timestamp(value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value or "").strip())
        except ValueError:
            pass
        try:
            return dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0

    def agent_state_rows(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        state_db = self.bindings.state_db()
        if not state_db.exists():
            return []
        try:
            connection = sqlite3.connect(f"file:{state_db.as_posix()}?mode=ro", uri=True, timeout=1)
            try:
                connection.row_factory = sqlite3.Row
                return [dict(row) for row in connection.execute(sql, params).fetchall()]
            finally:
                connection.close()
        except sqlite3.Error:
            return []

    def codex_rows(
        self,
        where: str,
        params: tuple[Any, ...],
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        sql = f"SELECT {self.bindings.thread_columns}, created_at FROM threads WHERE {where} ORDER BY updated_at DESC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = (*params, max(0, limit), max(0, offset))
        return self.agent_state_rows(sql, params)

    def codex_count(self, where: str, params: tuple[Any, ...]) -> int:
        rows = self.agent_state_rows(f"SELECT COUNT(*) AS total FROM threads WHERE {where}", params)
        try:
            return max(0, int(rows[0].get("total") or 0)) if rows else 0
        except (TypeError, ValueError):
            return 0

    def codex_session_index_titles(self) -> dict[str, str]:
        """Return explicit thread names without rescanning an unchanged index."""
        session_index = self.bindings.session_index()
        try:
            stat = session_index.stat()
            signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        except OSError:
            self.reset_index_cache()
            return {}
        with self._index_lock:
            if signature == self._index_signature:
                return dict(self._index_cache)
            titles: dict[str, str] = {}
            try:
                with session_index.open(encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(row, dict):
                            continue
                        thread_id = str(row.get("id") or "").strip()
                        title = self.bindings.session_index_title(row.get("thread_name"))
                        if thread_id and title:
                            titles[thread_id] = title
            except OSError:
                return dict(self._index_cache)
            self._index_cache = titles
            self._index_signature = signature
            return dict(titles)

    def codex_thread_title(
        self,
        thread: dict[str, Any],
        fallback: str = "Untitled session",
        index_titles: dict[str, str] | None = None,
    ) -> str:
        thread_id = str(thread.get("id") or "").strip()
        titles = index_titles if index_titles is not None else self.codex_session_index_titles()
        return titles.get(thread_id) or self.bindings.session_title_topic(thread.get("title"), fallback)

    def codex_capture_session_metadata(self, thread_id: str) -> dict[str, str]:
        """Return metadata that may change without changing the transcript."""
        clean_id = str(thread_id or "").strip()
        if not clean_id:
            return {}
        payload = {"sessionId": clean_id}
        if title := self.codex_session_index_titles().get(clean_id):
            payload["sessionTitle"] = title
        return payload

    @staticmethod
    def capture_event_digest(
        text: str,
        live_text: str,
        session_metadata: dict[str, str],
        interaction_revision: str = "",
        queued_send_now: bool = False,
    ) -> int:
        return hash((text, live_text, session_metadata.get("sessionTitle", ""), interaction_revision, queued_send_now))

    @staticmethod
    def path_under_root(path_value: str | None, root_value: str | None) -> bool:
        try:
            return bool(
                path_value
                and root_value
                and Path(path_value).expanduser().resolve().is_relative_to(Path(root_value).expanduser().resolve())
            )
        except OSError:
            return False

    def codex_session_item(
        self,
        config: Any,
        item: dict[str, Any],
        index_titles: dict[str, str],
        git_labels: dict[str, str],
        tmux_session: str = "",
    ) -> dict[str, Any]:
        bindings = self.bindings
        cwd = str(item.get("cwd") or "")
        thread_id = str(item.get("id") or "")
        updated_ts = self.parse_sqlite_timestamp(item.get("updated_at"))
        fallback = bindings.short_path(cwd) or thread_id or "Untitled session"
        startup_title = bindings.tmux_session_option(config, tmux_session, "@faryo_session_title", None) if tmux_session else ""
        title = index_titles.get(thread_id) or startup_title or self.codex_thread_title(item, fallback, index_titles)
        archived = bool(item.get("archived"))
        managed = bool(tmux_session and bindings.managed_session(config, tmux_session))
        state = "archived" if archived else "resumable"
        agent_running = False
        if tmux_session:
            target = bindings.config_factory(tmux_session, config.token, config.pane_width)
            profile = bindings.agent_profile_in_pane(target)
            state, agent_running = bindings.agent_session_lifecycle(config, tmux_session, profile, managed)
        web_managed = item.get("source") == "appServer"
        return {
            "id": thread_id,
            "title": title,
            "gitLabel": bindings.session_git_label(
                bindings.session_git_cwd(config, tmux_session, cwd),
                git_labels,
                bool(tmux_session),
            ),
            "cwd": bindings.short_path(cwd),
            "createdAt": item.get("created_at") or "",
            "updatedAt": item.get("updated_at") or "",
            "updatedTs": updated_ts,
            "rolloutPath": item.get("rollout_path") or "",
            "model": item.get("model") or "",
            "reasoningEffort": item.get("reasoning_effort") or "",
            "source": "codex-app-server" if web_managed else "codex-cli",
            "tmuxSession": tmux_session,
            "active": bool(tmux_session),
            "managed": managed,
            "agentRunning": agent_running,
            "state": state,
            "archived": archived,
            "backend": (
                session_backend.APP_SERVER.value
                if web_managed
                else session_backend.CODEX_TUI.value
            ),
        }

    def clean_agent_history_query(self, value: Any) -> str:
        return " ".join(str(value or "").replace("\x00", "").split())[: self.bindings.history_query_max_chars]

    def clean_agent_history_period(self, value: Any) -> str:
        period = str(value or "all").strip().lower()
        return period if period in self.bindings.history_periods else "all"

    def clean_agent_history_archive(self, value: Any) -> str:
        archive = str(value or "active").strip().lower()
        return archive if archive in self.bindings.history_archive_filters else "active"

    @staticmethod
    def agent_history_period_cutoff(period: str, now: float | None = None) -> float:
        current = float(time.time() if now is None else now)
        if period == "today":
            local = dt.datetime.fromtimestamp(current).astimezone()
            return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        if period == "7d":
            return current - 7 * 24 * 60 * 60
        if period == "30d":
            return current - 30 * 24 * 60 * 60
        return 0.0

    def agent_history_text_matches(self, item: dict[str, Any], query: str, index_titles: dict[str, str]) -> bool:
        needle = self.clean_agent_history_query(query).casefold()
        if not needle:
            return True
        cwd = str(item.get("cwd") or "")
        fallback = self.bindings.short_path(cwd) or str(item.get("id") or "") or "Untitled session"
        title = self.codex_thread_title(item, fallback, index_titles)
        folder = Path(cwd).name if cwd else ""
        return needle in title.casefold() or needle in folder.casefold()

    def interactive_top_level_thread(self, item: dict[str, Any]) -> bool:
        source = item.get("source")
        return (
            isinstance(source, str)
            and source in self.bindings.interactive_sources
            and item.get("thread_source") in {None, "user"}
        )

    def codex_history_filter(
        self,
        history_root: str | None,
        excluded_ids: set[str],
        archive: str = "active",
    ) -> tuple[str, tuple[Any, ...]]:
        where = self.bindings.interactive_top_level_sql
        params: tuple[Any, ...] = ()
        archive = self.clean_agent_history_archive(archive)
        if archive == "active":
            where += " AND COALESCE(archived, 0) = 0"
        elif archive == "archived":
            where += " AND COALESCE(archived, 0) != 0"
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

    def codex_history_page(
        self,
        config: Any,
        limit: int,
        offset: int = 0,
        history_root: str | None = None,
        excluded_ids: set[str] | None = None,
        query: str = "",
        period: str = "all",
        archive: str = "active",
        now: float | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        query = self.clean_agent_history_query(query)
        period = self.clean_agent_history_period(period)
        archive = self.clean_agent_history_archive(archive)
        where, params = self.codex_history_filter(history_root, excluded_ids or set(), archive)
        index_titles = self.codex_session_index_titles()
        git_labels: dict[str, str] = {}
        if not query and period == "all":
            total = self.codex_count(where, params)
            rows = self.codex_rows(where, params, max(1, limit), max(0, offset))
            return [self.codex_session_item(config, item, index_titles, git_labels) for item in rows], total
        cutoff = self.agent_history_period_cutoff(period, now)
        rows = [
            item
            for item in self.codex_rows(where, params)
            if (not cutoff or self.parse_sqlite_timestamp(item.get("updated_at")) >= cutoff)
            and self.agent_history_text_matches(item, query, index_titles)
        ]
        total = len(rows)
        rows = rows[max(0, offset) : max(0, offset) + max(1, limit)]
        return [self.codex_session_item(config, item, index_titles, git_labels) for item in rows], total

    def codex_history_items(self, config: Any, history_root: str | None = None) -> list[dict[str, Any]]:
        active, superseded = self.bindings.active_codex_thread_state(config)
        index_titles = self.codex_session_index_titles()
        items = []
        git_labels: dict[str, str] = {}
        where = f"{self.bindings.interactive_top_level_sql} AND COALESCE(archived, 0) = 0"
        for item in self.codex_rows(where, ()):
            cwd = str(item.get("cwd") or "")
            if history_root is not None and not self.path_under_root(cwd, history_root):
                continue
            thread_id = str(item.get("id") or "")
            tmux_session = active.get(thread_id, "")
            if thread_id in superseded:
                continue
            items.append(self.codex_session_item(config, item, index_titles, git_labels, tmux_session))
        return items

    def active_agent_session_items(
        self,
        config: Any,
        history_root: str | None = None,
        codex_state: tuple[dict[str, str], set[str]] | None = None,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        bindings = self.bindings
        active_codex, superseded = codex_state or bindings.active_codex_thread_state(config)
        index_titles = self.codex_session_index_titles()
        git_labels: dict[str, str] = {}
        items: list[dict[str, Any]] = []
        represented_ids: set[str] = set(active_codex) | superseded
        rows_by_id: dict[str, dict[str, Any]] = {}
        if active_codex:
            placeholders = ",".join("?" for _ in active_codex)
            rows_by_id = {
                str(row.get("id") or ""): row
                for row in self.codex_rows(f"id IN ({placeholders})", tuple(active_codex))
            }
        seen_tmux: set[str] = set()
        for thread_id, tmux_session in active_codex.items():
            item = rows_by_id.get(thread_id)
            if not item:
                continue
            cwd = str(item.get("cwd") or "")
            if history_root is not None and not self.path_under_root(cwd, history_root):
                continue
            items.append(self.codex_session_item(config, item, index_titles, git_labels, tmux_session))
            seen_tmux.add(tmux_session)
        for name in bindings.tmux_sessions(config):
            if name in seen_tmux:
                continue
            target = bindings.config_factory(name, config.token, config.pane_width)
            profile = bindings.agent_profile_in_pane(target)
            managed = bindings.managed_session(config, name)
            if not profile and not managed:
                continue
            cwd = bindings.get_pane_cwd(target)
            if history_root is not None and not self.path_under_root(cwd, history_root):
                continue
            thread = bindings.active_agent_thread(target, cwd) if profile else None
            thread_id = str(
                (thread or {}).get("id")
                or bindings.tmux_session_option(config, name, "@faryo_agent_session_id", None)
                or name
            )
            state, agent_running = bindings.agent_session_lifecycle(config, name, profile, managed)
            updated_ts = bindings.session_created_ts(target)
            updated_at = bindings.iso_from_ts(updated_ts) if updated_ts else ""
            title = (
                index_titles.get(thread_id)
                or bindings.tmux_session_option(config, name, "@faryo_session_title", None)
                or (
                    self.codex_thread_title(thread, bindings.short_path(cwd) or name, index_titles)
                    if thread
                    else bindings.short_path(cwd) or name
                )
            )
            source = profile.source if profile else bindings.tmux_session_option(config, name, "@faryo_agent_source", None) or "codex-cli"
            items.append(
                {
                    "id": thread_id,
                    "title": title,
                    "gitLabel": bindings.session_git_label(bindings.session_git_cwd(config, name, cwd), git_labels, True),
                    "cwd": bindings.short_path(cwd),
                    "createdAt": "",
                    "updatedAt": updated_at,
                    "updatedTs": updated_ts,
                    "rolloutPath": (thread or {}).get("rollout_path") or "",
                    "model": (thread or {}).get("model") or "",
                    "reasoningEffort": (thread or {}).get("reasoning_effort") or "",
                    "source": source,
                    "tmuxSession": name,
                    "active": True,
                    "managed": managed,
                    "agentRunning": agent_running,
                    "state": state,
                    "archived": False,
                }
            )
            if thread_id != name:
                represented_ids.add(thread_id)
            seen_tmux.add(name)
        return sorted(items, key=lambda item: float(item.get("updatedTs") or 0), reverse=True), represented_ids

    def agent_session_page(
        self,
        config: Any,
        limit: int,
        offset: int = 0,
        history_root: str | None = None,
        query: str = "",
        period: str = "all",
        archive: str = "active",
    ) -> dict[str, Any]:
        page_limit = max(1, limit)
        start = max(0, offset)
        codex_state = self.bindings.active_codex_thread_state(config)
        active, excluded_ids = self.active_agent_session_items(config, history_root, codex_state)
        sessions, history_total = self.codex_history_page(
            config,
            page_limit,
            start,
            history_root,
            excluded_ids,
            query,
            period,
            archive,
        )
        return {
            "activeSessions": active,
            "sessions": sessions,
            "historyTotal": history_total,
            "historyOffset": start,
            "historyLimit": page_limit,
            "historyFilter": {
                "q": self.clean_agent_history_query(query),
                "period": self.clean_agent_history_period(period),
                "archive": self.clean_agent_history_archive(archive),
            },
        }

    def agent_session_items(self, config: Any, history_root: str | None = None) -> list[dict[str, Any]]:
        bindings = self.bindings
        items = self.codex_history_items(config, history_root)
        seen_tmux = {item.get("tmuxSession") for item in items if item.get("tmuxSession")}
        git_labels: dict[str, str] = {}
        index_titles = self.codex_session_index_titles()
        for name in bindings.tmux_sessions(config):
            if name in seen_tmux:
                continue
            target = bindings.config_factory(name, config.token, config.pane_width)
            profile = bindings.agent_profile_in_pane(target)
            managed = bindings.managed_session(config, name)
            if not profile and not managed:
                continue
            cwd = bindings.get_pane_cwd(target)
            if history_root is not None and not self.path_under_root(cwd, history_root):
                continue
            thread = (bindings.active_agent_thread(target, cwd) or {}) if profile else {}
            thread_id = str(
                thread.get("id")
                or bindings.tmux_session_option(config, name, "@faryo_agent_session_id", None)
                or name
            )
            state, agent_running = bindings.agent_session_lifecycle(config, name, profile, managed)
            updated_ts = bindings.session_created_ts(target)
            updated_at = bindings.iso_from_ts(updated_ts) if updated_ts else ""
            title = (
                index_titles.get(thread_id)
                or bindings.tmux_session_option(config, name, "@faryo_session_title", None)
                or (
                    self.codex_thread_title(thread, bindings.short_path(cwd) or name, index_titles)
                    if thread
                    else bindings.short_path(cwd) or name
                )
            )
            source = profile.source if profile else bindings.tmux_session_option(config, name, "@faryo_agent_source", None) or "codex-cli"
            items.append(
                {
                    "id": thread_id,
                    "title": title,
                    "gitLabel": bindings.session_git_label(bindings.session_git_cwd(config, name, cwd), git_labels, True),
                    "cwd": bindings.short_path(cwd),
                    "createdAt": "",
                    "updatedAt": updated_at,
                    "updatedTs": updated_ts,
                    "rolloutPath": "",
                    "model": "",
                    "reasoningEffort": "",
                    "source": source,
                    "tmuxSession": name,
                    "active": True,
                    "managed": managed,
                    "agentRunning": agent_running,
                    "state": state,
                    "archived": False,
                }
            )
        return sorted(items, key=lambda item: float(item.get("updatedTs") or 0), reverse=True)

    def codex_thread_record(self, thread_id: str) -> dict[str, Any] | None:
        rows = self.codex_rows(
            f"id = ? AND {self.bindings.interactive_top_level_sql}",
            (thread_id,),
            1,
        )
        return rows[0] if rows else None

    @staticmethod
    def thread_record_archived(thread: dict[str, Any] | None) -> bool:
        try:
            return bool(int((thread or {}).get("archived") or 0))
        except (TypeError, ValueError):
            return False

    def codex_thread_by_id(self, thread_id: str) -> dict[str, Any] | None:
        thread = self.codex_thread_record(thread_id)
        return thread if thread and not self.thread_record_archived(thread) else None

    @staticmethod
    def codex_thread_lifecycle_error_status(message: str) -> HTTPStatus:
        value = str(message or "").lower()
        if "no rollout found" in value or "no archived rollout found" in value:
            return HTTPStatus.NOT_FOUND
        if any(marker in value for marker in ("active", "loaded", "owned", "in use", "descendant")):
            return HTTPStatus.CONFLICT
        return HTTPStatus.BAD_GATEWAY
