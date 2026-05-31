"""Faryo project workbench event-state helpers."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any

SHARED_DIR = Path(__file__).resolve().parents[2] / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
import pd_state

ITEM_TYPES = {"decision", "action", "watch"}
DONE_STATUSES = {"accepted", "done", "skipped", "seen", "rejected", "completed", "closed"}
ITEM_STAGES = {"awaiting_owner", "approved_for_workorder", "workorder_created", "in_progress", "receipt_submitted", "needs_fix", "paused"}
TERMINAL_STAGES = {"closed", "rejected"}


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def project_slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-") or "project"


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def item_stage(item: dict[str, Any]) -> str:
    stage = compact_text(item.get("stage"))
    if stage in ITEM_STAGES:
        return stage
    status = compact_text(item.get("status")).lower()
    return {"in_progress": "in_progress", "review": "receipt_submitted", "paused": "paused"}.get(status, "awaiting_owner")


def item_status(stage: str) -> str:
    return {
        "awaiting_owner": "pending",
        "approved_for_workorder": "open",
        "workorder_created": "open",
        "in_progress": "in_progress",
        "receipt_submitted": "review",
        "needs_fix": "open",
        "paused": "paused",
    }.get(stage, "open")


def clean_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    item_type = compact_text(item.get("type"))
    title = compact_text(item.get("title"))
    stage = item_stage(item)
    status = item_status(stage)
    if item_type not in ITEM_TYPES or not title or stage in TERMINAL_STAGES or status in DONE_STATUSES:
        return {}
    clean = {
        "id": compact_text(item.get("id")) or f"item-{index}",
        "type": item_type,
        "title": title,
        "body": compact_text(item.get("body")),
        "recommendation": compact_text(item.get("recommendation")),
        "status": status,
        "stage": stage,
    }
    for key in ("workorder_id", "updated_at"):
        value = compact_text(item.get(key))
        if value:
            clean[key] = value
    prompt = pd_state.clean_item_decision_prompt(item.get("decision_prompt"), item_type)
    if prompt:
        clean["decision_prompt"] = prompt
    decision = pd_state.clean_owner_decision(item.get("owner_decision"))
    if decision:
        clean["owner_decision"] = decision
    return clean


def clean_project(project: dict[str, Any]) -> dict[str, Any]:
    items = []
    for index, item in enumerate(project.get("items") if isinstance(project.get("items"), list) else [], 1):
        if isinstance(item, dict):
            clean = clean_item(item, index)
            if clean:
                items.append(clean)
    project_id = project_slug(project.get("id") or project.get("name"))
    return {
        "id": project_id,
        "name": compact_text(project.get("name") or project_id),
        "brief": compact_text(project.get("brief")),
        "current_d": compact_text(project.get("current_d")),
        "items": items,
    }


def project_text(project: dict[str, Any]) -> str:
    return json.dumps(project, ensure_ascii=False, indent=2) + "\n"


def project_hash(project: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(project, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def event_id() -> str:
    return f"evt-{_dt.datetime.now(_dt.timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(4)}"


def clean_workorder_id(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-")[:80]


def transition_item_ids(payload: dict[str, Any]) -> list[str]:
    values = payload.get("item_ids") or payload.get("itemIds") or payload.get("items") or payload.get("item_id") or payload.get("itemId")
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    ids: list[str] = []
    for value in values:
        item_id = compact_text(value.get("id") if isinstance(value, dict) else value)
        if item_id and item_id not in ids:
            ids.append(item_id)
    return ids


def next_stage(event_type: str, stage: str) -> str:
    allowed = {
        "owner_approved": {"awaiting_owner": "approved_for_workorder"},
        "owner_rejected": {"awaiting_owner": "closed"},
        "owner_seen": {"awaiting_owner": "approved_for_workorder", "paused": "approved_for_workorder"},
        "owner_paused": {"awaiting_owner": "paused", "approved_for_workorder": "paused", "workorder_created": "paused", "in_progress": "paused", "needs_fix": "paused"},
        "workorder_created": {"approved_for_workorder": "workorder_created"},
        "workorder_dispatch_failed": {"workorder_created": "approved_for_workorder"},
        "worker_started": {"workorder_created": "in_progress"},
        "worker_receipt_submitted": {"in_progress": "receipt_submitted", "needs_fix": "receipt_submitted"},
        "controller_verify_pass": {"receipt_submitted": "closed"},
        "controller_verify_fail": {"receipt_submitted": "needs_fix", "in_progress": "needs_fix"},
    }.get(event_type, {})
    if stage not in allowed:
        raise ValueError(f"invalid transition: {stage} -> {event_type}")
    return allowed[stage]


def base_event(project: dict[str, Any], event_type: str, payload: dict[str, Any], item_id: str = "", prev_stage: str = "", next_stage_value: str = "") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event_id": event_id(),
        "ts": now_iso(),
        "project_id": project["id"],
        "item_id": item_id,
        "event_type": event_type,
        "actor": compact_text(payload.get("actor")) or "faryo",
        "source": compact_text(payload.get("source")) or "owner-api",
        "prev_stage": prev_stage,
        "next_stage": next_stage_value,
        "workorder_id": clean_workorder_id(payload.get("workorder_id") or payload.get("workorderId")),
        "summary": compact_text(payload.get("summary")),
        "payload": {},
    }


def history_record(project: dict[str, Any], item: dict[str, str], event: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    final_status = compact_text(payload.get("final_status") or payload.get("finalStatus")) or {"owner_rejected": "rejected", "controller_verify_pass": "completed"}.get(str(event["event_type"]), "closed")
    summary = compact_text(payload.get("summary")) or compact_text(event.get("summary")) or item["title"]
    return {
        "ts": event["ts"],
        "project_id": project["id"],
        "item_id": item["id"],
        "type": item["type"],
        "title": item["title"],
        "final_status": final_status,
        "summary": summary,
        "evidence": compact_text(payload.get("evidence")) or compact_text(payload.get("verification")) or summary or "state transition",
        "actor": compact_text(event.get("actor")) or "faryo",
        "workorder_id": compact_text(event.get("workorder_id")),
        "closing_event_id": event["event_id"],
    }


def apply_transition(project: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    project = clean_project(project)
    event_type = compact_text(payload.get("event_type") or payload.get("eventType"))
    if not event_type:
        raise ValueError("missing event_type")
    item_ids = transition_item_ids(payload)
    events: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    items_by_id = {item["id"]: item for item in project["items"]}

    if event_type == "item_created":
        raw = payload.get("item") if isinstance(payload.get("item"), dict) else payload
        item = clean_item({**raw, "stage": "awaiting_owner", "status": "pending", "updated_at": now_iso()}, len(project["items"]) + 1)
        if not item:
            raise ValueError("invalid item")
        if item["id"] in items_by_id:
            raise ValueError("item already exists")
        project["items"].append(item)
        event = base_event(project, event_type, payload, item["id"], "", "awaiting_owner")
        event["summary"] = event["summary"] or item["title"]
        events.append(event)
        return project, events, history, item_ids

    if event_type == "project_updated":
        changes = {key: compact_text(payload.get(key)) for key in ("name", "brief", "current_d") if key in payload}
        if not changes:
            raise ValueError("missing project update fields")
        project.update(changes)
        event = base_event(project, event_type, payload)
        event["summary"] = event["summary"] or "Project current state updated."
        event["payload"] = {"changes": changes}
        events.append(event)
        return project, events, history, item_ids

    if not item_ids:
        raise ValueError("missing item_id")
    missing = [item_id for item_id in item_ids if item_id not in items_by_id]
    if missing:
        raise LookupError("item not found: " + ", ".join(missing))

    if event_type in {"item_updated", "item_escalated"}:
        raw = payload.get("item") if isinstance(payload.get("item"), dict) else payload
        for item in project["items"]:
            if item["id"] not in item_ids:
                continue
            if event_type == "item_escalated":
                prev = item_stage(item)
                item.update({"type": "decision", "stage": "awaiting_owner", "status": "pending", "updated_at": now_iso()})
                events.append(base_event(project, event_type, payload, item["id"], prev, "awaiting_owner"))
                continue
            changes = {}
            for key in ("title", "body", "recommendation", "type", "decision_prompt", "owner_decision"):
                if key in raw:
                    if key in {"decision_prompt", "owner_decision"}:
                        value = pd_state.clean_item_decision_prompt(raw.get(key), item.get("type")) if key == "decision_prompt" else pd_state.clean_owner_decision(raw.get(key))
                        if value:
                            item[key] = value
                            changes[key] = value
                        continue
                    text = compact_text(raw.get(key))
                    if key == "type" and text not in ITEM_TYPES:
                        raise ValueError("invalid item type")
                    if key == "title" and not text:
                        raise ValueError("item title is required")
                    item[key] = text
                    changes[key] = text
            if not changes:
                raise ValueError("missing item update fields")
            item["updated_at"] = now_iso()
            event = base_event(project, event_type, payload, item["id"], item_stage(item), item_stage(item))
            event["summary"] = event["summary"] or "Item text updated."
            event["payload"] = {"changes": changes}
            events.append(event)
        project["items"] = [clean for index, item in enumerate(project["items"], 1) if (clean := clean_item(item, index))]
        return project, events, history, item_ids

    remaining = []
    for item in project["items"]:
        if item["id"] not in item_ids:
            remaining.append(item)
            continue
        prev = item_stage(item)
        nxt = next_stage(event_type, prev)
        event = base_event(project, event_type, payload, item["id"], prev, nxt)
        event["workorder_id"] = event["workorder_id"] or compact_text(item.get("workorder_id"))
        owner_decision = pd_state.clean_owner_decision(payload.get("owner_decision"))
        if owner_decision:
            item["owner_decision"] = owner_decision
            event["payload"]["owner_decision"] = owner_decision
        events.append(event)
        if nxt == "closed":
            history.append(history_record(project, item, event, payload))
            continue
        item = dict(item)
        item.update({"stage": nxt, "status": item_status(nxt), "updated_at": now_iso()})
        if event_type == "workorder_dispatch_failed":
            item.pop("workorder_id", None)
        elif event["workorder_id"]:
            item["workorder_id"] = event["workorder_id"]
        if clean := clean_item(item, len(remaining) + 1):
            remaining.append(clean)
    project["items"] = remaining
    return project, events, history, item_ids


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_project(path: Path, project: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(project_text(project), encoding="utf-8")
    os.replace(tmp, path)
