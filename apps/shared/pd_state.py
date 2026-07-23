"""Shared conops.md parsing and current-stage update helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

STAGE_STATES = {"stage_to_define", "define_to_execute", "execute_to_close", "closed"}


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def clean_stage_state(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in STAGE_STATES:
        return text
    return {"1": "stage_to_define", "2": "define_to_execute", "3": "execute_to_close", "4": "closed"}.get(text[:1], "stage_to_define")


def unique_compact_items(parts: Any) -> list[str]:
    items = []
    for item in (compact_text(part) for part in parts):
        if item and item not in items:
            items.append(item)
    return items


def clean_item_decision_option(option: Any) -> dict[str, str]:
    if not isinstance(option, dict):
        return {}
    option_id = compact_text(option.get("id"))
    label = compact_text(option.get("label"))
    return {"id": option_id, "label": label} if option_id and label else {}


def clean_item_decision_prompt(value: Any, item_type: Any) -> dict[str, Any]:
    if compact_text(item_type) != "decision" or not isinstance(value, dict):
        return {}
    mode = compact_text(value.get("mode"))
    if mode not in {"choice", "binary", "checklist", "short_note"}:
        return {}
    clean: dict[str, Any] = {"mode": mode}
    label = compact_text(value.get("label"))
    if label:
        clean["label"] = label
    if mode in {"choice", "binary"}:
        options = []
        for option in value.get("options", []):
            clean_option = clean_item_decision_option(option)
            if clean_option:
                options.append(clean_option)
        if len(options) < 2:
            return {}
        clean["options"] = options[: 2 if mode == "binary" else 5]
    elif mode == "checklist":
        items = unique_compact_items(value.get("items") if isinstance(value.get("items"), list) else [])
        if not items:
            return {}
        clean["items"] = items[:5]
    else:
        placeholder = compact_text(value.get("placeholder"))
        if placeholder:
            clean["placeholder"] = placeholder
    if bool(value.get("required")):
        clean["required"] = True
    return clean


def clean_owner_decision(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, Any] = {}
    selected = compact_text(value.get("selected"))
    if selected:
        clean["selected"] = selected
    checked = unique_compact_items(value.get("checked") if isinstance(value.get("checked"), list) else [])
    if checked:
        clean["checked"] = checked[:5]
    note = compact_text(value.get("note"))
    if note:
        clean["note"] = note
    return clean


def clean_stage_dod_done(value: Any) -> list[str]:
    if isinstance(value, list):
        return unique_compact_items(value)
    text = str(value or "").strip()
    return [] if not text or text == "0" else unique_compact_items(re.split(r"[；;、,，]", text))


def clean_completed_stages(value: Any) -> list[str]:
    source = value if isinstance(value, list) else str(value or "").splitlines()
    return unique_compact_items(source)


def clean_project_definition(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, Any] = {}
    for key in ("current_phase", "current_stage_id", "current_stage_title", "stage_position", "stage_goal", "stage_out_of_scope"):
        text = compact_text(value.get(key))
        if text:
            clean[key] = text
    if "stage_state" in value:
        clean["stage_state"] = clean_stage_state(value.get("stage_state"))
    if "stage_dod" in value:
        clean["stage_dod"] = "；".join(clean_stage_dod_items(value.get("stage_dod")))
    if "stage_dod_done" in value:
        done = clean_stage_dod_done(value.get("stage_dod_done"))
        if "stage_dod" in clean:
            dod = clean_stage_dod_items(clean.get("stage_dod"))
            clean["stage_dod_done"] = [item for item in done if item in dod]
        else:
            clean["stage_dod_done"] = done
    completed = clean_completed_stages(value.get("completed_stages"))
    if completed:
        clean["completed_stages"] = completed
    return clean


def project_definition_hash_payload(value: Any) -> dict[str, Any]:
    return {key: item for key, item in clean_project_definition(value).items() if item not in ("", [])}


def project_definition_downlink_hash(project_id: Any, definition: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(project_id or "").strip().lower()).strip("-") or "project"
    body = json.dumps({
        "id": slug,
        "definition": project_definition_hash_payload(definition),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def current_stage_heading(definition: dict[str, Any]) -> str:
    stage_id = compact_text(definition.get("current_stage_id") or definition.get("current_phase"))
    title = compact_text(definition.get("current_stage_title")) or "当前阶段"
    return f"#### {stage_id}：{title}" if stage_id else f"#### {title}"


def current_stage_lines(definition: dict[str, Any]) -> list[str]:
    lines = ["", "### 当前阶段", current_stage_heading(definition)]
    fields = [
        ("stage_position", "阶段定位"),
        ("stage_goal", "阶段目标"),
        ("stage_dod", "阶段 DoD"),
        ("stage_state", "阶段状态"),
        ("stage_dod_done", "阶段 DoD 已完成"),
        ("stage_out_of_scope", "当前不做"),
    ]
    for key, label in fields:
        if key not in definition:
            continue
        value = definition[key]
        text = "；".join(value) if isinstance(value, list) else str(value)
        lines.append(f"- {label}：{text}")
    return lines


def ensure_current_stage_section(path: Path, definition: dict[str, Any]) -> None:
    text = path.read_text(encoding="utf-8")
    if "### 当前阶段" in text or not definition:
        return
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(text.rstrip() + "\n" + "\n".join(current_stage_lines(definition)) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def current_stage_block_lines(definition: dict[str, Any]) -> list[str]:
    lines = current_stage_lines(definition)
    return lines[1:] if lines[:1] == [""] else lines


def canonicalize_current_stage_section(path: Path, updates: dict[str, Any]) -> None:
    text = path.read_text(encoding="utf-8")
    definition = clean_project_definition({**parse_project_definition(text), **clean_project_definition(updates)})
    if not definition:
        return
    block = current_stage_block_lines(definition)
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    replaced = False
    while index < len(lines):
        if lines[index].strip() == "### 当前阶段":
            if output and output[-1].strip():
                output.append("")
            output.extend(block)
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("### "):
                index += 1
            if index < len(lines) and lines[index].strip():
                output.append("")
            replaced = True
            continue
        output.append(lines[index])
        index += 1
    if not replaced:
        if output and output[-1].strip():
            output.append("")
        output.extend(block)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_current_phase_line(path: Path, current_phase: Any) -> None:
    phase = compact_text(current_phase)
    if not phase:
        return
    lines, replaced = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("current_stage:", "current_phase:")):
            if not replaced:
                lines.append(f'current_stage: "{phase}"')
                replaced = True
            continue
        lines.append(line)
    if not replaced:
        insert_at = 1 if lines and lines[0].startswith("#") else 0
        lines.insert(insert_at, f'current_stage: "{phase}"')
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def definition_with_stage_state(definition: Any, stage_state: Any) -> dict[str, Any]:
    updated = clean_project_definition(definition)
    updated["stage_state"] = clean_stage_state(stage_state)
    return clean_project_definition(updated)


def definition_with_stage_dod_update(definition: Any, payload: dict[str, Any]) -> dict[str, Any]:
    updated = clean_project_definition(definition)
    if "stage_state" in payload:
        updated["stage_state"] = clean_stage_state(payload.get("stage_state"))
    if "stage_dod" in payload:
        items = clean_stage_dod_items(payload.get("stage_dod"))
        updated["stage_dod"] = "；".join(items)
        updated["stage_dod_done"] = [item for item in clean_stage_dod_done(updated.get("stage_dod_done")) if item in items]
    if "stage_dod_done" in payload:
        items = clean_stage_dod_items(updated.get("stage_dod"))
        updated["stage_dod_done"] = [item for item in clean_stage_dod_done(payload.get("stage_dod_done")) if item in items]
    item_text = compact_text(payload.get("item"))
    if item_text:
        values = [value for value in clean_stage_dod_done(updated.get("stage_dod_done")) if value != item_text]
        if bool(payload.get("done")):
            values.append(item_text)
        updated["stage_dod_done"] = values
    elif not any(key in payload for key in ("stage_state", "stage_dod", "stage_dod_done")):
        raise ValueError("DoD item is required")
    return clean_project_definition(updated)


def write_project_definition(path: Path, definition: Any) -> None:
    clean = clean_project_definition(definition)
    if "current_phase" in clean:
        write_current_phase_line(path, clean.get("current_phase"))
    ensure_current_stage_section(path, clean)
    if "stage_dod_done" in clean:
        if "stage_dod" in clean:
            current_dod = clean_stage_dod_items(clean.get("stage_dod"))
            values = [item for item in clean_stage_dod_done(clean.get("stage_dod_done")) if item in current_dod]
        else:
            current_dod = clean_stage_dod_items(parse_project_definition(path.read_text(encoding="utf-8")).get("stage_dod"))
            values = [item for item in clean_stage_dod_done(clean.get("stage_dod_done")) if not current_dod or item in current_dod]
        clean["stage_dod_done"] = values
    canonicalize_current_stage_section(path, clean)


def clean_stage_dod_items(value: Any) -> list[str]:
    return unique_compact_items(re.split(r"[\r\n；;、,，]+", str(value or "")))


def split_stage_heading(heading: str) -> tuple[str, str]:
    for sep in ("：", ":"):
        if sep in heading:
            left, right = heading.split(sep, 1)
            return compact_text(left), compact_text(right)
    return "", compact_text(heading)


def parse_project_definition(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {"completed_stages": []}
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("current_stage:", "current_phase:")):
            data["current_phase"] = line.split(":", 1)[1].strip().strip('"')
        if line.startswith("### "):
            section = line.lstrip("#").strip()
            continue
        if line.startswith("#### "):
            heading = line.lstrip("#").strip()
            if section == "当前阶段":
                stage_id, stage_title = split_stage_heading(heading)
                data.update({"current_stage_id": stage_id, "current_stage_title": stage_title})
            elif section == "已完成阶段":
                data["completed_stages"].append(heading)
            continue
        if section == "当前阶段" and line.startswith("-"):
            key, _, value = line[1:].strip().partition("：")
            if not value:
                key, _, value = line[1:].strip().partition(":")
            target = {
                "阶段定位": "stage_position",
                "阶段目标": "stage_goal",
                "阶段dod": "stage_dod",
                "阶段状态": "stage_state",
                "阶段进度": "stage_state",
                "阶段dod已完成": "stage_dod_done",
                "当前不做": "stage_out_of_scope",
            }.get(key.strip().replace(" ", "").lower())
            if target == "stage_state":
                data[target] = clean_stage_state(value)
            elif target == "stage_dod_done":
                data[target] = clean_stage_dod_done(value)
            elif target and value.strip():
                data[target] = value.strip()
    return clean_project_definition(data)
