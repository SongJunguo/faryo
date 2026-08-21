from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import unittest

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from appserver_events import EventJournal
from appserver_capabilities import inspect_schema_directory
from appserver_history import conversation_history_page
from appserver_protocol import (
    AppServerProtocolError,
    AppServerUnavailable,
    ProtocolMessageKind,
    decode_wire_message,
    parse_codex_version,
)
from appserver_session import WebSessionActor
from appserver_transport import AsyncCodexAppServerClient


class FakeSocket:
    def __init__(self, *, reject_experimental: bool = False) -> None:
        self.incoming: asyncio.Queue[str | BaseException] = asyncio.Queue()
        self.sent: list[dict] = []
        self.closed = False
        self.reject_experimental = reject_experimental

    async def send(self, message: str) -> None:
        body = json.loads(message)
        self.sent.append(body)
        if body.get("method") == "initialize" and "id" in body:
            capabilities = (body.get("params") or {}).get("capabilities")
            if self.reject_experimental and isinstance(capabilities, dict):
                await self.incoming.put(json.dumps({
                    "id": body["id"],
                    "error": {"code": -32602, "message": "unsupported capability"},
                }))
            else:
                await self.incoming.put(json.dumps({"id": body["id"], "result": {"userAgent": "test/0"}}))

    async def recv(self) -> str:
        value = await self.incoming.get()
        if isinstance(value, BaseException):
            raise value
        return value

    async def close(self) -> None:
        self.closed = True


class ProtocolTest(unittest.TestCase):
    def test_classifies_all_bidirectional_shapes(self) -> None:
        self.assertEqual(decode_wire_message('{"id":1,"result":{}}').kind, ProtocolMessageKind.RESPONSE)
        self.assertEqual(
            decode_wire_message('{"id":1,"error":{"code":-1,"message":"no"}}').kind,
            ProtocolMessageKind.ERROR,
        )
        self.assertEqual(
            decode_wire_message('{"method":"item/started","params":{}}').kind,
            ProtocolMessageKind.NOTIFICATION,
        )
        self.assertEqual(
            decode_wire_message('{"id":7,"method":"item/requestApproval","params":{}}').kind,
            ProtocolMessageKind.SERVER_REQUEST,
        )
        with self.assertRaises(AppServerProtocolError):
            decode_wire_message("[]")

    def test_parses_codex_cli_version_without_freezing_launcher_path(self) -> None:
        self.assertEqual(parse_codex_version("codex-cli 0.149.0"), "0.149.0")
        self.assertEqual(parse_codex_version("unrecognized"), "")

    def test_schema_probe_reports_missing_methods_without_crashing(self) -> None:
        with self.subTest("missing files"):
            report = inspect_schema_directory(Path(__file__).parent / "fixtures/not-present")
            self.assertFalse(report.compatible)
            self.assertEqual(len(report.errors), 2)

    def test_fixture_delta_and_final_converge_to_one_item(self) -> None:
        actor = WebSessionActor(session_id="session_demo", thread_id="thread_demo")
        fixture = Path(__file__).parent / "fixtures/appserver-0.149.0.jsonl"
        kinds: list[str] = []
        for line in fixture.read_text(encoding="utf-8").splitlines()[1:]:
            message = json.loads(line)
            kinds.extend(event.kind for event in actor.apply(message["method"], message.get("params") or {}))
        self.assertIn("item.delta", kinds)
        self.assertIn("item.final", kinds)
        self.assertEqual(actor.item_order, ["item_demo"])
        item = actor.items["item_demo"]
        self.assertEqual(item.text, "Hello $x^2$.")
        self.assertTrue(item.final)
        self.assertEqual(actor.lifecycle, "idle")

    def test_tool_activity_is_bounded_and_hidden_reasoning_is_not_exposed(self) -> None:
        actor = WebSessionActor(session_id="session_demo", thread_id="thread_demo")
        actor.apply(
            "turn/started",
            {"threadId": "thread_demo", "turn": {"id": "turn_demo", "status": "inProgress"}},
        )
        actor.apply(
            "item/started",
            {
                "threadId": "thread_demo",
                "turnId": "turn_demo",
                "item": {
                    "id": "command_demo",
                    "type": "commandExecution",
                    "command": "python -m pytest",
                    "status": "inProgress",
                },
            },
        )
        actor.apply(
            "item/completed",
            {
                "threadId": "thread_demo",
                "turnId": "turn_demo",
                "item": {
                    "id": "command_demo",
                    "type": "commandExecution",
                    "command": "python -m pytest",
                    "status": "completed",
                    "exitCode": 0,
                    "aggregatedOutput": "private command output is not projected",
                },
            },
        )
        actor.apply(
            "item/completed",
            {
                "threadId": "thread_demo",
                "turnId": "turn_demo",
                "item": {
                    "id": "reasoning_demo",
                    "type": "reasoning",
                    "text": "hidden reasoning body",
                },
            },
        )
        actor.apply(
            "item/completed",
            {
                "threadId": "thread_demo",
                "turnId": "turn_demo",
                "item": {
                    "id": "change_demo",
                    "type": "fileChange",
                    "status": "completed",
                    "changes": [{"path": "/workspace/src/app.py", "kind": "update", "diff": "private diff"}],
                },
            },
        )
        messages = actor.messages()
        rendered = "\n".join(text for _role, text in messages)

        self.assertIn(("process", "Ran python -m pytest · exit 0"), messages)
        self.assertIn(("process", "Working"), messages)
        self.assertIn(("process", "Edited app.py"), messages)
        self.assertNotIn("hidden reasoning body", rendered)
        self.assertNotIn("private command output", rendered)
        self.assertNotIn("private diff", rendered)

    def test_event_journal_replay_gap_reset_and_byte_bound(self) -> None:
        journal = EventJournal(max_events=3, max_bytes=800, epoch="epoch")
        first = journal.publish(session_id="s", thread_id="t", kind="one", payload={"n": 1})
        journal.publish(session_id="s", thread_id="t", kind="two", payload={"n": 2})
        third = journal.publish(session_id="s", thread_id="t", kind="three", payload={"n": 3})
        self.assertEqual([event.kind for event in journal.replay(first.id).events], ["two", "three"])
        self.assertEqual(journal.replay(third.id).status, "replay")
        self.assertEqual(journal.replay("other:1").status, "reset")
        for number in range(4, 12):
            journal.publish(session_id="s", thread_id="t", kind="next", payload={"n": number})
        self.assertLessEqual(len(tuple(journal)), 3)
        self.assertLessEqual(journal.total_bytes, 800)
        self.assertEqual(journal.replay(first.id).status, "gap")

    def test_live_snapshot_history_pages_until_jsonl_becomes_authoritative(self) -> None:
        snapshot = {
            "revision": 999,
            "turns": [
                {
                    "id": f"turn_{index}",
                    "status": "completed",
                    "items": [
                        {
                            "id": f"user_{index}",
                            "type": "userMessage",
                            "content": [{"type": "text", "text": f"Question {index}"}],
                        },
                        {"id": f"answer_{index}", "type": "agentMessage", "text": f"Answer {index}"},
                    ],
                }
                for index in range(30)
            ],
        }
        options = {
            "thread_id": "thread_demo",
            "limit": 5,
            "max_page_turns": 24,
            "page_char_budget": 100_000,
            "preview_chars": 80,
            "updated_at": lambda: "now",
        }
        latest = conversation_history_page(snapshot, **options)
        older = conversation_history_page(snapshot, cursor=latest["olderCursor"], **options)
        around = conversation_history_page(snapshot, around=3, **options)

        self.assertEqual(latest["source"], "codex-app-server")
        self.assertEqual(latest["totalTurns"], 30)
        self.assertEqual([turn["index"] for turn in latest["turns"]], [25, 26, 27, 28, 29])
        self.assertEqual([turn["index"] for turn in older["turns"]], [20, 21, 22, 23, 24])
        self.assertIn("Question 3", around["turns"][3 - around["start"]]["text"])
        self.assertEqual(len(latest["questions"]), 30)


class TransportTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.socket = FakeSocket()
        self.notifications: list[tuple[str, dict]] = []

        async def connector():
            return self.socket

        async def notification(method: str, params: dict) -> None:
            self.notifications.append((method, params))

        self.client = AsyncCodexAppServerClient(
            connector=connector,
            client_version="test",
            notification_handler=notification,
            rpc_timeout=0.5,
            random_value=lambda: 0.5,
        )
        await self.client.connect()

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_notification_between_request_and_response_is_not_dropped(self) -> None:
        task = asyncio.create_task(self.client.rpc("thread/read", {"threadId": "thread_demo"}))
        await asyncio.sleep(0)
        request = self.socket.sent[-1]
        await self.socket.incoming.put(json.dumps({"method": "turn/started", "params": {"threadId": "thread_demo"}}))
        await self.socket.incoming.put(json.dumps({"id": request["id"], "result": {"thread": {"id": "thread_demo"}}}))
        result = await task
        await asyncio.sleep(0)
        self.assertEqual(result["thread"]["id"], "thread_demo")
        self.assertEqual(self.notifications[0][0], "turn/started")

    async def test_initialize_retries_without_experimental_capability_when_rejected(self) -> None:
        socket = FakeSocket(reject_experimental=True)

        async def connector():
            return socket

        client = AsyncCodexAppServerClient(
            connector=connector,
            client_version="test",
            rpc_timeout=0.5,
        )
        try:
            result = await client.connect()
            initialize = [message for message in socket.sent if message.get("method") == "initialize"]
            self.assertEqual(result, {"userAgent": "test/0"})
            self.assertEqual(len(initialize), 2)
            self.assertEqual(initialize[0]["params"]["capabilities"], {"experimentalApi": True})
            self.assertIsNone(initialize[1]["params"]["capabilities"])
            self.assertFalse(client.experimental_api)
        finally:
            await client.close()

    async def test_server_request_is_answered_and_unknown_request_fails_closed(self) -> None:
        self.client.register_server_request("item/requestApproval", lambda params: {"decision": "decline"})
        await self.socket.incoming.put(json.dumps({"id": "srv-1", "method": "item/requestApproval", "params": {}}))
        await self.socket.incoming.put(json.dumps({"id": "srv-2", "method": "future/request", "params": {}}))
        for _attempt in range(20):
            if any(message.get("id") == "srv-2" for message in self.socket.sent):
                break
            await asyncio.sleep(0.01)
        supported = next(message for message in self.socket.sent if message.get("id") == "srv-1")
        unknown = next(message for message in self.socket.sent if message.get("id") == "srv-2")
        self.assertEqual(supported["result"], {"decision": "decline"})
        self.assertEqual(unknown["error"]["code"], -32601)

    async def test_overload_response_retries_only_after_explicit_rejection(self) -> None:
        task = asyncio.create_task(self.client.rpc("thread/read", {}, overload_attempts=2))
        await asyncio.sleep(0)
        first = self.socket.sent[-1]
        await self.socket.incoming.put(json.dumps({
            "id": first["id"],
            "error": {"code": -32001, "message": "Server overloaded; retry later."},
        }))
        for _attempt in range(50):
            requests = [message for message in self.socket.sent if message.get("method") == "thread/read"]
            if len(requests) == 2:
                break
            await asyncio.sleep(0.01)
        second = requests[-1]
        await self.socket.incoming.put(json.dumps({"id": second["id"], "result": {"ok": True}}))
        self.assertEqual(await task, {"ok": True})

    async def test_disconnect_fails_pending_request(self) -> None:
        task = asyncio.create_task(self.client.rpc("thread/read", {}))
        await asyncio.sleep(0)
        await self.socket.incoming.put(ConnectionError("lost"))
        with self.assertRaises(AppServerUnavailable):
            await task
        self.assertFalse(self.client.ready)
        self.assertEqual(self.client.pending_count, 0)

    async def test_slow_notification_consumer_disconnects_instead_of_unbounded_buffering(self) -> None:
        socket = FakeSocket()
        release = asyncio.Event()
        disconnected = asyncio.Event()

        async def connector():
            return socket

        async def slow_notification(_method: str, _params: dict) -> None:
            await release.wait()

        async def on_disconnect(_error: BaseException) -> None:
            disconnected.set()

        client = AsyncCodexAppServerClient(
            connector=connector,
            client_version="test",
            notification_handler=slow_notification,
            disconnect_handler=on_disconnect,
            notification_queue_size=1,
            rpc_timeout=0.5,
        )
        await client.connect()
        await socket.incoming.put(json.dumps({"method": "one", "params": {}}))
        await asyncio.sleep(0)
        await socket.incoming.put(json.dumps({"method": "two", "params": {}}))
        await socket.incoming.put(json.dumps({"method": "three", "params": {}}))
        await asyncio.wait_for(disconnected.wait(), timeout=0.5)
        release.set()
        await client.close()

        self.assertFalse(client.ready)
        self.assertLessEqual(client._notification_queue.qsize(), 1)


if __name__ == "__main__":
    unittest.main()
