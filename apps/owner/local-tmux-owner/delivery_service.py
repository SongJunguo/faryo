"""Reliable tmux delivery orchestration with explicit runtime dependencies."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from http import HTTPStatus
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from typing import Any
import uuid

import codex_command_policy


class DeliveryService:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.lock = threading.RLock()
        self.session_locks: dict[str, dict[str, Any]] = {}
        self.message_locks: dict[str, dict[str, Any]] = {}
        self.deliveries: dict[str, dict[str, Any]] = {}

    @contextmanager
    def scoped_lock(self, registry: dict[str, dict[str, Any]], key: str):
        with self.lock:
            entry = registry.setdefault(key, {"lock": threading.RLock(), "references": 0})
            entry["references"] = int(entry["references"]) + 1
            item_lock = entry["lock"]
        try:
            with item_lock:
                yield
        finally:
            with self.lock:
                entry["references"] = int(entry["references"]) - 1
                if entry["references"] == 0 and registry.get(key) is entry:
                    registry.pop(key, None)

    def session_lock(self, session: str):
        return self.scoped_lock(self.session_locks, session)

    def message_lock(self, delivery_id: str):
        return self.scoped_lock(self.message_locks, delivery_id)

    def record_path(self, delivery_id: str) -> Path | None:
        return self.runtime.delivery_store.record_path(delivery_id)

    def cleanup_persisted(self, now_epoch: float | None = None, *, force: bool = False) -> None:
        self.runtime.delivery_store.cleanup(now_epoch, force=force)

    def persist(self, delivery_id: str, state: dict[str, Any]) -> bool:
        return self.runtime.delivery_store.persist(delivery_id, state)

    def load(self, delivery_id: str, now_epoch: float | None = None) -> dict[str, Any] | None:
        return self.runtime.delivery_store.load(delivery_id, now_epoch)

    def remember_accepted(self, delivery_id: str, state: dict[str, Any]) -> None:
        state["updatedAt"] = time.monotonic()
        state["updatedEpoch"] = time.time()
        self.deliveries[delivery_id] = state
        self.persist(delivery_id, state)

    def remember_pasted(self, delivery_id: str, state: dict[str, Any]) -> None:
        state["updatedAt"] = time.monotonic()
        state["updatedEpoch"] = time.time()
        self.deliveries[delivery_id] = state
        self.persist(delivery_id, state)

    def prune(self, now: float | None = None) -> None:
        with self.lock:
            cutoff = (now if now is not None else time.monotonic()) - self.runtime.delivery_ttl_seconds
            for delivery_id in [
                key
                for key, value in self.deliveries.items()
                if float(value.get("updatedAt") or 0) < cutoff
            ]:
                self.deliveries.pop(delivery_id, None)
            self.cleanup_persisted()

    @staticmethod
    def receipt(
        delivery_id: str,
        config: Any,
        state: str,
        enter_attempts: int,
        *,
        duplicate: bool = False,
    ) -> dict[str, Any]:
        return {
            "deliveryId": delivery_id,
            "delivery": "accepted",
            "deliveryState": state,
            "session": config.session,
            "enterAttempts": enter_attempts,
            "duplicate": duplicate,
        }

    def send(self, config: Any, text: str, client_message_id: str | None = None) -> dict[str, Any]:
        runtime = self.runtime
        if not runtime.has_session(config):
            raise runtime.owner_error(f"tmux session not found: {config.session}", HTTPStatus.NOT_FOUND)
        if not text.strip():
            raise runtime.owner_error("empty text")
        if len(text) > runtime.max_send_chars:
            raise runtime.owner_error(
                f"text too long: {len(text)} > {runtime.max_send_chars}",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        if client_message_id and not runtime.clean_client_message_id(client_message_id):
            raise runtime.owner_error("invalid client message id")
        delivery_id = runtime.clean_client_message_id(client_message_id) or uuid.uuid4().hex
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        line = text.strip()
        if codex_command_policy.command_invocation(line):
            raise runtime.owner_error(
                "exact Codex slash commands require the structured interaction endpoint",
                HTTPStatus.CONFLICT,
            )
        words = line.split()
        launch_command = Path(words[0]).name.lower() if words else ""
        shell_prep = bool(
            words
            and (
                launch_command in runtime.agent_launch_commands
                or runtime.shell_prep_matches(line)
            )
        )
        with self.session_lock(config.session), self.message_lock(delivery_id):
            now = time.monotonic()
            self.prune(now)
            existing = self.deliveries.get(delivery_id) or self.load(delivery_id)
            if existing and delivery_id not in self.deliveries:
                self.deliveries[delivery_id] = existing
            if existing and (
                existing.get("session") != config.session
                or existing.get("digest") != digest
            ):
                raise runtime.owner_error(
                    "client message id was already used for different content",
                    HTTPStatus.CONFLICT,
                )
            if existing and existing.get("status") == "accepted":
                receipt = dict(existing["receipt"])
                receipt["duplicate"] = True
                existing["updatedAt"] = now
                existing["updatedEpoch"] = time.time()
                self.persist(delivery_id, existing)
                return receipt

            if shell_prep and not runtime.agent_in_pane(config):
                for keys in (["-l", line], ["Enter"]):
                    result = runtime.tmux(
                        config,
                        ["send-keys", "-t", runtime.tmux_target(config), *keys],
                        timeout=3,
                    )
                    if result.returncode != 0:
                        raise runtime.owner_error(
                            result.stderr.strip() or "tmux send shell prep failed",
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                receipt = self.receipt(delivery_id, config, "shell", 1)
                self.remember_accepted(delivery_id, {
                    "session": config.session,
                    "digest": digest,
                    "status": "accepted",
                    "receipt": receipt,
                })
                return receipt

            profile = runtime.agent_profile_in_pane(config)
            continuing_paste = bool(existing and existing.get("status") == "pasted")
            if (
                runtime.is_codex_profile(profile)
                and not continuing_paste
                and runtime.codex_composer_has_draft(config)
            ):
                raise runtime.owner_error(
                    "Codex TUI already has an unsent draft; the browser draft was kept",
                    HTTPStatus.CONFLICT,
                )
            fresh_rollout_probe = (
                runtime.codex_rollout_submission_probe(config)
                if runtime.is_codex_profile(profile)
                else None
            )
            rollout_probe = (
                runtime.codex_rollout_probe_from_state(config, existing)
                if runtime.is_codex_profile(profile) and continuing_paste and existing
                else fresh_rollout_probe
            )
            if runtime.is_codex_profile(profile) and rollout_probe is None:
                rollout_probe = fresh_rollout_probe
            queued_baseline = (
                max(0, int(existing.get("queuedBaseline") or 0))
                if continuing_paste and existing
                else 0
            )

            if not continuing_paste:
                buffer_name = f"local-tmux-owner-{secrets.token_hex(4)}"
                tmp_path: str | None = None
                try:
                    baseline = runtime.tmux_capture_compact(config)
                    baseline_cursor = runtime.tmux_cursor_position(config)
                    queued_baseline = (
                        runtime.codex_queued_followup_count(
                            runtime.tmux_current_capture(config),
                            text,
                        )
                        if runtime.is_codex_profile(profile)
                        else 0
                    )
                    with tempfile.NamedTemporaryFile(
                        "w",
                        encoding="utf-8",
                        delete=False,
                        prefix="local-tmux-owner-",
                        suffix=".txt",
                    ) as tmp:
                        tmp.write(text)
                        tmp_path = tmp.name
                    result = runtime.tmux(
                        config,
                        ["load-buffer", "-b", buffer_name, tmp_path],
                        timeout=3,
                    )
                    if result.returncode != 0:
                        raise runtime.owner_error(
                            result.stderr.strip() or "tmux load-buffer failed",
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                    paste_args = [
                        "paste-buffer",
                        "-d",
                        "-r",
                        "-b",
                        buffer_name,
                        "-t",
                        runtime.tmux_target(config),
                    ]
                    paste_args.insert(2, "-p")
                    result = runtime.tmux(config, paste_args, timeout=3)
                    if result.returncode != 0:
                        raise runtime.owner_error(
                            result.stderr.strip() or "tmux paste-buffer failed",
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                    paste_ready = runtime.wait_for_paste_tail(
                        config,
                        text,
                        baseline,
                        baseline_cursor,
                    )
                    if not paste_ready:
                        raise runtime.owner_error(
                            "text paste could not be confirmed; the browser draft was kept",
                            HTTPStatus.GATEWAY_TIMEOUT,
                        )
                    pasted_state = {
                        "session": config.session,
                        "digest": digest,
                        "status": "pasted",
                        "pasteReady": True,
                        "queuedBaseline": queued_baseline,
                        **runtime.codex_rollout_probe_state(rollout_probe),
                    }
                    self.remember_pasted(delivery_id, pasted_state)
                finally:
                    if tmp_path:
                        try:
                            os.unlink(tmp_path)
                        except FileNotFoundError:
                            pass
                    runtime.tmux(config, ["delete-buffer", "-b", buffer_name], timeout=1)
                runtime.sleep(runtime.paste_settle_seconds)
            elif (
                runtime.is_codex_profile(profile)
                and not runtime.codex_composer_contains_text(config, text)
            ):
                recovered_state = runtime.wait_for_codex_submission(
                    config,
                    text,
                    timeout=0.35,
                    rollout_probe=rollout_probe,
                    queued_baseline=queued_baseline,
                    allow_composer_disappearance=False,
                )
                if not recovered_state:
                    existing["updatedAt"] = time.monotonic()
                    existing["updatedEpoch"] = time.time()
                    self.persist(delivery_id, existing)
                    raise runtime.owner_error(
                        "previous delivery is still ambiguous; no rollout or new queue evidence was found and nothing was sent again",
                        HTTPStatus.GATEWAY_TIMEOUT,
                    )
                receipt = self.receipt(delivery_id, config, recovered_state, 0)
                existing.update({"status": "accepted", "receipt": receipt})
                self.remember_accepted(delivery_id, existing)
                return receipt

            enter_attempts = 0
            accepted_state: str | None = None
            key_attempts = (
                runtime.send_key_max_attempts
                if runtime.is_codex_profile(profile)
                else 1
            )
            for _attempt in range(key_attempts):
                enter_attempts += 1
                key = (
                    runtime.codex_submission_key(config)
                    if runtime.is_codex_profile(profile)
                    else "C-m"
                )
                result = runtime.tmux(
                    config,
                    ["send-keys", "-t", runtime.tmux_target(config), key],
                    timeout=3,
                )
                if result.returncode != 0:
                    raise runtime.owner_error(
                        result.stderr.strip() or f"tmux send {key} failed",
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                if runtime.is_codex_profile(profile):
                    accepted_state = runtime.wait_for_codex_submission(
                        config,
                        text,
                        rollout_probe=rollout_probe,
                        queued_baseline=queued_baseline,
                        allow_composer_disappearance=key != "Tab",
                    )
                    if accepted_state:
                        break
                    runtime.sleep(runtime.send_accept_retry_delay)
                else:
                    accepted_state = "sent"
                    break

            if not accepted_state:
                state = self.deliveries[delivery_id]
                state["updatedAt"] = time.monotonic()
                state["updatedEpoch"] = time.time()
                self.persist(delivery_id, state)
                raise runtime.owner_error(
                    "Codex did not accept the submit key; the browser and TUI drafts were kept for retry",
                    HTTPStatus.GATEWAY_TIMEOUT,
                )

            receipt = self.receipt(delivery_id, config, accepted_state, enter_attempts)
            self.remember_accepted(delivery_id, {
                "session": config.session,
                "digest": digest,
                "status": "accepted",
                "receipt": receipt,
            })
            return receipt
