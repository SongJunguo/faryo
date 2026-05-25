"""Shared project.md parsing and current-stage update helpers."""

from __future__ import annotations

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
    if "stage_dod" in payload:
        items = clean_stage_dod_items(payload.get("stage_dod"))
        updated["stage_dod"] = "；".join(items)
        updated["stage_dod_done"] = [item for item in clean_stage_dod_done(updated.get("stage_dod_done")) if item in items]
        return clean_project_definition(updated)
    item_text = compact_text(payload.get("item"))
    if not item_text:
        raise ValueError("DoD item is required")
    values = [value for value in clean_stage_dod_done(updated.get("stage_dod_done")) if value != item_text]
    if bool(payload.get("done")):
        values.append(item_text)
    updated["stage_dod_done"] = values
    return clean_project_definition(updated)


def write_project_definition(path: Path, definition: Any) -> None:
    clean = clean_project_definition(definition)
    if "current_phase" in clean:
        write_current_phase_line(path, clean.get("current_phase"))
    ensure_current_stage_section(path, clean)
    if "stage_state" in clean:
        write_stage_state(path, clean.get("stage_state"))
    if "stage_dod" in clean:
        write_stage_dod(path, clean.get("stage_dod"))
    if "stage_dod_done" in clean:
        if "stage_dod" in clean:
            current_dod = clean_stage_dod_items(clean.get("stage_dod"))
            values = [item for item in clean_stage_dod_done(clean.get("stage_dod_done")) if item in current_dod]
        else:
            current_dod = clean_stage_dod_items(parse_project_definition(path.read_text(encoding="utf-8")).get("stage_dod"))
            values = [item for item in clean_stage_dod_done(clean.get("stage_dod_done")) if not current_dod or item in current_dod]
        write_stage_dod_done_values(path, values)


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


def write_current_stage_line(path: Path, field_pattern: str, replacement: str | None, insert_after_pattern: str | None = None) -> None:
    output, inserted, in_current = [], False, False
    field_re = re.compile(field_pattern, re.IGNORECASE)
    after_re = re.compile(insert_after_pattern, re.IGNORECASE) if insert_after_pattern else None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "### 当前阶段":
            in_current = True
        elif stripped.startswith("### "):
            if in_current and not inserted and replacement:
                output.append(replacement)
                inserted = True
            in_current = False
        if in_current and field_re.match(stripped):
            if replacement:
                output.append(replacement)
            inserted = True
            continue
        output.append(line)
        if in_current and after_re and not inserted and replacement and after_re.match(stripped):
            output.append(replacement)
            inserted = True
    if in_current and not inserted and replacement:
        output.append(replacement)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_stage_state(path: Path, stage_state: Any) -> None:
    write_current_stage_line(path, r"-\s*阶段(?:状态|进度)[:：]", f"- 阶段状态：{clean_stage_state(stage_state)}")


def write_stage_dod_done_values(path: Path, values: list[str]) -> None:
    replacement = f"- 阶段 DoD 已完成：{'；'.join(values)}" if values else None
    write_current_stage_line(path, r"-\s*阶段\s*DoD\s*已完成[:：]", replacement, r"-\s*阶段\s*DoD[:：]")


def write_stage_dod(path: Path, stage_dod: Any) -> None:
    items = clean_stage_dod_items(stage_dod)
    current_done = parse_project_definition(path.read_text(encoding="utf-8")).get("stage_dod_done", [])
    replacement = f"- 阶段 DoD：{'；'.join(items)}" if items else None
    write_current_stage_line(path, r"-\s*阶段\s*DoD\s*[:：]", replacement, r"-\s*阶段目标[:：]")
    write_stage_dod_done_values(path, [item for item in current_done if item in items])
