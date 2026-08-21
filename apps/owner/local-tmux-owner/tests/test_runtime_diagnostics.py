#!/usr/bin/env python3
"""Privacy contract for capability and diagnostics payloads."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import runtime_diagnostics


class RuntimeDiagnosticsTest(unittest.TestCase):
    def test_capabilities_are_versioned_and_pending_queue_is_not_overclaimed(self) -> None:
        payload = runtime_diagnostics.capability_payload("v-test", True, True)

        self.assertEqual(payload["schemaVersion"], 1)
        self.assertTrue(payload["features"]["workspaceChanges"])
        self.assertTrue(payload["features"]["diagnostics"])
        self.assertTrue(payload["features"]["goalStatus"])
        self.assertTrue(payload["features"]["structuredInteractions"])
        self.assertTrue(payload["features"]["commandCatalog"])
        self.assertTrue(payload["features"]["goalDetails"])
        self.assertFalse(payload["features"]["pendingQueueManagement"])
        self.assertEqual(payload["protocol"]["pendingQueue"], "unsupported")
        self.assertEqual(payload["protocol"]["tuiInteraction"], "v1")

    def test_diagnostics_contains_only_allowlisted_metadata(self) -> None:
        capabilities = runtime_diagnostics.capability_payload("v-test", False, False)
        payload = runtime_diagnostics.diagnostics_payload(
            capabilities,
            tmux_sessions=3,
            managed_sessions=2,
            recognized_agents=2,
            delivery_receipts=7,
            thread_cache_entries=4,
        )
        encoded = json.dumps(payload, ensure_ascii=False).lower()

        self.assertEqual(payload["counts"]["tmuxSessions"], 3)
        for forbidden in ("token", "cookie", "email", "hostname", "username", "sessionid", "cwd", "path", "prompt", "answer", "/home/"):
            self.assertNotIn(forbidden, encoded)


if __name__ == "__main__":
    unittest.main()
