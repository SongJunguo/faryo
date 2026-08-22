"""Privacy-safe paged history projected from a live App Server snapshot."""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Mapping

from appserver_session import browser_turn_key, message_block
import codex_history


PUBLIC_BLOCK_KINDS = {"user", "output", "process", "plan"}


def _public_block(value: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = str(value.get("kind") or "")
    item_id = str(value.get("id") or "")
    turn_key = str(value.get("turnKey") or "")
    text = str(value.get("text") or "").strip()
    if kind not in PUBLIC_BLOCK_KINDS or not item_id or not turn_key or not text:
        return None
    try:
        revision = max(0, int(value.get("revision") or 0))
    except (TypeError, ValueError):
        revision = 0
    role = str(value.get("role") or "")
    if role not in {"user", "assistant", "process"}:
        role = "user" if kind == "user" else "assistant" if kind == "output" else "process"
    block: dict[str, Any] = {
        "id": item_id,
        "turnKey": turn_key,
        "kind": kind,
        "role": role,
        "text": text,
        "revision": revision,
        "final": value.get("final") is not False,
    }
    if kind == "user":
        block["questionKey"] = turn_key
    return block


def _project_message_blocks(
    values: list[Mapping[str, Any]],
    preview_chars: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for value in values:
        block = _public_block(value)
        if block is None:
            continue
        turn_key = str(block["turnKey"])
        if turn_key not in grouped:
            grouped[turn_key] = []
            order.append(turn_key)
        grouped[turn_key].append(block)
    projected: list[dict[str, Any]] = []
    for turn_key in order:
        blocks = grouped[turn_key]
        text = _turn_text(blocks)
        question = next(
            (str(block["text"]) for block in blocks if block["kind"] == "user"),
            "",
        )
        if text:
            projected.append({
                "id": turn_key,
                "key": turn_key,
                "preview": codex_history.history_preview(question, preview_chars),
                "text": text,
                "blocks": blocks,
            })
    return projected


def _turn_blocks(turn: Mapping[str, Any]) -> list[dict[str, Any]]:
    turn_id = str(turn.get("id") or "")
    blocks: list[dict[str, Any]] = []
    for item in turn.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        block = message_block(
            item,
            item_id=str(item.get("id") or ""),
            turn_id=turn_id,
            final=True,
        )
        if block is not None:
            blocks.append(block)
    return blocks


def _turn_text(blocks: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"{'›' if block['kind'] == 'user' else '•'} {block['text']}"
        for block in blocks
    )


def _question_text(turn: Mapping[str, Any]) -> str:
    for item in turn.get("items") or []:
        if isinstance(item, dict) and item.get("type") == "userMessage":
            return codex_history.user_message_text(item)
    return ""


def _revision(thread_id: str, turns: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256(thread_id.encode("utf-8"))
    for turn in turns:
        digest.update(b"\0")
        digest.update(str(turn["id"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(turn["text"]).encode("utf-8"))
    return digest.hexdigest()[:16]


def conversation_history_page(
    snapshot: Mapping[str, Any],
    *,
    thread_id: str,
    message_blocks: list[Mapping[str, Any]] | None = None,
    limit: int,
    cursor: str = "",
    around: int | None = None,
    max_page_turns: int,
    page_char_budget: int,
    preview_chars: int,
    updated_at: Callable[[], str],
) -> dict[str, Any]:
    structured_values = [item for item in (message_blocks or []) if isinstance(item, Mapping)]
    projected = _project_message_blocks(structured_values, preview_chars)
    if not projected:
        for raw_turn in snapshot.get("turns") or []:
            if not isinstance(raw_turn, Mapping):
                continue
            turn_id = str(raw_turn.get("id") or "")
            blocks = _turn_blocks(raw_turn)
            text = _turn_text(blocks)
            if not turn_id or not text:
                continue
            question = _question_text(raw_turn)
            projected.append({
                "id": turn_id,
                "key": browser_turn_key(turn_id),
                "preview": codex_history.history_preview(question, preview_chars),
                "text": text,
                "blocks": blocks,
            })

    revision = _revision(thread_id, projected)
    total = len(projected)
    page_limit = max(1, min(int(limit), max_page_turns))
    if cursor and around is not None:
        raise codex_history.HistoryCursorError("choose either a history cursor or an around index")
    if around is not None:
        if around < 0 or around >= total:
            raise codex_history.HistoryCursorError("conversation history index out of range")
        start = max(0, around - page_limit // 2)
        end = min(total, start + page_limit)
        start = max(0, end - page_limit)
    else:
        end = codex_history.decode_history_cursor(cursor, revision) if cursor else total
        end = max(0, min(total, end))
        start = max(0, end - page_limit)

    selected = [dict(turn, index=index) for index, turn in enumerate(projected[start:end], start=start)]
    target_index = around if around is not None else max(start, end - 1)
    while len(selected) > 1 and sum(len(item["text"]) for item in selected) > page_char_budget:
        if around is None:
            selected.pop(0)
        elif abs(selected[0]["index"] - target_index) >= abs(selected[-1]["index"] - target_index):
            selected.pop(0)
        else:
            selected.pop()
    if selected:
        start = int(selected[0]["index"])
        end = int(selected[-1]["index"]) + 1

    turns = [
        {
            "index": int(item["index"]),
            "key": str(item["key"]),
            "preview": str(item["preview"]),
            "text": str(item["text"]),
            "blocks": list(item["blocks"]),
        }
        for item in selected
    ]
    return {
        "ok": True,
        "source": "codex-app-server",
        "revision": revision,
        "totalTurns": total,
        "start": start,
        "end": end,
        "hasOlder": start > 0,
        "hasNewer": end < total,
        "olderCursor": codex_history.history_cursor(revision, start) if start > 0 else "",
        "newerCursor": codex_history.history_cursor(revision, min(total, end + page_limit)) if end < total else "",
        "questions": [
            {"index": index, "key": str(turn["key"]), "preview": str(turn["preview"])}
            for index, turn in enumerate(projected)
        ],
        "turns": turns,
        "pageChars": sum(len(item["text"]) for item in turns),
        "oversized": any(len(item["text"]) > page_char_budget for item in turns),
        "updatedAt": updated_at(),
    }
