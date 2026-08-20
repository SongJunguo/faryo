"""Privacy-allowlisted capability and diagnostics payloads."""

from __future__ import annotations

from typing import Any


SCHEMA_VERSION = 1


def capability_payload(release: str, app_server_configured: bool, metadata_available: bool) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "releaseVersion": str(release or "unknown"),
        "runtime": "codex",
        "features": {
            "archiveRestore": True,
            "bodyFreeAttention": True,
            "diagnostics": True,
            "documentScroll": True,
            "fullscreen": True,
            "markdownMath": True,
            "pendingQueueManagement": False,
            "pwa": True,
            "reliableDelivery": True,
            "structuredHistory": bool(metadata_available),
            "workspaceChanges": True,
        },
        "protocol": {
            "appServerConfigured": bool(app_server_configured),
            "pendingQueue": "unsupported",
            "turnSteer": "not-used-for-tui-owned-turns",
        },
    }


def diagnostics_payload(
    capabilities: dict[str, Any],
    *,
    tmux_sessions: int,
    managed_sessions: int,
    recognized_agents: int,
    delivery_receipts: int,
    thread_cache_entries: int,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "releaseVersion": capabilities.get("releaseVersion") or "unknown",
        "runtime": capabilities.get("runtime") or "codex",
        "features": dict(capabilities.get("features") or {}),
        "protocol": dict(capabilities.get("protocol") or {}),
        "counts": {
            "deliveryReceipts": max(0, int(delivery_receipts)),
            "managedSessions": max(0, int(managed_sessions)),
            "recognizedAgents": max(0, int(recognized_agents)),
            "threadCacheEntries": max(0, int(thread_cache_entries)),
            "tmuxSessions": max(0, int(tmux_sessions)),
        },
    }
