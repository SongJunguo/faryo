import sys
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import server


class SendDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.config = server.Config("codex-send-test", "token", 145)
        server._send_deliveries.clear()
        self.completed = mock.Mock(returncode=0, stdout="", stderr="")

    def tearDown(self):
        server._send_deliveries.clear()

    def send_patches(self, *, composer_states=None, submission_states=None):
        return (
            mock.patch.object(server, "has_session", return_value=True),
            mock.patch.object(server, "agent_profile_in_pane", return_value=server.CODEX_PROFILE),
            mock.patch.object(server, "codex_composer_has_draft", side_effect=composer_states or [False]),
            mock.patch.object(server, "tmux_capture_compact", return_value="baseline"),
            mock.patch.object(server, "tmux_cursor_position", return_value=(2, 20)),
            mock.patch.object(server, "wait_for_paste_tail", return_value=True),
            mock.patch.object(server, "wait_for_codex_submission", side_effect=submission_states or ["submitted"]),
            mock.patch.object(server, "tmux", return_value=self.completed),
            mock.patch.object(server.time, "sleep"),
        )

    def test_wait_for_paste_tail_accepts_observed_cursor_change(self):
        with (
            mock.patch.object(server, "tmux_capture_compact", return_value="unchanged"),
            mock.patch.object(server, "tmux_cursor_position", return_value=(18, 20)),
        ):
            ready = server.wait_for_paste_tail(self.config, "hello world", "unchanged", (2, 20))

        self.assertTrue(ready)

    def test_rollout_confirmation_uses_only_new_exact_user_message(self):
        import json
        import tempfile

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

    def test_retries_enter_until_codex_confirms_submission(self):
        patches = self.send_patches(submission_states=[None, "submitted"])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7] as tmux, patches[8]:
            receipt = server.send_text(self.config, "hello", "web-retry-enter")

        enter_keys = [call.args[1][-1] for call in tmux.call_args_list if call.args[1][:3] == ["send-keys", "-t", self.config.session]]
        self.assertEqual(["C-m", "Enter"], enter_keys)
        self.assertEqual("accepted", receipt["delivery"])
        self.assertEqual("submitted", receipt["deliveryState"])
        self.assertEqual(2, receipt["enterAttempts"])

    def test_retry_after_timeout_does_not_paste_the_message_twice(self):
        patches = self.send_patches(composer_states=[False, True], submission_states=[None, None, "submitted"])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7] as tmux, patches[8]:
            with self.assertRaises(server.OwnerError) as raised:
                server.send_text(self.config, "keep this draft", "web-timeout-retry")
            receipt = server.send_text(self.config, "keep this draft", "web-timeout-retry")

        self.assertEqual(HTTPStatus.GATEWAY_TIMEOUT, raised.exception.status)
        paste_calls = [call for call in tmux.call_args_list if call.args[1] and call.args[1][0] == "paste-buffer"]
        self.assertEqual(1, len(paste_calls))
        self.assertEqual("accepted", receipt["delivery"])
        self.assertEqual(1, receipt["enterAttempts"])

    def test_accepted_client_message_id_is_idempotent(self):
        patches = self.send_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7] as tmux, patches[8]:
            first = server.send_text(self.config, "only once", "web-idempotent")
            tmux_calls = len(tmux.call_args_list)
            second = server.send_text(self.config, "only once", "web-idempotent")

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(tmux_calls, len(tmux.call_args_list))

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
