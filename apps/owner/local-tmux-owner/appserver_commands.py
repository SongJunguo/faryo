"""Structured slash-command actions for Codex App Server sessions."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import Any, Awaitable, Callable, Mapping


class AppServerCommandError(RuntimeError):
    pass


Rpc = Callable[[str, dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class CommandChoice:
    id: str
    label: str
    description: str
    method: str = ""
    params: dict[str, Any] | None = None
    selected: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "selected": self.selected,
            "current": self.selected,
            "disabled": False,
        }


@dataclass
class PendingCommand:
    id: str
    session: str
    generation: int
    kind: str
    title: str
    prompt: str
    choices: tuple[CommandChoice, ...]
    details: dict[str, Any]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "generation": self.generation,
            "kind": self.kind,
            "title": self.title,
            "prompt": self.prompt,
            "options": [choice.public() for choice in self.choices],
            "questions": [],
            "details": dict(self.details),
            "responseKind": "choice",
            "actions": ["cancel"],
            "source": "codex-app-server",
            "status": "pending",
        }


class AppServerCommandService:
    def __init__(
        self,
        *,
        on_open: Callable[[str, dict[str, Any]], None],
        on_close: Callable[[str, str], None],
    ) -> None:
        self.on_open = on_open
        self.on_close = on_close
        self.pending: dict[str, PendingCommand] = {}
        self.generations: dict[str, int] = {}

    async def begin(
        self,
        *,
        session: str,
        thread_id: str,
        cwd: str,
        thread: Mapping[str, Any],
        command: str,
        rpc: Rpc,
    ) -> dict[str, Any]:
        if session in self.pending:
            raise AppServerCommandError("another Codex interaction is already pending")
        invocation = str(command or "").strip()
        name, _separator, argument = invocation.partition(" ")
        name = name.lower()
        argument = argument.strip()
        if name == "/fast":
            current = str(thread.get("serviceTier") or "")
            value = None if current == "fast" else "fast"
            await rpc("thread/settings/update", {"threadId": thread_id, "serviceTier": value})
            return self._resolved(session)
        if name == "/rename":
            if not argument:
                raise AppServerCommandError("/rename requires a title")
            await rpc("thread/name/set", {"threadId": thread_id, "name": argument[:240]})
            return self._resolved(session)
        if name == "/compact":
            await rpc("thread/compact/start", {"threadId": thread_id})
            return self._resolved(session)
        if name == "/model":
            models = await self._paged(rpc, "model/list", {"includeHidden": False, "limit": 100})
            if argument:
                selected = next(
                    (
                        model
                        for model in models
                        if argument in {str(model.get("id") or ""), str(model.get("model") or "")}
                    ),
                    None,
                )
                if selected is None:
                    raise AppServerCommandError("unknown Codex model")
                await rpc(
                    "thread/settings/update",
                    {"threadId": thread_id, "model": str(selected.get("model") or selected.get("id"))},
                )
                return self._resolved(session)
            current = str(thread.get("model") or "")
            choices = tuple(
                self._choice(
                    str(model.get("displayName") or model.get("id") or model.get("model") or "Model"),
                    str(model.get("description") or ""),
                    "thread/settings/update",
                    {"threadId": thread_id, "model": str(model.get("model") or model.get("id") or "")},
                    selected=current in {str(model.get("model") or ""), str(model.get("id") or "")},
                )
                for model in models
                if str(model.get("model") or model.get("id") or "")
            )
            return self._opened(session, "model_select", "Select model", "Choose the model for subsequent turns.", choices)
        if name == "/permissions":
            profiles = await self._paged(rpc, "permissionProfile/list", {"cwd": cwd, "limit": 100})
            current_profile = thread.get("activePermissionProfile")
            current = str(current_profile.get("id") or "") if isinstance(current_profile, Mapping) else ""
            if argument:
                selected = next((profile for profile in profiles if str(profile.get("id") or "") == argument), None)
                if selected is None or not selected.get("allowed", False):
                    raise AppServerCommandError("unknown or unavailable permissions profile")
                await rpc("thread/settings/update", {"threadId": thread_id, "permissions": argument})
                return self._resolved(session)
            choices = tuple(
                self._choice(
                    str(profile.get("id") or "Permissions"),
                    str(profile.get("description") or ""),
                    "thread/settings/update",
                    {"threadId": thread_id, "permissions": str(profile.get("id") or "")},
                    selected=current == str(profile.get("id") or ""),
                )
                for profile in profiles
                if profile.get("allowed", False) and str(profile.get("id") or "")
            )
            return self._opened(
                session,
                "permissions_select",
                "Select permissions",
                "Choose the official Codex permissions profile for subsequent turns.",
                choices,
            )
        if name == "/usage":
            rate_limits = await rpc("account/rateLimits/read", {})
            usage = await rpc("account/usage/read", {})
            prompt = self._usage_prompt(rate_limits, usage)
            return self._opened(
                session,
                "usage_select",
                "Usage",
                prompt,
                (self._choice("Close", "Return to the conversation."),),
            )
        if name == "/goal":
            result = await rpc("thread/goal/get", {"threadId": thread_id})
            goal = result.get("goal") if isinstance(result, Mapping) else None
            prompt = "No active goal."
            if isinstance(goal, Mapping):
                status = str(goal.get("status") or "active")
                objective = str(goal.get("objective") or "").strip()
                prompt = f"{status.title()}: {objective}" if objective else status.title()
            return self._opened(
                session,
                "goal",
                "Goal status",
                prompt,
                (self._choice("Close", "Return to the conversation."),),
            )
        raise AppServerCommandError("this Codex command is not available in Codex App Server sessions")

    async def respond(
        self,
        *,
        session: str,
        interaction_id: str,
        option_id: str,
        action: str,
        rpc: Rpc,
    ) -> dict[str, Any] | None:
        pending = self.pending.get(session)
        if pending is None or pending.id != interaction_id:
            return None
        if action == "cancel":
            self._close(pending)
            return self._resolved(session, pending.generation)
        choice = next((item for item in pending.choices if item.id == option_id), None)
        if choice is None:
            raise AppServerCommandError("unknown interaction option")
        if choice.method:
            await rpc(choice.method, dict(choice.params or {}))
        self._close(pending)
        return self._resolved(session, pending.generation)

    def _opened(
        self,
        session: str,
        kind: str,
        title: str,
        prompt: str,
        choices: tuple[CommandChoice, ...],
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not choices:
            raise AppServerCommandError("Codex returned no available choices")
        generation = self.generations.get(session, 0) + 1
        self.generations[session] = generation
        pending = PendingCommand(
            f"ascmd_{secrets.token_urlsafe(18)}",
            session,
            generation,
            kind,
            title,
            prompt,
            choices,
            details or {},
        )
        self.pending[session] = pending
        public = pending.public()
        self.on_open(session, public)
        return {
            "ok": True,
            "interaction": public,
            "interactionRevision": f"appserver:{generation}",
            "changed": True,
            "resolved": False,
            "duplicate": False,
        }

    def _close(self, pending: PendingCommand) -> None:
        self.pending.pop(pending.session, None)
        self.on_close(pending.session, pending.id)

    @staticmethod
    def _resolved(session: str, generation: int = 0) -> dict[str, Any]:
        return {
            "ok": True,
            "session": session,
            "interaction": None,
            "interactionRevision": f"appserver:{generation + 1}",
            "changed": True,
            "resolved": True,
            "duplicate": False,
        }

    @staticmethod
    def _choice(
        label: str,
        description: str,
        method: str = "",
        params: dict[str, Any] | None = None,
        *,
        selected: bool = False,
    ) -> CommandChoice:
        return CommandChoice(
            f"ascopt_{secrets.token_urlsafe(12)}",
            label,
            description,
            method,
            params,
            selected,
        )

    @staticmethod
    async def _paged(rpc: Rpc, method: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        cursor = ""
        for _page in range(8):
            request = dict(params)
            if cursor:
                request["cursor"] = cursor
            result = await rpc(method, request)
            if not isinstance(result, Mapping):
                break
            values.extend(item for item in result.get("data") or [] if isinstance(item, dict))
            cursor = str(result.get("nextCursor") or "")
            if not cursor:
                break
        return values

    @staticmethod
    def _usage_prompt(rate_limits: Any, usage: Any) -> str:
        parts: list[str] = []
        if isinstance(rate_limits, Mapping):
            snapshots = rate_limits.get("rateLimitsByLimitId")
            snapshot = snapshots.get("codex") if isinstance(snapshots, Mapping) else rate_limits.get("rateLimits")
            if isinstance(snapshot, Mapping):
                for label, key in (("Current window", "primary"), ("Weekly window", "secondary")):
                    window = snapshot.get(key)
                    if isinstance(window, Mapping) and isinstance(window.get("usedPercent"), (int, float)):
                        parts.append(f"{label}: {float(window['usedPercent']):.1f}% used")
        if isinstance(usage, Mapping):
            summary = usage.get("summary")
            if isinstance(summary, Mapping) and isinstance(summary.get("lifetimeTokens"), int):
                parts.append(f"Lifetime tokens: {int(summary['lifetimeTokens']):,}")
        return " · ".join(parts) or "Usage details are currently unavailable."
