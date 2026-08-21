"""Immutable structured interaction types shared by Owner adapters.

The types in this module deliberately contain no tmux, HTTP, filesystem or
global-cache operations.  Adapters may parse private terminal text into these
objects, but only InteractionService is allowed to create the opaque public
identifiers returned to a browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json


INTERACTION_ACTIONS = ("previous", "next", "choose", "cancel")


@dataclass(frozen=True)
class InteractionOption:
    """One adapter-owned option before public identifier projection."""

    key: str
    label: str
    description: str = ""
    selected: bool = False
    current: bool = False
    disabled: bool = False
    ordinal: int | None = None

    def signature_value(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "selected": self.selected,
            "current": self.current,
            "disabled": self.disabled,
            "ordinal": self.ordinal,
        }


@dataclass(frozen=True)
class DetectedInteraction:
    """A side-effect-free adapter result for the current terminal state."""

    kind: str
    title: str
    prompt: str = ""
    options: tuple[InteractionOption, ...] = field(default_factory=tuple)
    actions: tuple[str, ...] = INTERACTION_ACTIONS
    source: str = "codex-tui"

    @property
    def selected_index(self) -> int | None:
        return next(
            (index for index, option in enumerate(self.options) if option.selected),
            None,
        )

    def fingerprint(self) -> str:
        """Return a stable body-free fingerprint of the normalized state."""

        value = {
            "kind": self.kind,
            "title": self.title,
            "prompt": self.prompt,
            "actions": list(self.actions),
            "source": self.source,
            "options": [option.signature_value() for option in self.options],
        }
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
