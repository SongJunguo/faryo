import assert from "node:assert/strict";
import test from "node:test";

import { createCaptureController } from "../static/owner/capture-controller.mjs";

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
