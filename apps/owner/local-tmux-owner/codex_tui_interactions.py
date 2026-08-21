"""Pure parsers for current Codex CLI terminal interactions.

The parsers intentionally accept only an active numbered menu with a visible
selection marker and a confirmation cue.  Text quoted in an old conversation
must not become a live remote-control surface.
"""

from __future__ import annotations

import re
import unicodedata

from interaction_types import DetectedInteraction, InteractionOption


ANSI_ESCAPE_RE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
NUMBERED_OPTION_RE = re.compile(
    r"^\s*(?P<selected>[›>])?\s*(?P<ordinal>\d+)\.\s+(?P<body>\S.*)$"
)
SELECTED_OPTION_RE = re.compile(r"^\s*[›>]\s*\d+\.\s+\S")
CONFIRM_RE = re.compile(
    r"(?:press\s+enter\s+to\s+(?:confirm|continue)|enter\s+to\s+confirm)",
    re.I,
)
ACTIVE_COMPOSER_RE = re.compile(r"^\s*[›>»]\s+(?!\d+\.)\S")
CURRENT_RE = re.compile(r"\s*\(current\)\s*", re.I)
DEFAULT_RE = re.compile(r"\s*\(default\)\s*", re.I)


def normalized_lines(capture: str) -> list[str]:
    """Remove terminal controls while preserving visible menu text."""

    value = ANSI_ESCAPE_RE.sub("", str(capture or "")).replace("\r", "\n")
    value = CONTROL_RE.sub("", value)
    lines = [unicodedata.normalize("NFKC", line).rstrip() for line in value.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _active_menu_bounds(lines: list[str], title_index: int) -> tuple[int, int] | None:
    """Return the current title..confirm slice or reject historical text."""

    selected_indexes = [
        index
        for index in range(title_index + 1, len(lines))
        if SELECTED_OPTION_RE.match(lines[index])
    ]
    if not selected_indexes:
        return None
    selected_index = selected_indexes[-1]
    confirm_index = next(
        (
            index
            for index in range(selected_index + 1, len(lines))
            if CONFIRM_RE.search(lines[index])
        ),
        None,
    )
    if confirm_index is None:
        return None
    # A later ordinary composer means the same menu text is scrollback rather
    # than the active control surface.
    if any(ACTIVE_COMPOSER_RE.match(line) for line in lines[confirm_index + 1 :]):
        return None
    return title_index, confirm_index


def _last_title_index(lines: list[str], pattern: re.Pattern[str]) -> int | None:
    return next(
        (index for index in range(len(lines) - 1, -1, -1) if pattern.search(lines[index])),
        None,
    )


def _option_key(kind: str, label: str, ordinal: int) -> str:
    normalized = label.lower().replace("…", "...")
    normalized = re.sub(r"[^a-z0-9._+-]+", "-", normalized).strip("-")
    return f"{kind}:{normalized or ordinal}"


def _parse_numbered_options(
    lines: list[str],
    start: int,
    end: int,
    *,
    key_kind: str,
) -> tuple[InteractionOption, ...]:
    mutable: list[dict[str, object]] = []
    for line in lines[start:end]:
        match = NUMBERED_OPTION_RE.match(line)
        if match:
            body = match.group("body").strip()
            parts = re.split(r"\s{2,}", body, maxsplit=1)
            raw_label = parts[0].strip()
            description = parts[1].strip() if len(parts) > 1 else ""
            current = bool(CURRENT_RE.search(raw_label))
            label = CURRENT_RE.sub("", raw_label).strip()
            # Default is useful presentation text, not identity.
            default = bool(DEFAULT_RE.search(label))
            label = DEFAULT_RE.sub("", label).strip()
            if default:
                description = f"Default. {description}".strip()
            ordinal = int(match.group("ordinal"))
            mutable.append(
                {
                    "key": _option_key(key_kind, label, ordinal),
                    "label": label,
                    "description": description,
                    "selected": bool(match.group("selected")),
                    "current": current,
                    "disabled": False,
                    "ordinal": ordinal,
                }
            )
            continue
        stripped = line.strip()
        if not mutable or not stripped or CONFIRM_RE.search(stripped):
            continue
        # Wrapped descriptions do not receive a second ordinal from the TUI.
        # Append them to the last option instead of creating a guessed choice.
        previous = mutable[-1]
        previous["description"] = " ".join(
            value
            for value in (str(previous["description"]), stripped)
            if value
        )
    return tuple(InteractionOption(**value) for value in mutable)


def detect_model_selector(capture: str) -> DetectedInteraction | None:
    lines = normalized_lines(capture)
    title_re = re.compile(r"^\s*Select Model(?: and Effort)?\s*$", re.I)
    title_index = _last_title_index(lines, title_re)
    if title_index is None:
        return None
    bounds = _active_menu_bounds(lines, title_index)
    if bounds is None:
        return None
    options = _parse_numbered_options(
        lines,
        bounds[0] + 1,
        bounds[1],
        key_kind="model",
    )
    if not options:
        return None
    return DetectedInteraction(
        kind="model_select",
        title="Select model",
        prompt="Choose the model used by the next turn.",
        options=options,
    )


def detect_reasoning_selector(capture: str) -> DetectedInteraction | None:
    lines = normalized_lines(capture)
    title_re = re.compile(r"^\s*Select Reasoning (?:Level|Effort)(?: for .+)?\s*$", re.I)
    title_index = _last_title_index(lines, title_re)
    if title_index is None:
        return None
    bounds = _active_menu_bounds(lines, title_index)
    if bounds is None:
        return None
    options = _parse_numbered_options(
        lines,
        bounds[0] + 1,
        bounds[1],
        key_kind="reasoning",
    )
    if not options:
        return None
    return DetectedInteraction(
        kind="reasoning_select",
        title="Select reasoning level",
        prompt="Choose the reasoning level used by the selected model.",
        options=options,
    )


def detect_advanced_reasoning_selector(capture: str) -> DetectedInteraction | None:
    lines = normalized_lines(capture)
    title_re = re.compile(r"^\s*Advanced Reasoning\s*$", re.I)
    title_index = _last_title_index(lines, title_re)
    if title_index is None:
        return None
    bounds = _active_menu_bounds(lines, title_index)
    if bounds is None:
        return None
    options = _parse_numbered_options(
        lines,
        bounds[0] + 1,
        bounds[1],
        key_kind="reasoning",
    )
    if not options:
        return None
    return DetectedInteraction(
        kind="reasoning_select",
        title="Advanced reasoning",
        prompt="Choose an advanced reasoning level.",
        options=options,
    )


def detect_usage_selector(capture: str) -> DetectedInteraction | None:
    lines = normalized_lines(capture)
    title_re = re.compile(r"^\s*Usage\s*$", re.I)
    title_index = _last_title_index(lines, title_re)
    if title_index is None:
        return None
    bounds = _active_menu_bounds(lines, title_index)
    if bounds is None:
        return None
    options = _parse_numbered_options(
        lines,
        bounds[0] + 1,
        bounds[1],
        key_kind="usage",
    )
    if not options:
        return None
    return DetectedInteraction(
        kind="usage_select",
        title="Usage",
        prompt="Choose the account usage view or an available reset action.",
        options=options,
    )


def detect_permissions_selector(capture: str) -> DetectedInteraction | None:
    lines = normalized_lines(capture)
    title_re = re.compile(r"^\s*(?:Update Model Permissions|Select Permissions)\s*$", re.I)
    title_index = _last_title_index(lines, title_re)
    if title_index is None:
        return None
    bounds = _active_menu_bounds(lines, title_index)
    if bounds is None:
        return None
    options = _parse_numbered_options(
        lines,
        bounds[0] + 1,
        bounds[1],
        key_kind="permissions",
    )
    if not options:
        return None
    return DetectedInteraction(
        kind="permissions_select",
        title="Model permissions",
        prompt="Choose the permission profile used by Codex.",
        options=options,
    )


def detect_resume_directory_selector(capture: str) -> DetectedInteraction | None:
    lines = normalized_lines(capture)
    title_re = re.compile(r"Choose working directory to resume this session", re.I)
    title_index = _last_title_index(lines, title_re)
    if title_index is None:
        return None
    bounds = _active_menu_bounds(lines, title_index)
    if bounds is None:
        return None
    options = _parse_numbered_options(
        lines,
        bounds[0] + 1,
        bounds[1],
        key_kind="resume-directory",
    )
    if not options:
        return None
    return DetectedInteraction(
        kind="resume_directory",
        title="Choose working directory",
        prompt="Choose where Codex should resume this session.",
        options=options,
    )


def detect_workspace_trust_selector(capture: str) -> DetectedInteraction | None:
    lines = normalized_lines(capture)
    title_re = re.compile(
        r"(?:Do you trust (?:the )?(?:contents of )?this directory|Trust this workspace)",
        re.I,
    )
    title_index = _last_title_index(lines, title_re)
    if title_index is None:
        return None
    bounds = _active_menu_bounds(lines, title_index)
    if bounds is None:
        return None
    options = _parse_numbered_options(
        lines,
        bounds[0] + 1,
        bounds[1],
        key_kind="workspace-trust",
    )
    if not options:
        return None
    return DetectedInteraction(
        kind="workspace_trust",
        title="Workspace trust",
        prompt="Codex is waiting for a workspace trust decision.",
        options=options,
    )


def detect_approval_selector(capture: str) -> DetectedInteraction | None:
    lines = normalized_lines(capture)
    title_re = re.compile(
        r"(?:Would you like to .+\?|Allow Codex to .+\?|Approval requested)",
        re.I,
    )
    title_index = _last_title_index(lines, title_re)
    if title_index is None:
        return None
    bounds = _active_menu_bounds(lines, title_index)
    if bounds is None:
        return None
    options = _parse_numbered_options(
        lines,
        bounds[0] + 1,
        bounds[1],
        key_kind="approval",
    )
    if not options:
        return None
    return DetectedInteraction(
        kind="approval",
        title="Codex approval",
        prompt="Review the action in the terminal evidence before choosing.",
        options=options,
    )


def detect_generic_selector(capture: str) -> DetectedInteraction | None:
    lines = normalized_lines(capture)
    selected_index = next(
        (index for index in range(len(lines) - 1, -1, -1) if SELECTED_OPTION_RE.match(lines[index])),
        None,
    )
    if selected_index is None:
        return None
    confirm_index = next(
        (
            index
            for index in range(selected_index + 1, len(lines))
            if CONFIRM_RE.search(lines[index])
        ),
        None,
    )
    if confirm_index is None or any(
        ACTIVE_COMPOSER_RE.match(line) for line in lines[confirm_index + 1 :]
    ):
        return None
    start = selected_index
    while start > 0 and (
        NUMBERED_OPTION_RE.match(lines[start - 1])
        or (lines[start - 1].strip() and not CONFIRM_RE.search(lines[start - 1]))
    ):
        start -= 1
        if selected_index - start > 24:
            break
    options = _parse_numbered_options(
        lines,
        start,
        confirm_index,
        key_kind="generic",
    )
    if not options:
        return None
    title = next(
        (
            line.strip()
            for line in reversed(lines[max(0, start - 4) : start])
            if line.strip()
        ),
        "Codex menu",
    )
    return DetectedInteraction(
        kind="generic_tui",
        title=title[:120],
        prompt="Codex is waiting for a terminal choice.",
        options=options,
    )


DETECTORS = (
    detect_resume_directory_selector,
    detect_model_selector,
    detect_reasoning_selector,
    detect_advanced_reasoning_selector,
    detect_usage_selector,
    detect_permissions_selector,
    detect_workspace_trust_selector,
    detect_approval_selector,
    detect_generic_selector,
)


def detect_interaction(capture: str) -> DetectedInteraction | None:
    """Return the first specific active interaction from the registry."""

    for detector in DETECTORS:
        detected = detector(capture)
        if detected is not None:
            return detected
    return None
