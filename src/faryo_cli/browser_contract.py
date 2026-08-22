"""Versioned browser JSON envelope shared by Gateway and Owner."""

from __future__ import annotations

from typing import Any, Mapping


ENVELOPE_VERSION = 1
ENVELOPE_FIELD = "envelopeVersion"


class BrowserContractError(ValueError):
    pass


def wrap_response(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    payload[ENVELOPE_FIELD] = ENVELOPE_VERSION
    return payload


def require_supported_version(
    value: Mapping[str, Any],
    *,
    allow_legacy: bool = True,
) -> None:
    raw = value.get(ENVELOPE_FIELD)
    if raw is None and allow_legacy:
        return
    if isinstance(raw, bool) or raw != ENVELOPE_VERSION:
        raise BrowserContractError("unsupported browser envelope version")
