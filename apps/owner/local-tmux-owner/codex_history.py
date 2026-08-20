"""Pure Codex transcript, rollout-message, budget, and cursor policy."""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any


class HistoryCursorError(Exception):
    def __init__(self, message: str, *, expired: bool = False) -> None:
        super().__init__(message)
        self.expired = expired


def user_message_text(item: dict[str, Any]) -> str:
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
    if selected_count <= 0:
        return False
    if used_chars + turn_chars > char_budget:
        return True
    return selected_count >= min_turns and used_lines + turn_lines > line_budget


def thread_transcript(thread: dict[str, Any], max_lines: int, *, page_turns: int, char_budget: int, min_turns: int) -> str:
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
                if text := user_message_text(item):
                    messages.append(f"› {text}")
            elif item_type == "agentMessage":
                if text := str(item.get("text") or "").strip():
                    messages.append(f"• {text}")
            elif item_type == "plan":
                if text := str(item.get("text") or "").strip():
                    messages.append(f"• Updated Plan\n{text}")
        if messages:
            turns.append("\n\n".join(messages))
    return _bounded_turn_text(turns, max_lines, page_turns=page_turns, char_budget=char_budget, min_turns=min_turns)


def rollout_message(event: Any) -> tuple[str, str] | None:
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


def history_preview(text: str, max_chars: int) -> str:
    compact = " ".join(str(text or "").split()) or "Untitled question"
    limit = max(8, int(max_chars))
    return compact if len(compact) <= limit else compact[:limit - 1] + "…"


def history_revision(identity: tuple[int, ...]) -> str:
    value = ":".join(str(part) for part in identity).encode("ascii")
    return hashlib.sha256(value).hexdigest()[:16]


def history_cursor(revision: str, before: int) -> str:
    return f"{revision}.{max(0, int(before)):x}"


def decode_history_cursor(cursor: str, revision: str) -> int:
    match = re.fullmatch(r"([0-9a-f]{16})\.([0-9a-f]+)", str(cursor or "").strip().lower())
    if not match:
        raise HistoryCursorError("invalid conversation history cursor")
    if not secrets.compare_digest(match.group(1), revision):
        raise HistoryCursorError("conversation history cursor expired", expired=True)
    return int(match.group(2), 16)


def bounded_rollout_messages(
    messages: list[tuple[str, str]],
    *,
    page_turns: int,
    line_budget: int,
    char_budget: int,
    min_turns: int,
) -> list[tuple[str, str]]:
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
        if len(selected) >= page_turns:
            break
        turn_lines = sum(text.count("\n") + 1 for _role, text in turn)
        turn_chars = sum(len(text) for _role, text in turn)
        if turn_exceeds_recent_budget(
            len(selected), used_lines, used_chars, turn_lines, turn_chars,
            line_budget=line_budget, char_budget=char_budget, min_turns=min_turns,
        ):
            break
        selected.append(turn)
        used_lines += turn_lines
        used_chars += turn_chars
    return [message for turn in reversed(selected) for message in turn]


def message_transcript(messages: list[tuple[str, str]], max_lines: int, *, page_turns: int, char_budget: int, min_turns: int) -> str:
    turns: list[str] = []
    current: list[str] = []
    for role, text in messages:
        if role == "user" and current:
            turns.append("\n\n".join(current))
            current = []
        current.append(f"› {text}" if role == "user" else f"• {text}")
    if current:
        turns.append("\n\n".join(current))
    return _bounded_turn_text(turns, max_lines, page_turns=page_turns, char_budget=char_budget, min_turns=min_turns)


def _bounded_turn_text(turns: list[str], line_budget: int, *, page_turns: int, char_budget: int, min_turns: int) -> str:
    selected: list[str] = []
    used_lines = 0
    used_chars = 0
    for turn in reversed(turns):
        if len(selected) >= page_turns:
            break
        turn_lines = turn.count("\n") + 1
        turn_chars = len(turn)
        if turn_exceeds_recent_budget(
            len(selected), used_lines, used_chars, turn_lines, turn_chars,
            line_budget=line_budget, char_budget=char_budget, min_turns=min_turns,
        ):
            break
        selected.append(turn)
        used_lines += turn_lines
        used_chars += turn_chars
    return "\n\n".join(reversed(selected)).strip()
