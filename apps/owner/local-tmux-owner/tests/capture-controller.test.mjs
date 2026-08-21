import assert from "node:assert/strict";
import test from "node:test";

import { createCaptureController } from "../static/owner/capture-controller.mjs";

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const eventParser = { createParser: () => ({ push() {} }) };

function fixture(overrides = {}) {
  const states = [];
  const captures = [];
  const view = {
    AbortController,
    ReadableStream,
    TextDecoder,
    clearInterval,
    clearTimeout,
    setInterval,
    setTimeout,
  };
  const controller = createCaptureController({
    view,
    compactLines: 320,
    fullLines: 800,
    fetchTimeoutMs: 1000,
    fullRefreshMs: 1000,
    fallbackRefreshMs: 1000,
    currentLines: () => 320,
    getOutputMode: () => "compact",
    isHidden: () => false,
    setError() {},
    setLiveState: (state) => states.push(state),
    loadCapture: async (lines) => ({ ok: true, text: String(lines) }),
    onCapture: (capture, meta) => captures.push([capture, meta]),
    handleBackgroundError() {},
    refreshStatusIfVisible() {},
    fetch: async () => ({ ok: false, status: 503 }),
    eventUrl: () => "/api/events",
    ownerHeaders: () => ({}),
    eventStreamParser: null,
    ...overrides,
  });
  return { controller, states, captures };
}

test("capture refresh applies the newest successful payload", async () => {
  const { controller, captures } = fixture();
  await controller.refresh(800);
  assert.equal(captures.length, 1);
  assert.equal(captures[0][0].text, "800");
  assert.equal(captures[0][1].source, "refresh");
});

test("refresh cancellation ignores a late payload", async () => {
  let resolveCapture;
  const { controller, captures } = fixture({
    loadCapture: () => new Promise((resolve) => { resolveCapture = resolve; }),
  });
  const pending = controller.refresh(320);
  controller.cancelRefresh();
  resolveCapture({ ok: true, text: "late" });
  await pending;
  assert.deepEqual(captures, []);
});

test("a response from an obsolete conversation scope is rejected", async () => {
  let resolveCapture;
  let scope = { session: "alpha", generation: 1, mode: "compact" };
  const { controller, captures } = fixture({
    getScope: () => ({ ...scope }),
    acceptScope: (candidate) =>
      candidate.session === scope.session &&
      candidate.generation === scope.generation &&
      candidate.mode === scope.mode,
    loadCapture: () => new Promise((resolve) => { resolveCapture = resolve; }),
  });
  const pending = controller.refresh(320);
  scope = { session: "beta", generation: 2, mode: "compact" };
  resolveCapture({ ok: true, text: "obsolete" });
  await pending;
  assert.deepEqual(captures, []);
});

test("an event from an obsolete conversation scope is rejected", async (context) => {
  let applyEvent = null;
  let scope = { session: "alpha", generation: 1, mode: "compact" };
  const { controller, captures } = fixture({
    getScope: () => ({ ...scope }),
    acceptScope: (candidate) =>
      candidate.session === scope.session &&
      candidate.generation === scope.generation &&
      candidate.mode === scope.mode,
    eventIdleTimeoutMs: 1000,
    eventStreamParser: {
      createParser(callback) {
        applyEvent = callback;
        return { push() {} };
      },
    },
    fetch: async () => ({
      ok: true,
      status: 200,
      body: new ReadableStream({
        start(stream) {
          stream.enqueue(new TextEncoder().encode(": opened\n\n"));
        },
      }),
    }),
  });
  context.after(() => controller.closeEventStream());
  controller.startEventStream();
  await delay(0);
  scope = { session: "beta", generation: 2, mode: "compact" };
  applyEvent({
    type: "capture",
    data: JSON.stringify({ ok: true, text: "obsolete event" }),
  });
  assert.deepEqual(captures, []);
});

test("a buffered event from a closed stream cannot update the conversation", async () => {
  let applyEvent = null;
  const { controller, captures } = fixture({
    eventIdleTimeoutMs: 1000,
    eventStreamParser: {
      createParser(callback) {
        applyEvent = callback;
        return { push() {} };
      },
    },
    fetch: async () => ({
      ok: true,
      status: 200,
      body: new ReadableStream({
        start(stream) {
          stream.enqueue(new TextEncoder().encode(": opened\n\n"));
        },
      }),
    }),
  });

  controller.startEventStream();
  await delay(0);
  controller.closeEventStream();
  applyEvent({
    type: "capture",
    data: JSON.stringify({ ok: true, text: "late event" }),
  });

  assert.deepEqual(captures, []);
});

test("missing streaming support selects the polling fallback", () => {
  const intervals = [];
  const { controller, states } = fixture({
    view: {
      AbortController,
      ReadableStream: null,
      TextDecoder,
      clearInterval() {},
      clearTimeout,
      setInterval: (callback, delay) => { intervals.push([callback, delay]); return 1; },
      setTimeout,
    },
  });
  controller.startEventStream();
  assert.equal(states.at(-1), "fallback");
  assert.equal(intervals.length, 1);
  controller.setFallback(false);
});

test("an apparently open stream with no heartbeat falls back and reconnects", async (context) => {
  let fetchCalls = 0;
  const { controller, states } = fixture({
    eventIdleTimeoutMs: 20,
    eventRetryInitialMs: 10,
    fallbackRefreshMs: 10,
    safetyRefreshMs: 1000,
    eventStreamParser: eventParser,
    fetch: async () => {
      fetchCalls += 1;
      return {
        ok: true,
        status: 200,
        body: new ReadableStream({
          start(stream) {
            stream.enqueue(new TextEncoder().encode(": opened\n\n"));
          },
        }),
      };
    },
  });
  context.after(() => {
    controller.closeEventStream();
    controller.setFallback(false);
  });

  controller.startEventStream();
  await delay(85);

  assert.ok(fetchCalls >= 2, `expected a reconnect, saw ${fetchCalls} stream request(s)`);
  assert.ok(states.includes("live"));
  assert.ok(states.filter((state) => state === "reconnecting").length >= 2);
});

test("stream heartbeats prevent a false idle reconnect", async (context) => {
  let fetchCalls = 0;
  let heartbeatTimer = null;
  const { controller } = fixture({
    eventIdleTimeoutMs: 25,
    eventRetryInitialMs: 10,
    safetyRefreshMs: 1000,
    eventStreamParser: eventParser,
    fetch: async () => {
      fetchCalls += 1;
      return {
        ok: true,
        status: 200,
        body: new ReadableStream({
          start(stream) {
            stream.enqueue(new TextEncoder().encode(": opened\n\n"));
            heartbeatTimer = setInterval(() => {
              stream.enqueue(new TextEncoder().encode(": keepalive\n\n"));
            }, 8);
          },
          cancel() {
            if (heartbeatTimer) clearInterval(heartbeatTimer);
          },
        }),
      };
    },
  });
  context.after(() => {
    controller.closeEventStream();
    if (heartbeatTimer) clearInterval(heartbeatTimer);
  });

  controller.startEventStream();
  await delay(70);

  assert.equal(fetchCalls, 1);
});

test("a live stream retains deduplicated capture polling as a safety net", async (context) => {
  let refreshCalls = 0;
  const { controller, states, captures } = fixture({
    eventIdleTimeoutMs: 1000,
    safetyRefreshMs: 12,
    eventStreamParser: eventParser,
    loadCapture: async () => {
      refreshCalls += 1;
      return { ok: true, text: "safety" };
    },
    fetch: async () => ({
      ok: true,
      status: 200,
      body: new ReadableStream({
        start(stream) {
          stream.enqueue(new TextEncoder().encode(": opened\n\n"));
        },
      }),
    }),
  });
  context.after(() => controller.closeEventStream());

  controller.startEventStream();
  await delay(45);

  assert.equal(states.at(-1), "live");
  assert.ok(refreshCalls >= 2, `expected safety refreshes, saw ${refreshCalls}`);
  assert.equal(captures.length, 1, "unchanged safety payloads should not rerender the conversation");
});

test("a delayed safety response cannot replace a newer event frame", async (context) => {
  let applyEvent = null;
  let resolveSafety = null;
  const { controller, captures } = fixture({
    eventIdleTimeoutMs: 1000,
    safetyRefreshMs: 1000,
    eventStreamParser: {
      createParser(callback) {
        applyEvent = callback;
        return { push() {} };
      },
    },
    loadCapture: () => new Promise((resolve) => { resolveSafety = resolve; }),
    fetch: async (_url, init) => {
      let streamController = null;
      const body = new ReadableStream({
        start(stream) {
          streamController = stream;
          stream.enqueue(new TextEncoder().encode(": opened\n\n"));
        },
      });
      init.signal.addEventListener("abort", () => {
        const error = new Error("aborted");
        error.name = "AbortError";
        streamController.error(error);
      }, { once: true });
      return { ok: true, status: 200, body };
    },
  });
  context.after(() => controller.closeEventStream());

  controller.startEventStream();
  await delay(0);
  const pendingSafety = controller.refresh(320, { silent: true, safety: true });
  applyEvent({ type: "capture", data: JSON.stringify({ ok: true, text: "new" }) });
  resolveSafety({ ok: true, text: "old" });
  await pendingSafety;

  assert.deepEqual(captures.map(([capture]) => capture.text), ["new"]);
});
