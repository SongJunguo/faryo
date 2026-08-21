"""Pure Codex transcript, rollout-message, budget, and cursor policy."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Any


GOAL_STATUSES = {"active", "blocked", "complete", "paused", "usage_limited"}
GOAL_TOOL_CALL_RE = re.compile(r"\btools\.(?:create_goal|get_goal|update_goal)\s*\(")
GOAL_OUTPUT_MAX_CHARS = 256 * 1024
GOAL_OBJECTIVE_MAX_CHARS = 32 * 1024


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


def _goal_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def goal_snapshot(value: Any, *, allow_none: bool = False) -> dict[str, Any] | None:
    """Return privacy-safe goal metadata, never the objective or thread id."""
    if value is None:
        return {"status": "none"} if allow_none else None
    if not isinstance(value, dict):
        return None
    status = str(value.get("status") or "").strip().lower()
    if status not in GOAL_STATUSES:
        return None
    snapshot: dict[str, Any] = {"status": status}
    for source, target in (
        ("tokenBudget", "tokenBudget"),
        ("token_budget", "tokenBudget"),
        ("tokensUsed", "tokensUsed"),
        ("tokens_used", "tokensUsed"),
        ("timeUsedSeconds", "timeUsedSeconds"),
        ("time_used_seconds", "timeUsedSeconds"),
        ("updatedAt", "updatedAt"),
        ("updated_at", "updatedAt"),
    ):
        if target in snapshot:
            continue
        parsed = _goal_nonnegative_int(value.get(source))
        if parsed is not None:
            snapshot[target] = parsed
    return snapshot


def goal_details(value: Any) -> dict[str, Any]:
    """Return authenticated on-demand details without exposing thread identity."""

    snapshot = goal_snapshot(value, allow_none=True)
    if snapshot is None or snapshot.get("status") == "none":
        return {"status": "none", "objective": ""}
    objective = str(value.get("objective") or "") if isinstance(value, dict) else ""
    truncated = len(objective) > GOAL_OBJECTIVE_MAX_CHARS
    snapshot["objective"] = objective[:GOAL_OBJECTIVE_MAX_CHARS]
    snapshot["objectiveTruncated"] = truncated
    for source, target in (("createdAt", "createdAt"), ("created_at", "createdAt")):
        if target in snapshot:
            break
        parsed = _goal_nonnegative_int(value.get(source)) if isinstance(value, dict) else None
        if parsed is not None:
            snapshot[target] = parsed
    return snapshot


def direct_goal_snapshot(event: Any) -> dict[str, Any] | None:
    if not isinstance(event, dict) or event.get("type") != "response_item":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "thread_goal_updated" or "goal" not in payload:
        return None
    return goal_snapshot(payload.get("goal"), allow_none=True)


def goal_tool_call_id(event: Any) -> str | None:
    if not isinstance(event, dict) or event.get("type") != "response_item":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "custom_tool_call" or payload.get("name") != "exec":
        return None
    source = payload.get("input")
    if not isinstance(source, str) or not GOAL_TOOL_CALL_RE.search(source):
        return None
    call_id = str(payload.get("call_id") or payload.get("id") or "").strip()
    return call_id or None


def goal_tool_output(event: Any) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(event, dict) or event.get("type") != "response_item":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "custom_tool_call_output":
        return None
    call_id = str(payload.get("call_id") or "").strip()
    output = payload.get("output")
    if not call_id or not isinstance(output, list):
        return None
    for block in output:
        text = block.get("text") if isinstance(block, dict) else None
        if not isinstance(text, str) or len(text) > GOAL_OUTPUT_MAX_CHARS or not text.lstrip().startswith("{"):
            continue
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(result, dict) or "goal" not in result:
            continue
        snapshot = goal_snapshot(result.get("goal"), allow_none=True)
        if snapshot is not None:
            return call_id, snapshot
    return None


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
