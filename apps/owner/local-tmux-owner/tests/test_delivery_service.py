from __future__ import annotations

import threading
import time
import unittest
from unittest import mock
from pathlib import Path
import sys


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import delivery_service


class FakeStore:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.cleanup_calls = 0

    def record_path(self, _delivery_id: str):
        return None

    def cleanup(self, _now_epoch=None, *, force: bool = False) -> None:
        self.cleanup_calls += 1

    def persist(self, delivery_id: str, state: dict) -> bool:
        self.records[delivery_id] = dict(state)
        return True

    def load(self, delivery_id: str, _now_epoch=None):
        return self.records.get(delivery_id)


class FakeRuntime:
    def __init__(self) -> None:
        self.delivery_store = FakeStore()
        self.delivery_ttl_seconds = 10.0


class DeliveryServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = FakeRuntime()
        self.service = delivery_service.DeliveryService(self.runtime)

    def test_reference_counted_lock_registry_does_not_leak(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def worker() -> None:
            with self.service.session_lock("session-a"):
                entered.set()
                release.wait(1)

        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(entered.wait(1))
        self.assertEqual(self.service.session_locks["session-a"]["references"], 1)
        release.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.service.session_locks, {})

    def test_accepted_state_is_persisted_without_message_body(self) -> None:
        receipt = self.service.receipt(
            "message-a",
            mock.Mock(session="session-a"),
            "recorded",
            1,
        )
        self.service.remember_accepted("message-a", {
            "session": "session-a",
            "digest": "a" * 64,
            "status": "accepted",
            "receipt": receipt,
        })

        self.assertEqual(self.service.deliveries["message-a"]["receipt"], receipt)
        self.assertEqual(self.runtime.delivery_store.records["message-a"]["digest"], "a" * 64)
        self.assertNotIn("text", self.runtime.delivery_store.records["message-a"])

    def test_prune_removes_only_expired_memory_state_and_cleans_store(self) -> None:
        now = time.monotonic()
        self.service.deliveries.update({
            "expired": {"updatedAt": now - 11},
            "current": {"updatedAt": now - 2},
        })

        self.service.prune(now)

        self.assertNotIn("expired", self.service.deliveries)
        self.assertIn("current", self.service.deliveries)
        self.assertEqual(self.runtime.delivery_store.cleanup_calls, 1)


if __name__ == "__main__":
    unittest.main()
