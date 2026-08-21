"""Bounded browser-event journal with epoch/sequence replay semantics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
from typing import Any, Iterable
from uuid import uuid4


@dataclass(frozen=True)
class EventCursor:
    epoch: str
    sequence: int

    @classmethod
    def parse(cls, value: str | None) -> "EventCursor | None":
        if not value or ":" not in value:
            return None
        epoch, raw_sequence = value.rsplit(":", 1)
        try:
            sequence = int(raw_sequence)
        except ValueError:
            return None
        if not epoch or sequence < 0:
            return None
        return cls(epoch, sequence)

    def render(self) -> str:
        return f"{self.epoch}:{self.sequence}"


@dataclass(frozen=True)
class JournalEvent:
    cursor: EventCursor
    session_id: str
    thread_id: str
    turn_id: str | None
    item_id: str | None
    kind: str
    revision: int
    payload: dict[str, Any]
    encoded_bytes: int

    @property
    def id(self) -> str:
        return self.cursor.render()

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "epoch": self.cursor.epoch,
            "sequence": self.cursor.sequence,
            "sessionId": self.session_id,
            "threadId": self.thread_id,
            "turnId": self.turn_id,
            "itemId": self.item_id,
            "kind": self.kind,
            "revision": self.revision,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class ReplayResult:
    status: str
    events: tuple[JournalEvent, ...]
    latest: EventCursor


class EventJournal:
    def __init__(self, *, max_events: int = 2048, max_bytes: int = 4 * 1024 * 1024, epoch: str | None = None) -> None:
        if max_events < 1 or max_bytes < 1:
            raise ValueError("event journal limits must be positive")
        self.max_events = max_events
        self.max_bytes = max_bytes
        self.epoch = epoch or uuid4().hex
        self.sequence = 0
        self.total_bytes = 0
        self.events: deque[JournalEvent] = deque()

    @property
    def latest(self) -> EventCursor:
        return EventCursor(self.epoch, self.sequence)

    def publish(
        self,
        *,
        session_id: str,
        thread_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        turn_id: str | None = None,
        item_id: str | None = None,
        revision: int = 0,
        replayable: bool = True,
    ) -> JournalEvent:
        self.sequence += 1
        body = payload or {}
        provisional = {
            "epoch": self.epoch,
            "sequence": self.sequence,
            "sessionId": session_id,
            "threadId": thread_id,
            "turnId": turn_id,
            "itemId": item_id,
            "kind": kind,
            "revision": revision,
            "payload": body,
        }
        size = len(json.dumps(provisional, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        event = JournalEvent(
            cursor=EventCursor(self.epoch, self.sequence),
            session_id=session_id,
            thread_id=thread_id,
            turn_id=turn_id,
            item_id=item_id,
            kind=kind,
            revision=revision,
            payload=body,
            encoded_bytes=size,
        )
        if replayable and size <= self.max_bytes:
            self.events.append(event)
            self.total_bytes += size
            self._trim()
        return event

    def _trim(self) -> None:
        while self.events and (len(self.events) > self.max_events or self.total_bytes > self.max_bytes):
            removed = self.events.popleft()
            self.total_bytes -= removed.encoded_bytes

    def replay(self, raw_cursor: str | None) -> ReplayResult:
        cursor = EventCursor.parse(raw_cursor)
        latest = self.latest
        if cursor is None:
            return ReplayResult("snapshot", (), latest)
        if cursor.epoch != self.epoch or cursor.sequence > self.sequence:
            return ReplayResult("reset", (), latest)
        if cursor.sequence == self.sequence:
            return ReplayResult("replay", (), latest)
        if not self.events or cursor.sequence < self.events[0].cursor.sequence - 1:
            return ReplayResult("gap", (), latest)
        return ReplayResult(
            "replay",
            tuple(event for event in self.events if event.cursor.sequence > cursor.sequence),
            latest,
        )

    def __iter__(self) -> Iterable[JournalEvent]:
        return iter(tuple(self.events))

