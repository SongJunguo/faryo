from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest


OWNER_ROOT = Path(__file__).resolve().parents[1]
if str(OWNER_ROOT) not in sys.path:
    sys.path.insert(0, str(OWNER_ROOT))

from delivery_store import DeliveryStore


class DeliveryStoreTest(unittest.TestCase):
    def store(self, root: Path, epoch: float = 100.0, monotonic: float = 50.0) -> DeliveryStore:
        return DeliveryStore(
            root,
            ttl_seconds=48 * 60 * 60,
            cleanup_interval_seconds=60 * 60,
            epoch_clock=lambda: epoch,
            monotonic_clock=lambda: monotonic,
        )

    def test_accepted_round_trip_is_private_and_body_free(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "receipts"
            store = self.store(root)
            delivery_id = "web-roundtrip"
            receipt = {"deliveryId": delivery_id, "delivery": "accepted", "session": "faryo1"}
            state = {"session": "faryo1", "digest": "a" * 64, "status": "accepted", "receipt": receipt}

            self.assertTrue(store.persist(delivery_id, state))
            loaded = store.load(delivery_id)

            self.assertEqual(loaded["receipt"], receipt)
            self.assertEqual(loaded["updatedAt"], 50.0)
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(store.record_path(delivery_id).stat().st_mode), 0o600)
            text = store.record_path(delivery_id).read_text(encoding="utf-8")
            self.assertNotIn("prompt", text.lower())
            self.assertNotIn("rolloutPath", text)

    def test_pasted_round_trip_keeps_only_bounded_recovery_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.store(Path(temp) / "receipts")
            state = {
                "session": "faryo1",
                "digest": "b" * 64,
                "status": "pasted",
                "pasteReady": True,
                "queuedBaseline": "2",
                "rolloutDevice": 10,
                "rolloutInode": 20,
                "rolloutOffset": 30,
            }
            self.assertTrue(store.persist("web-pasted", state))
            loaded = store.load("web-pasted")
            self.assertEqual(loaded["queuedBaseline"], 2)
            self.assertEqual(loaded["rolloutOffset"], 30)
            self.assertNotIn("receipt", loaded)

    def test_invalid_id_corrupt_large_and_symlink_records_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "receipts"
            root.mkdir()
            store = self.store(root)
            self.assertIsNone(store.record_path("short"))
            corrupt = store.record_path("web-corrupt")
            corrupt.write_text("not-json", encoding="utf-8")
            self.assertIsNone(store.load("web-corrupt"))
            large = store.record_path("web-too-large")
            large.write_text("x" * (16 * 1024 + 1), encoding="utf-8")
            self.assertIsNone(store.load("web-too-large"))
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            link = store.record_path("web-symlink")
            link.symlink_to(target)
            self.assertIsNone(store.load("web-symlink"))

    def test_expired_record_is_removed_and_cleanup_is_throttled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "receipts"
            store = self.store(root, epoch=200_000.0, monotonic=10_000.0)
            delivery_id = "web-expired"
            root.mkdir()
            path = store.record_path(delivery_id)
            path.write_text(json.dumps({
                "version": 2,
                "deliveryId": delivery_id,
                "session": "faryo1",
                "digest": "c" * 64,
                "status": "pasted",
                "updatedEpoch": 0,
            }), encoding="utf-8")
            self.assertIsNone(store.load(delivery_id))
            self.assertFalse(path.exists())

            stale = store.record_path("web-cleanup")
            stale.write_text("{}", encoding="utf-8")
            os.utime(stale, (0, 0))
            store.cleanup(now_epoch=200_000.0)
            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
