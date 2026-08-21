"""Deterministic projection of Codex thread notifications for the browser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from appserver_protocol import agent_message_text, item_identity


HANDLED_NOTIFICATION_METHODS = frozenset({
    "error",
    "item/agentMessage/delta",
    "item/commandExecution/outputDelta",
    "item/completed",
    "item/fileChange/outputDelta",
    "item/plan/delta",
    "item/reasoning/summaryTextDelta",
    "item/started",
    "thread/goal/cleared",
    "thread/goal/updated",
    "thread/name/updated",
    "thread/started",
    "thread/status/changed",
    "thread/settings/updated",
    "thread/tokenUsage/updated",
    "turn/completed",
    "turn/error",
    "turn/started",
})


def _bounded_text(value: Any, limit: int = 2_000) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _path_label(value: Any) -> str:
    text = str(value or "").replace("\\", "/").rstrip("/")
    return text.rsplit("/", 1)[-1] if text else "file"


def item_process_text(item: Mapping[str, Any], *, final: bool = False) -> str:
    item_type = str(item.get("type") or "")
    status = str(item.get("status") or "")
    completed = final or status.lower() in {"completed", "failed", "declined"}
    if item_type == "plan":
        text = str(item.get("text") or "").strip()
        return f"Updated Plan\n{text}" if text else "Updated Plan"
    if item_type == "reasoning":
        return "Working"
    if item_type == "commandExecution":
        command = _bounded_text(item.get("command")) or "command"
        exit_code = item.get("exitCode", item.get("exit_code"))
        suffix = f" · exit {exit_code}" if completed and isinstance(exit_code, int) else ""
        return f"{'Ran' if completed else 'Running'} {command}{suffix}"
    if item_type == "fileChange":
        changes = item.get("changes") if isinstance(item.get("changes"), list) else []
        paths = [_path_label(change.get("path")) for change in changes if isinstance(change, Mapping)]
        if not paths:
            return "Edited files" if completed else "Editing files"
        prefix = "Edited" if completed else "Editing"
        return "\n".join(f"{prefix} {path}" for path in paths[:8])
    if item_type == "mcpToolCall":
        label = ".".join(
            part for part in (_bounded_text(item.get("server"), 120), _bounded_text(item.get("tool"), 120)) if part
        ) or "MCP tool"
        return f"Called {label}" if completed else f"Calling {label}"
    if item_type == "dynamicToolCall":
        label = ".".join(
            part
            for part in (_bounded_text(item.get("namespace"), 120), _bounded_text(item.get("tool"), 120))
            if part
        ) or "tool"
        return f"Called {label}" if completed else f"Calling {label}"
    if item_type == "webSearch":
        query = _bounded_text(item.get("query"), 240)
        return f"{'Searched' if completed else 'Searching the web'} {query}".rstrip()
    if item_type == "todoList":
        rows = []
        for entry in item.get("items") or []:
            if not isinstance(entry, Mapping):
                continue
            marker = "✓" if entry.get("completed") else "□"
            text = _bounded_text(entry.get("text"), 400)
            if text:
                rows.append(f"{marker} {text}")
        return "Updated Plan" + ("\n" + "\n".join(rows) if rows else "")
    if item_type == "contextCompaction":
        return "Context compacted"
    if item_type == "imageView":
        return f"Viewed Image {_path_label(item.get('path'))}"
    if item_type == "subAgentActivity":
        return "Working with a background agent"
    if item_type == "error":
        return "⚠ " + (_bounded_text(item.get("message"), 800) or "Codex error")
    return ""


def user_message_text(item: Mapping[str, Any]) -> str:
    if item.get("type") != "userMessage":
        return ""
    parts: list[str] = []
    content = item.get("content")
    if not isinstance(content, list):
        return ""
    for value in content:
        if not isinstance(value, Mapping):
            continue
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            parts.append(str(value["text"]))
        elif value.get("type") in {"image", "localImage"}:
            parts.append("[Image attached]")
    return "\n".join(parts)


@dataclass
class ItemProjection:
    id: str
    turn_id: str
    type: str
    text: str = ""
    revision: int = 0
    final: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "turnId": self.turn_id,
            "type": self.type,
            "text": self.text,
            "revision": self.revision,
            "final": self.final,
            "item": self.raw,
        }


@dataclass(frozen=True)
class ActorEvent:
    kind: str
    turn_id: str | None = None
    item_id: str | None = None
    revision: int = 0
    payload: dict[str, Any] = field(default_factory=dict)


class WebSessionActor:
    def __init__(self, *, session_id: str, thread_id: str) -> None:
        if not session_id or not thread_id:
            raise ValueError("session_id and thread_id are required")
        self.session_id = session_id
        self.thread_id = thread_id
        self.lifecycle = "loading"
        self.active_turn_id: str | None = None
        self.turns: dict[str, dict[str, Any]] = {}
        self.item_order: list[str] = []
        self.items: dict[str, ItemProjection] = {}
        self.token_usage: dict[str, Any] = {}
        self.goal: dict[str, Any] | None = None
        self.interaction: dict[str, Any] | None = None
        self.interaction_revision = 0
        self.thread: dict[str, Any] = {"id": thread_id}
        self.revision = 0

    def apply(self, method: str, params: Mapping[str, Any]) -> list[ActorEvent]:
        event_thread_id = params.get("threadId")
        if isinstance(event_thread_id, str) and event_thread_id != self.thread_id:
            return []
        if method == "thread/started":
            thread = params.get("thread")
            if isinstance(thread, Mapping) and thread.get("id") == self.thread_id:
                self.thread = dict(thread)
                self.lifecycle = self._thread_status(thread.get("status"))
                return [self._event("session.snapshot", payload=self.snapshot())]
            return []
        if method == "thread/status/changed":
            self.lifecycle = self._thread_status(params.get("status"))
            return [self._event("session.lifecycle", payload={"lifecycle": self.lifecycle})]
        if method == "thread/name/updated":
            name = params.get("threadName")
            self.thread["name"] = name if isinstance(name, str) else None
            return [self._event("session.title", payload={"title": self.thread.get("name")})]
        if method == "thread/settings/updated":
            settings = params.get("threadSettings")
            if isinstance(settings, Mapping):
                self.thread.update(dict(settings))
                return [self._event("session.settings", payload={"threadSettings": dict(settings)})]
            return []
        if method == "turn/started":
            turn = params.get("turn")
            if not isinstance(turn, Mapping) or not isinstance(turn.get("id"), str):
                return []
            turn_id = str(turn["id"])
            self.turns[turn_id] = dict(turn)
            self.active_turn_id = turn_id
            self.lifecycle = "running"
            return [self._event("turn.started", turn_id=turn_id, payload={"turn": dict(turn)})]
        if method == "item/started":
            return self._item_started(params)
        if method == "item/agentMessage/delta":
            return self._agent_delta(params)
        if method == "item/plan/delta":
            return self._plan_delta(params)
        if method in {"item/commandExecution/outputDelta", "item/fileChange/outputDelta", "item/reasoning/summaryTextDelta"}:
            return []
        if method == "item/completed":
            return self._item_completed(params)
        if method == "turn/completed":
            return self._turn_completed(params)
        if method == "thread/tokenUsage/updated":
            usage = params.get("tokenUsage")
            if isinstance(usage, Mapping):
                self.token_usage = dict(usage)
                return [self._event("session.usage", turn_id=self._turn_id(params), payload={"tokenUsage": self.token_usage})]
            return []
        if method == "thread/goal/updated":
            goal = params.get("goal")
            if isinstance(goal, Mapping):
                self.goal = dict(goal)
                return [self._event("session.goal", turn_id=self._turn_id(params), payload={"goal": self.goal})]
            return []
        if method == "thread/goal/cleared":
            self.goal = None
            return [self._event("session.goal", turn_id=self._turn_id(params), payload={"goal": None})]
        if method in {"error", "turn/error"}:
            return [self._event("session.error", turn_id=self._turn_id(params), payload={"error": dict(params)})]
        return []

    def _item_started(self, params: Mapping[str, Any]) -> list[ActorEvent]:
        identity = item_identity(params)
        item = params.get("item")
        if identity is None or not isinstance(item, Mapping):
            return []
        _thread_id, turn_id, item_id = identity
        projection = self.items.get(item_id)
        if projection is None:
            projection = ItemProjection(
                id=item_id,
                turn_id=turn_id,
                type=str(item.get("type") or "unknown"),
                text=agent_message_text(item) or item_process_text(item),
                raw=dict(item),
            )
            self.items[item_id] = projection
            self.item_order.append(item_id)
        else:
            projection.raw = dict(item)
            projection.text = agent_message_text(item) or item_process_text(item)
        return [self._event("item.started", turn_id=turn_id, item_id=item_id, payload={"item": projection.public()})]

    def _agent_delta(self, params: Mapping[str, Any]) -> list[ActorEvent]:
        identity = item_identity(params)
        delta = params.get("delta")
        if identity is None or not isinstance(delta, str):
            return []
        _thread_id, turn_id, item_id = identity
        projection = self.items.get(item_id)
        if projection is None:
            projection = ItemProjection(id=item_id, turn_id=turn_id, type="agentMessage")
            self.items[item_id] = projection
            self.item_order.append(item_id)
        if projection.final:
            return []
        if projection.text == "Updated Plan":
            projection.text += "\n"
        projection.text += delta
        projection.revision += 1
        return [
            self._event(
                "item.delta",
                turn_id=turn_id,
                item_id=item_id,
                revision=projection.revision,
                payload={"deltaChars": len(delta), "textLength": len(projection.text)},
            )
        ]

    def _plan_delta(self, params: Mapping[str, Any]) -> list[ActorEvent]:
        identity = item_identity(params)
        delta = params.get("delta")
        if identity is None or not isinstance(delta, str):
            return []
        _thread_id, turn_id, item_id = identity
        projection = self.items.get(item_id)
        if projection is None:
            projection = ItemProjection(id=item_id, turn_id=turn_id, type="plan", text="Updated Plan\n")
            self.items[item_id] = projection
            self.item_order.append(item_id)
        if projection.final:
            return []
        projection.text += delta
        projection.revision += 1
        return [
            self._event(
                "item.delta",
                turn_id=turn_id,
                item_id=item_id,
                revision=projection.revision,
                payload={"deltaChars": len(delta), "textLength": len(projection.text)},
            )
        ]

    def _item_completed(self, params: Mapping[str, Any]) -> list[ActorEvent]:
        identity = item_identity(params)
        item = params.get("item")
        if identity is None or not isinstance(item, Mapping):
            return []
        _thread_id, turn_id, item_id = identity
        projection = self.items.get(item_id)
        if projection is None:
            projection = ItemProjection(id=item_id, turn_id=turn_id, type=str(item.get("type") or "unknown"))
            self.items[item_id] = projection
            self.item_order.append(item_id)
        final_text = agent_message_text(item) or item_process_text(item, final=True)
        changed = not projection.final or projection.raw != dict(item) or projection.text != final_text
        projection.type = str(item.get("type") or projection.type)
        projection.raw = dict(item)
        if final_text:
            projection.text = final_text
        projection.final = True
        if changed:
            projection.revision += 1
        return [
            self._event(
                "item.final",
                turn_id=turn_id,
                item_id=item_id,
                revision=projection.revision,
                payload={"item": projection.public()},
            )
        ] if changed else []

    def _turn_completed(self, params: Mapping[str, Any]) -> list[ActorEvent]:
        turn = params.get("turn")
        if not isinstance(turn, Mapping) or not isinstance(turn.get("id"), str):
            return []
        turn_id = str(turn["id"])
        events: list[ActorEvent] = []
        items = turn.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, Mapping):
                    events.extend(self._item_completed({"threadId": self.thread_id, "turnId": turn_id, "item": item}))
        self.turns[turn_id] = dict(turn)
        if self.active_turn_id == turn_id:
            self.active_turn_id = None
        status = str(turn.get("status") or "completed")
        self.lifecycle = "idle" if status == "completed" else status
        events.append(self._event("turn.completed", turn_id=turn_id, payload={"turn": dict(turn), "lifecycle": self.lifecycle}))
        return events

    def snapshot(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "threadId": self.thread_id,
            "lifecycle": self.lifecycle,
            "activeTurnId": self.active_turn_id,
            "thread": self.thread,
            "turns": list(self.turns.values()),
            "items": [self.items[item_id].public() for item_id in self.item_order],
            "tokenUsage": self.token_usage,
            "goal": self.goal,
            "interaction": self.interaction,
            "interactionRevision": f"appserver:{self.interaction_revision}",
            "revision": self.revision,
        }

    def set_interaction(self, interaction: Mapping[str, Any]) -> ActorEvent:
        self.interaction = dict(interaction)
        self.interaction_revision += 1
        response_kind = str(interaction.get("responseKind") or "choice")
        self.lifecycle = "waiting_for_input" if response_kind == "questions" else "waiting_for_approval"
        return self._event(
            "session.interaction",
            turn_id=self.active_turn_id,
            payload={
                "interaction": self.interaction,
                "interactionRevision": f"appserver:{self.interaction_revision}",
                "lifecycle": self.lifecycle,
            },
        )

    def clear_interaction(self, interaction_id: str) -> ActorEvent | None:
        if self.interaction is None or self.interaction.get("id") != interaction_id:
            return None
        self.interaction = None
        self.interaction_revision += 1
        self.lifecycle = "running" if self.active_turn_id else "idle"
        return self._event(
            "session.interaction",
            turn_id=self.active_turn_id,
            payload={
                "interaction": None,
                "interactionRevision": f"appserver:{self.interaction_revision}",
                "lifecycle": self.lifecycle,
            },
        )

    def messages(self) -> list[tuple[str, str]]:
        messages: list[tuple[str, str]] = []
        for item_id in self.item_order:
            projection = self.items[item_id]
            if projection.type == "agentMessage" and projection.text:
                messages.append(("assistant", projection.text))
            elif projection.type == "userMessage":
                text = user_message_text(projection.raw)
                if text:
                    messages.append(("user", text))
            elif projection.text:
                messages.append(("process", projection.text))
        return messages

    def hydrate(self, thread: Mapping[str, Any], turns: list[Mapping[str, Any]] | None = None) -> None:
        if thread.get("id") == self.thread_id:
            self.thread = dict(thread)
            self.lifecycle = self._thread_status(thread.get("status"))
        source_turns = turns if turns is not None else thread.get("turns")
        if not isinstance(source_turns, list):
            return
        for turn in source_turns:
            if not isinstance(turn, Mapping) or not isinstance(turn.get("id"), str):
                continue
            turn_id = str(turn["id"])
            self.turns[turn_id] = dict(turn)
            items = turn.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, Mapping):
                        self._item_completed({"threadId": self.thread_id, "turnId": turn_id, "item": item})
            status = str(turn.get("status") or "")
            if status in {"inProgress", "in_progress", "active"}:
                self.active_turn_id = turn_id
                self.lifecycle = "running"

    def _event(
        self,
        kind: str,
        *,
        turn_id: str | None = None,
        item_id: str | None = None,
        revision: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> ActorEvent:
        self.revision += 1
        return ActorEvent(kind, turn_id, item_id, revision, payload or {})

    @staticmethod
    def _turn_id(params: Mapping[str, Any]) -> str | None:
        value = params.get("turnId")
        return value if isinstance(value, str) else None

    @staticmethod
    def _thread_status(value: Any) -> str:
        if isinstance(value, str):
            return {"notLoaded": "unloaded", "idle": "idle", "systemError": "failed"}.get(value, value)
        if isinstance(value, Mapping):
            return "running" if value.get("type") == "active" or "activeFlags" in value else str(value.get("type") or "loading")
        return "loading"
