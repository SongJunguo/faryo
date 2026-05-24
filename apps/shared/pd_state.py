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


def clean_stage_dod_done(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text or text == "0":
        return []
    return [item for item in (compact_text(part) for part in re.split(r"[；;、,，]", text)) if item]


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
    return {key: value for key, value in data.items() if value}


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


def write_stage_dod_done(path: Path, item: Any, done: bool) -> None:
    item_text = compact_text(item)
    values = [value for value in parse_project_definition(path.read_text(encoding="utf-8")).get("stage_dod_done", []) if compact_text(value) and compact_text(value) != item_text]
    if done and item_text:
        values.append(item_text)
    replacement = f"- 阶段 DoD 已完成：{'；'.join(values)}" if values else None
    write_current_stage_line(path, r"-\s*阶段\s*DoD\s*已完成[:：]", replacement, r"-\s*阶段\s*DoD[:：]")
