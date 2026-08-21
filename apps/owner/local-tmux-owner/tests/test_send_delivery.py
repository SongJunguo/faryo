import json
import hashlib
import stat
import sys
import tempfile
import threading
import time
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import server
import delivery_store


class SendDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.config = server.Config("codex-send-test", "token", 145)
        server._send_deliveries.clear()
        server._send_session_locks.clear()
        server._send_message_locks.clear()
        self.delivery_temp = tempfile.TemporaryDirectory()
        self.original_delivery_root = server.SEND_DELIVERY_ROOT
        self.original_delivery_store = server._delivery_store
        server.SEND_DELIVERY_ROOT = Path(self.delivery_temp.name) / "send-deliveries"
        server._delivery_store = delivery_store.DeliveryStore(
            server.SEND_DELIVERY_ROOT,
            ttl_seconds=server.SEND_DELIVERY_TTL_SECONDS,
            cleanup_interval_seconds=server.SEND_DELIVERY_CLEANUP_INTERVAL_SECONDS,
        )
        self.completed = mock.Mock(returncode=0, stdout="", stderr="")

    def tearDown(self):
        server._send_deliveries.clear()
        server._send_session_locks.clear()
        server._send_message_locks.clear()
        server.SEND_DELIVERY_ROOT = self.original_delivery_root
        server._delivery_store = self.original_delivery_store
        self.delivery_temp.cleanup()

    def send_patches(self, *, composer_states=None, submission_states=None, composer_contains_states=None, submission_key="Enter"):
        return (
            mock.patch.object(server, "has_session", return_value=True),
            mock.patch.object(server, "agent_profile_in_pane", return_value=server.CODEX_PROFILE),
            mock.patch.object(server, "codex_composer_has_draft", side_effect=composer_states or [False]),
            mock.patch.object(server, "tmux_capture_compact", return_value="baseline"),
            mock.patch.object(server, "tmux_cursor_position", return_value=(2, 20)),
            mock.patch.object(server, "wait_for_paste_tail", return_value=True),
            mock.patch.object(server, "wait_for_codex_submission", side_effect=submission_states or ["submitted"]),
            mock.patch.object(server, "codex_submission_key", return_value=submission_key),
            mock.patch.object(server, "codex_composer_contains_text", side_effect=composer_contains_states or [True]),
            mock.patch.object(server, "tmux", return_value=self.completed),
            mock.patch.object(server.time, "sleep"),
        )

    def test_delivery_runtime_preserves_keyword_only_tmux_timeout(self):
        with mock.patch.object(server, "tmux", return_value=self.completed) as tmux:
            result = server.DeliveryRuntime.tmux(self.config, ["display-message"], timeout=3)

        self.assertIs(result, self.completed)
        tmux.assert_called_once_with(self.config, ["display-message"], timeout=3)

    def test_wait_for_paste_tail_accepts_observed_cursor_change(self):
        with (
            mock.patch.object(server, "tmux_capture_compact", return_value="unchanged"),
            mock.patch.object(server, "tmux_cursor_position", return_value=(18, 20)),
        ):
            ready = server.wait_for_paste_tail(self.config, "hello world", "unchanged", (2, 20))

        self.assertTrue(ready)

    def test_rollout_confirmation_uses_only_new_exact_user_message(self):
        with tempfile.NamedTemporaryFile("w+b") as fh:
            fh.write((json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "old"}]}}) + "\n").encode())
            offset = fh.tell()
            fh.write((json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "confirmed text"}]}}) + "\n").encode())
            fh.flush()
            probe = (Path(fh.name), offset)
            self.assertTrue(server.codex_rollout_has_user_message(probe, "confirmed text"))
            self.assertFalse(server.codex_rollout_has_user_message(probe, "old"))
            self.assertFalse(server.codex_rollout_has_user_message(probe, "confirmed"))

    def test_wait_for_submission_prefers_rollout_confirmation(self):
        with (
            mock.patch.object(server, "codex_rollout_has_user_message", return_value=True),
            mock.patch.object(server, "tmux_cursor_position") as cursor,
        ):
            state = server.wait_for_codex_submission(self.config, "confirmed", rollout_probe=mock.sentinel.probe)

        self.assertEqual("recorded", state)
        cursor.assert_not_called()

    def test_active_composer_prompt_uses_double_angle_while_working(self):
        capture = "\n".join((
            "› already submitted",
            "• Working (1s • esc to interrupt)",
            "» current web draft",
            "  tab to queue message",
        ))

        self.assertIn("current web draft", server.last_agent_prompt_block_from_text(capture))
        self.assertNotIn("already submitted", server.last_agent_prompt_block_from_text(capture))

    def test_ansi_draft_detection_distinguishes_dim_placeholder(self):
        placeholder = "\x1b[1m›\x1b[0m \x1b[2mUse /skills to list available skills\x1b[0m"
        idle_draft = "\x1b[1m›\x1b[0m actual draft"
        working_draft = "\x1b[1m\x1b[38;2;186;130;255m»\x1b[0m wrapped draft"

        self.assertFalse(server.ansi_prompt_has_real_text(placeholder))
        self.assertTrue(server.ansi_prompt_has_real_text(idle_draft))
        self.assertTrue(server.ansi_prompt_has_real_text(working_draft))

    def test_submission_key_queues_only_while_codex_is_working(self):
        with mock.patch.object(server, "tmux_current_capture", return_value="› idle prompt\n  100% context left"):
            self.assertEqual("Enter", server.codex_submission_key(self.config))
        with mock.patch.object(server, "tmux_current_capture", return_value="» follow up\n  tab to queue message"):
            self.assertEqual("Tab", server.codex_submission_key(self.config))
        with mock.patch.object(server, "tmux_current_capture", return_value="• Working (1s • esc to interrupt)\n» follow up"):
            self.assertEqual("Tab", server.codex_submission_key(self.config))
        with mock.patch.object(server, "tmux_current_capture", return_value="• Worked for 2s (esc to interrupt)\n› idle prompt"):
            self.assertEqual("Enter", server.codex_submission_key(self.config))

    def test_exact_slash_command_cannot_enter_generic_retry_delivery(self):
        with (
            mock.patch.object(server, "has_session", return_value=True),
            mock.patch.object(server, "tmux") as tmux,
        ):
            with self.assertRaises(server.OwnerError) as raised:
                server.send_text(self.config, "/model", "web-command-route")

        self.assertEqual(HTTPStatus.CONFLICT, raised.exception.status)
        self.assertIn("structured interaction", str(raised.exception))
        tmux.assert_not_called()

        with (
            mock.patch.object(server, "has_session", return_value=True),
            mock.patch.object(server, "tmux") as tmux,
        ):
            with self.assertRaises(server.OwnerError):
                server.send_text(self.config, "/rename Anonymous title", "web-command-argument")
        tmux.assert_not_called()

    def test_wait_for_submission_accepts_cleared_active_composer_while_working(self):
        capture = "\n".join((
            "› prompt that has just been submitted",
            "• Starting MCP servers (1s • esc to interrupt)",
            "» Use /skills to list available skills",
        ))
        with (
            mock.patch.object(server, "codex_rollout_has_user_message", return_value=False),
            mock.patch.object(server, "tmux_current_capture", return_value=capture),
        ):
            state = server.wait_for_codex_submission(self.config, "prompt that has just been submitted", timeout=0.1)

        self.assertEqual("submitted", state)

    def test_wait_for_submission_recognizes_exact_queued_followup(self):
        capture = "\n".join((
            "• Queued follow-up inputs",
            "  ↳ keep working, then answer this followup",
            "» Improve documentation in @filename",
        ))
        with (
            mock.patch.object(server, "codex_rollout_has_user_message", return_value=False),
            mock.patch.object(server, "tmux_current_capture", return_value=capture),
        ):
            state = server.wait_for_codex_submission(self.config, "keep working, then answer this followup", timeout=0.1)

        self.assertEqual("queued", state)

    def test_existing_identical_queue_does_not_confirm_active_composer_copy(self):
        capture = "\n".join((
            "• Queued follow-up inputs",
            "  ↳ repeat exactly",
            "» repeat exactly",
            "  tab to queue message",
        ))
        with (
            mock.patch.object(server, "codex_rollout_has_user_message", return_value=False),
            mock.patch.object(server, "tmux_current_capture", return_value=capture),
        ):
            state = server.wait_for_codex_submission(
                self.config,
                "repeat exactly",
                timeout=0.01,
                queued_baseline=1,
                allow_composer_disappearance=False,
            )

        self.assertIsNone(state)
        self.assertEqual(1, server.codex_queued_followup_count(capture, "repeat exactly"))

    def test_identical_queue_requires_count_increase(self):
        capture = "\n".join((
            "• Queued follow-up inputs",
            "  ↳ repeat exactly",
            "  ↳ repeat exactly",
            "» Improve documentation in @filename",
        ))
        with (
            mock.patch.object(server, "codex_rollout_has_user_message", return_value=False),
            mock.patch.object(server, "tmux_current_capture", return_value=capture),
        ):
            state = server.wait_for_codex_submission(
                self.config,
                "repeat exactly",
                timeout=0.1,
                queued_baseline=1,
                allow_composer_disappearance=False,
            )

        self.assertEqual("queued", state)

    def test_retries_enter_until_codex_confirms_submission(self):
        patches = self.send_patches(submission_states=[None, "submitted"])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9] as tmux, patches[10]:
            receipt = server.send_text(self.config, "hello", "web-retry-enter")

        enter_keys = [call.args[1][-1] for call in tmux.call_args_list if call.args[1][:3] == ["send-keys", "-t", self.config.session]]
        self.assertEqual(["Enter", "Enter"], enter_keys)
        self.assertEqual("accepted", receipt["delivery"])
        self.assertEqual("submitted", receipt["deliveryState"])
        self.assertEqual(2, receipt["enterAttempts"])

    def test_working_codex_uses_tab_and_returns_queued_receipt(self):
        patches = self.send_patches(submission_states=["queued"], submission_key="Tab")
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9] as tmux, patches[10]:
            receipt = server.send_text(self.config, "follow up", "web-queued-followup")

        keys = [call.args[1][-1] for call in tmux.call_args_list if call.args[1][:3] == ["send-keys", "-t", self.config.session]]
        self.assertEqual(["Tab"], keys)
        self.assertEqual("queued", receipt["deliveryState"])

    def test_retry_after_timeout_does_not_paste_the_message_twice(self):
        patches = self.send_patches(composer_states=[False], submission_states=[None, None, None, "submitted"], composer_contains_states=[True])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9] as tmux, patches[10]:
            with self.assertRaises(server.OwnerError) as raised:
                server.send_text(self.config, "keep this draft", "web-timeout-retry")
            receipt = server.send_text(self.config, "keep this draft", "web-timeout-retry")

        self.assertEqual(HTTPStatus.GATEWAY_TIMEOUT, raised.exception.status)
        paste_calls = [call for call in tmux.call_args_list if call.args[1] and call.args[1][0] == "paste-buffer"]
        self.assertEqual(1, len(paste_calls))
        self.assertEqual("accepted", receipt["delivery"])
        self.assertEqual(1, receipt["enterAttempts"])

    def test_retry_without_rollout_or_new_queue_evidence_stays_ambiguous(self):
        delivery_id = "web-ambiguous-retry"
        text = "lost draft"
        server._send_deliveries[delivery_id] = {
            "session": self.config.session,
            "digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "status": "pasted",
            "pasteReady": True,
            "queuedBaseline": 0,
            "updatedAt": time.monotonic(),
        }
        with (
            mock.patch.object(server, "has_session", return_value=True),
            mock.patch.object(server, "agent_profile_in_pane", return_value=server.CODEX_PROFILE),
            mock.patch.object(server, "codex_rollout_submission_probe", return_value=None),
            mock.patch.object(server, "codex_composer_contains_text", return_value=False),
            mock.patch.object(server, "wait_for_codex_submission", return_value=None),
            mock.patch.object(server, "tmux", return_value=self.completed) as tmux,
        ):
            with self.assertRaises(server.OwnerError) as raised:
                server.send_text(self.config, text, delivery_id)

        self.assertEqual(HTTPStatus.GATEWAY_TIMEOUT, raised.exception.status)
        self.assertNotIn("receipt", server._send_deliveries[delivery_id])
        self.assertFalse(any(call.args[1] and call.args[1][0] == "send-keys" for call in tmux.call_args_list))

    def test_pasted_state_survives_memory_clear_without_message_body(self):
        delivery_id = "web-pasted-restart"
        state = {
            "session": self.config.session,
            "digest": "1" * 64,
            "status": "pasted",
            "pasteReady": True,
            "queuedBaseline": 2,
            "rolloutDevice": 10,
            "rolloutInode": 20,
            "rolloutOffset": 30,
        }

        server.remember_pasted_send_delivery(delivery_id, state)
        server._send_deliveries.clear()
        loaded = server.load_persisted_send_delivery(delivery_id)

        self.assertEqual("pasted", loaded["status"])
        self.assertEqual(2, loaded["queuedBaseline"])
        self.assertEqual(30, loaded["rolloutOffset"])
        record = server.send_delivery_record_path(delivery_id)
        self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
        self.assertNotIn("lost draft", record.read_text(encoding="utf-8"))

    def test_different_sessions_do_not_share_the_long_delivery_lock(self):
        config_a = server.Config("codex-send-a", "token", 0)
        config_b = server.Config("codex-send-b", "token", 0)
        delivery_a = "web-concurrent-a"
        delivery_b = "web-concurrent-b"
        entered_a = threading.Event()
        release_a = threading.Event()
        entered_b = threading.Event()
        errors = []

        def confirmation(config, _text, **_kwargs):
            if config.session == config_a.session:
                entered_a.set()
                release_a.wait(2)
            else:
                entered_b.set()
            return "submitted"

        def worker(config, text, delivery_id):
            try:
                server.send_text(config, text, delivery_id)
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with (
            mock.patch.object(server, "has_session", return_value=True),
            mock.patch.object(server, "agent_profile_in_pane", return_value=server.CODEX_PROFILE),
            mock.patch.object(server, "codex_composer_has_draft", return_value=False),
            mock.patch.object(server, "codex_rollout_submission_probe", return_value=None),
            mock.patch.object(server, "tmux_capture_compact", return_value="baseline"),
            mock.patch.object(server, "tmux_current_capture", return_value="› placeholder"),
            mock.patch.object(server, "tmux_cursor_position", return_value=(2, 20)),
            mock.patch.object(server, "wait_for_paste_tail", return_value=True),
            mock.patch.object(server, "codex_submission_key", return_value="Enter"),
            mock.patch.object(server, "wait_for_codex_submission", side_effect=confirmation),
            mock.patch.object(server, "tmux", return_value=self.completed),
        ):
            thread_a = threading.Thread(target=worker, args=(config_a, "message a", delivery_a))
            thread_b = threading.Thread(target=worker, args=(config_b, "message b", delivery_b))
            thread_a.start()
            self.assertTrue(entered_a.wait(1))
            thread_b.start()
            self.assertTrue(entered_b.wait(1), "session B was blocked by session A")
            release_a.set()
            thread_a.join(2)
            thread_b.join(2)

        self.assertFalse(thread_a.is_alive())
        self.assertFalse(thread_b.is_alive())
        self.assertEqual([], errors)
        self.assertEqual({}, server._send_session_locks)
        self.assertEqual({}, server._send_message_locks)

    def test_same_message_id_across_sessions_serializes_then_conflicts(self):
        config_a = server.Config("codex-same-id-a", "token", 0)
        config_b = server.Config("codex-same-id-b", "token", 0)
        delivery_id = "web-same-id"
        entered_a = threading.Event()
        release_a = threading.Event()
        errors = []

        def confirmation(config, _text, **_kwargs):
            if config.session == config_a.session:
                entered_a.set()
                release_a.wait(2)
            return "submitted"

        def worker(config):
            try:
                server.send_text(config, "same content", delivery_id)
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with (
            mock.patch.object(server, "has_session", return_value=True),
            mock.patch.object(server, "agent_profile_in_pane", return_value=server.CODEX_PROFILE),
            mock.patch.object(server, "codex_composer_has_draft", return_value=False),
            mock.patch.object(server, "codex_rollout_submission_probe", return_value=None),
            mock.patch.object(server, "tmux_capture_compact", return_value="baseline"),
            mock.patch.object(server, "tmux_current_capture", return_value="› placeholder"),
            mock.patch.object(server, "tmux_cursor_position", return_value=(2, 20)),
            mock.patch.object(server, "wait_for_paste_tail", return_value=True),
            mock.patch.object(server, "codex_submission_key", return_value="Enter"),
            mock.patch.object(server, "wait_for_codex_submission", side_effect=confirmation),
            mock.patch.object(server, "tmux", return_value=self.completed),
        ):
            thread_a = threading.Thread(target=worker, args=(config_a,))
            thread_b = threading.Thread(target=worker, args=(config_b,))
            thread_a.start()
            self.assertTrue(entered_a.wait(1))
            thread_b.start()
            time.sleep(0.05)
            self.assertTrue(thread_b.is_alive(), "same message id was not serialized")
            release_a.set()
            thread_a.join(2)
            thread_b.join(2)

        self.assertFalse(thread_a.is_alive())
        self.assertFalse(thread_b.is_alive())
        self.assertEqual(1, len(errors))
        self.assertIsInstance(errors[0], server.OwnerError)
        self.assertEqual(HTTPStatus.CONFLICT, errors[0].status)
        self.assertEqual({}, server._send_session_locks)
        self.assertEqual({}, server._send_message_locks)

    def test_accepted_client_message_id_is_idempotent(self):
        patches = self.send_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9] as tmux, patches[10]:
            first = server.send_text(self.config, "only once", "web-idempotent")
            tmux_calls = len(tmux.call_args_list)
            server._send_deliveries.clear()
            second = server.send_text(self.config, "only once", "web-idempotent")

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(tmux_calls, len(tmux.call_args_list))
        record = server.send_delivery_record_path("web-idempotent")
        self.assertTrue(record.is_file())
        self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)

    def test_expired_persisted_delivery_is_not_reused(self):
        delivery_id = "web-expired"
        digest = "0" * 64
        record = server.send_delivery_record_path(delivery_id)
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({
            "version": 1,
            "deliveryId": delivery_id,
            "session": self.config.session,
            "digest": digest,
            "status": "accepted",
            "receipt": {
                "deliveryId": delivery_id,
                "delivery": "accepted",
                "deliveryState": "recorded",
                "session": self.config.session,
                "enterAttempts": 1,
                "duplicate": False,
            },
            "updatedEpoch": 1,
        }), encoding="utf-8")

        loaded = server.load_persisted_send_delivery(delivery_id, now_epoch=server.SEND_DELIVERY_TTL_SECONDS + 2)

        self.assertIsNone(loaded)
        self.assertFalse(record.exists())

    def test_corrupt_persisted_delivery_is_ignored(self):
        record = server.send_delivery_record_path("web-corrupt")
        record.parent.mkdir(parents=True)
        record.write_text("{not-json", encoding="utf-8")

        self.assertIsNone(server.load_persisted_send_delivery("web-corrupt"))

    def test_existing_tmux_draft_is_not_overwritten(self):
        with (
            mock.patch.object(server, "has_session", return_value=True),
            mock.patch.object(server, "agent_profile_in_pane", return_value=server.CODEX_PROFILE),
            mock.patch.object(server, "codex_composer_has_draft", return_value=True),
            mock.patch.object(server, "tmux") as tmux,
        ):
            with self.assertRaises(server.OwnerError) as raised:
                server.send_text(self.config, "new browser text", "web-draft-conflict")

        self.assertEqual(HTTPStatus.CONFLICT, raised.exception.status)
        tmux.assert_not_called()


if __name__ == "__main__":
    unittest.main()
