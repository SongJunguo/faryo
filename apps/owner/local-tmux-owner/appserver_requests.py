"""Fail-closed browser interactions for Codex App Server requests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import re
import secrets
import time
from typing import Any, Callable, Mapping


CLIENT_REQUEST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
APPROVAL_METHODS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
    "execCommandApproval",
    "applyPatchApproval",
}
USER_INPUT_METHOD = "item/tool/requestUserInput"


class AppServerInteractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class InteractionChoice:
    public_id: str
    label: str
    description: str
    response: dict[str, Any]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.public_id,
            "label": self.label,
            "description": self.description,
            "selected": False,
            "current": False,
            "disabled": False,
        }


@dataclass
class PendingAppServerInteraction:
    id: str
    session: str
    method: str
    thread_id: str
    turn_id: str
    item_id: str
    generation: int
    kind: str
    title: str
    prompt: str
    response_kind: str
    choices: tuple[InteractionChoice, ...] = ()
    questions: tuple[dict[str, Any], ...] = ()
    details: dict[str, Any] = field(default_factory=dict)
    future: asyncio.Future[dict[str, Any]] | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "generation": self.generation,
            "kind": self.kind,
            "title": self.title,
            "prompt": self.prompt,
            "options": [choice.public() for choice in self.choices],
            "questions": [dict(question) for question in self.questions],
            "details": dict(self.details),
            "responseKind": self.response_kind,
            "actions": ["cancel"],
            "source": "codex-app-server",
            "status": "pending",
        }


def declined_response(method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if method in {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
    }:
        return {"decision": "decline"}
    if method == "item/permissions/requestApproval":
        return {"permissions": {}, "scope": "turn"}
    if method == USER_INPUT_METHOD:
        answers: dict[str, Any] = {}
        for question in (params or {}).get("questions") or []:
            if isinstance(question, Mapping) and isinstance(question.get("id"), str):
                answers[str(question["id"])] = {"answers": []}
        return {"answers": answers}
    if method in {"execCommandApproval", "applyPatchApproval"}:
        return {"decision": "denied"}
    return {}


class AppServerInteractionBroker:
    """Own pending server requests without persisting message bodies."""

    def __init__(
        self,
        *,
        on_open: Callable[[str, dict[str, Any]], None],
        on_close: Callable[[str, str], None],
        receipt_ttl: float = 48 * 60 * 60,
    ) -> None:
        self.on_open = on_open
        self.on_close = on_close
        self.receipt_ttl = receipt_ttl
        self.pending_by_session: dict[str, PendingAppServerInteraction] = {}
        self.pending_by_id: dict[str, PendingAppServerInteraction] = {}
        self.generations: dict[str, int] = {}
        self.receipts: dict[str, dict[str, Any]] = {}

    async def request(self, session: str, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        if session in self.pending_by_session:
            return declined_response(method, params)
        pending = self._build(session, method, params)
        if pending is None:
            return declined_response(method, params)
        pending.future = asyncio.get_running_loop().create_future()
        self.pending_by_session[session] = pending
        self.pending_by_id[pending.id] = pending
        self.on_open(session, pending.public())
        try:
            return await pending.future
        except asyncio.CancelledError:
            if pending.future is not None and not pending.future.done():
                pending.future.cancel()
            raise
        finally:
            self.pending_by_session.pop(session, None)
            self.pending_by_id.pop(pending.id, None)
            self.on_close(session, pending.id)

    def snapshot(self, session: str) -> dict[str, Any] | None:
        pending = self.pending_by_session.get(session)
        return pending.public() if pending is not None else None

    def respond(
        self,
        session: str,
        *,
        interaction_id: str,
        option_id: str = "",
        answers: Mapping[str, Any] | None = None,
        client_request_id: str,
    ) -> dict[str, Any]:
        self._prune_receipts()
        request_id = str(client_request_id or "").strip()
        if not CLIENT_REQUEST_RE.fullmatch(request_id):
            raise AppServerInteractionError("invalid client request id")
        identity = (session, interaction_id, option_id, self._normalized_answers(answers))
        existing = self.receipts.get(request_id)
        if existing is not None:
            if existing["identity"] != identity:
                raise AppServerInteractionError("client request id was already used for another interaction")
            return {**existing["result"], "duplicate": True}

        pending = self.pending_by_id.get(interaction_id)
        if pending is None or pending.session != session:
            raise AppServerInteractionError("interaction is no longer current")
        if pending.future is None or pending.future.done():
            raise AppServerInteractionError("interaction is already resolved")

        if pending.response_kind == "questions":
            result = self._question_response(pending, answers or {})
        else:
            choice = next((item for item in pending.choices if item.public_id == option_id), None)
            if choice is None:
                raise AppServerInteractionError("unknown interaction option")
            result = dict(choice.response)
        pending.future.set_result(result)
        response = {
            "ok": True,
            "requestId": request_id,
            "interaction": None,
            "interactionRevision": f"appserver:{pending.generation + 1}",
            "changed": True,
            "resolved": True,
            "duplicate": False,
        }
        self.receipts[request_id] = {
            "identity": identity,
            "result": dict(response),
            "updatedAt": time.monotonic(),
        }
        return response

    def cancel(self, session: str, *, client_request_id: str) -> dict[str, Any]:
        pending = self.pending_by_session.get(session)
        if pending is None:
            raise AppServerInteractionError("interaction is no longer current")
        cancel_choice = next(
            (
                choice
                for choice in pending.choices
                if choice.response.get("decision") in {"cancel", "decline", "denied"}
            ),
            None,
        )
        if pending.response_kind == "questions":
            answers = {question["id"]: [] for question in pending.questions}
            return self.respond(
                session,
                interaction_id=pending.id,
                answers=answers,
                client_request_id=client_request_id,
            )
        if cancel_choice is None:
            raise AppServerInteractionError("interaction cannot be cancelled")
        return self.respond(
            session,
            interaction_id=pending.id,
            option_id=cancel_choice.public_id,
            client_request_id=client_request_id,
        )

    def _build(
        self,
        session: str,
        method: str,
        params: Mapping[str, Any],
    ) -> PendingAppServerInteraction | None:
        thread_id = str(params.get("threadId") or "")
        turn_id = str(params.get("turnId") or "")
        item_id = str(params.get("itemId") or params.get("callId") or "")
        if not thread_id and method not in {"execCommandApproval", "applyPatchApproval"}:
            return None
        generation = self.generations.get(session, 0) + 1
        self.generations[session] = generation
        interaction_id = f"asix_{secrets.token_urlsafe(18)}"

        if method == "item/commandExecution/requestApproval":
            command = str(params.get("command") or "")
            cwd = str(params.get("cwd") or "")
            reason = str(params.get("reason") or "")
            available = params.get("availableDecisions")
            allowed = {
                str(value)
                for value in available
                if isinstance(value, str)
            } if isinstance(available, list) else {"accept", "acceptForSession", "decline", "cancel"}
            choices = self._approval_choices(allowed)
            return PendingAppServerInteraction(
                interaction_id, session, method, thread_id, turn_id, item_id, generation,
                "approval", "Allow this command?", reason or "Codex needs permission to run a command.",
                "choice", choices=choices, details={"command": command, "cwd": cwd},
            )
        if method == "item/fileChange/requestApproval":
            reason = str(params.get("reason") or "")
            grant_root = str(params.get("grantRoot") or "")
            return PendingAppServerInteraction(
                interaction_id, session, method, thread_id, turn_id, item_id, generation,
                "approval", "Allow file changes?", reason or "Codex needs permission to modify files.",
                "choice", choices=self._approval_choices({"accept", "acceptForSession", "decline", "cancel"}),
                details={"path": grant_root},
            )
        if method == "item/permissions/requestApproval":
            permissions = params.get("permissions") if isinstance(params.get("permissions"), Mapping) else {}
            reason = str(params.get("reason") or "")
            choices = (
                self._choice("Allow once", "Grant the requested permissions for this turn.", {"permissions": dict(permissions), "scope": "turn"}),
                self._choice("Allow for session", "Grant the requested permissions for this session.", {"permissions": dict(permissions), "scope": "session"}),
                self._choice("Decline", "Continue without the requested permissions.", {"permissions": {}, "scope": "turn"}),
            )
            return PendingAppServerInteraction(
                interaction_id, session, method, thread_id, turn_id, item_id, generation,
                "approval", "Allow additional permissions?", reason or "Codex requested additional sandbox permissions.",
                "choice", choices=choices, details={"cwd": str(params.get("cwd") or ""), "permissions": dict(permissions)},
            )
        if method == USER_INPUT_METHOD:
            questions = self._questions(params.get("questions"))
            if not questions:
                return None
            return PendingAppServerInteraction(
                interaction_id, session, method, thread_id, turn_id, item_id, generation,
                "user_input", "Codex needs your input", "Answer the questions to continue this turn.",
                "questions", questions=questions,
            )
        if method in {"execCommandApproval", "applyPatchApproval"}:
            details = {
                "command": " ".join(str(value) for value in params.get("command") or [])
                if isinstance(params.get("command"), list)
                else "",
                "path": str(params.get("grantRoot") or ""),
            }
            choices = (
                self._choice("Allow once", "Approve this legacy Codex request.", {"decision": "approved"}),
                self._choice("Decline", "Do not approve this request.", {"decision": "denied"}),
            )
            return PendingAppServerInteraction(
                interaction_id, session, method, thread_id, turn_id, item_id, generation,
                "approval", "Allow this Codex action?", str(params.get("reason") or "Approval is required."),
                "choice", choices=choices, details=details,
            )
        return None

    def _approval_choices(self, allowed: set[str]) -> tuple[InteractionChoice, ...]:
        values = []
        definitions = (
            ("accept", "Allow once", "Approve this action once."),
            ("acceptForSession", "Allow for session", "Approve matching actions for this session."),
            ("decline", "Decline", "Do not approve this action; let Codex continue."),
            ("cancel", "Decline and stop", "Decline this action and interrupt the turn."),
        )
        for decision, label, description in definitions:
            if decision in allowed:
                values.append(self._choice(label, description, {"decision": decision}))
        if not values:
            values.append(self._choice("Decline", "Do not approve this action.", {"decision": "decline"}))
        return tuple(values)

    @staticmethod
    def _choice(label: str, description: str, response: dict[str, Any]) -> InteractionChoice:
        return InteractionChoice(f"asopt_{secrets.token_urlsafe(12)}", label, description, response)

    @staticmethod
    def _questions(value: Any) -> tuple[dict[str, Any], ...]:
        questions: list[dict[str, Any]] = []
        if not isinstance(value, list):
            return ()
        for raw in value:
            if not isinstance(raw, Mapping):
                continue
            question_id = str(raw.get("id") or "")
            question = str(raw.get("question") or "")
            if not question_id or not question:
                continue
            options = []
            for option in raw.get("options") or []:
                if isinstance(option, Mapping) and str(option.get("label") or ""):
                    options.append({
                        "label": str(option.get("label")),
                        "description": str(option.get("description") or ""),
                    })
            questions.append({
                "id": question_id,
                "header": str(raw.get("header") or "Question"),
                "question": question,
                "options": options,
                "isOther": bool(raw.get("isOther", True)),
                "isSecret": bool(raw.get("isSecret", False)),
            })
        return tuple(questions)

    @staticmethod
    def _normalized_answers(value: Mapping[str, Any] | None) -> tuple[tuple[str, tuple[str, ...]], ...]:
        normalized = []
        for key, raw in (value or {}).items():
            answers = raw if isinstance(raw, list) else [raw]
            normalized.append((str(key), tuple(str(answer) for answer in answers if isinstance(answer, str))))
        return tuple(sorted(normalized))

    @staticmethod
    def _question_response(
        pending: PendingAppServerInteraction,
        submitted: Mapping[str, Any],
    ) -> dict[str, Any]:
        answers: dict[str, Any] = {}
        for question in pending.questions:
            question_id = str(question["id"])
            raw = submitted.get(question_id, [])
            values = raw if isinstance(raw, list) else [raw]
            answers[question_id] = {
                "answers": [str(value) for value in values if isinstance(value, str) and value.strip()]
            }
        return {"answers": answers}

    def _prune_receipts(self) -> None:
        cutoff = time.monotonic() - self.receipt_ttl
        for key in [key for key, value in self.receipts.items() if value["updatedAt"] < cutoff]:
            self.receipts.pop(key, None)
