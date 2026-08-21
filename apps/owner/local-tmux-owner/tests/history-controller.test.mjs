import assert from "node:assert/strict";
import test from "node:test";

import { createHistoryController, emptyConversationHistory, isStructuredCapture } from "../static/owner/history-controller.mjs";

function fixture(overrides = {}) {
  const output = { querySelectorAll: () => [] };
  const view = {
    AbortController,
    clearTimeout,
    setTimeout,
  };
  const controller = createHistoryController({
    view,
    output,
    scroller: { scrollTop: 0 },
    api: async () => ({
      revision: "rev-a",
      totalTurns: 3,
      start: 0,
      olderCursor: "older-a",
      questions: [{ key: "q0", preview: "First" }, { key: "q1", preview: "Second" }, { key: "q2", preview: "Third" }],
      turns: [{ index: 0, key: "q0", text: "› First\n\n• Answer" }, { index: 2, key: "q2", text: "› Third\n\n• Answer" }],
    }),
    apiPath: (path) => path,
    getSelectedSession: () => "codex",
    getExpectedSessionId: (fallback) => fallback || "thread-a",
    getLastCapture: () => null,
    getOutputMode: () => "compact",
    renderCapture() {},
    anchorSnapshot: () => null,
    restoreAnchor() {},
    isInitialLatestPending: () => false,
    applyInitialLatestScroll() {},
    beginInitialLatestScroll() {},
    cancelInitialLatestScroll() {},
    isNearBottom: () => true,
    scrollBottom() {},
    setError() {},
    userErrorMessage: (error) => error.message,
    handleBackgroundError() {},
    ...overrides,
  });
  return controller;
}

test("history state starts private and empty", () => {
  const state = emptyConversationHistory();
  assert.equal(state.initialized, false);
  assert.equal(state.turns.size, 0);
  assert.deepEqual(state.questions, []);
});

test("history pages merge intact turns and expose unloaded gaps", async () => {
  const controller = fixture();
  await controller.load({ latest: true });

  assert.equal(controller.initialized, true);
  assert.equal(controller.totalTurns, 3);
  assert.equal(controller.questions.length, 3);
  assert.equal(controller.loadedTurns().length, 2);
  const merged = controller.mergedCapture({ captureSource: "codex-jsonl", sessionId: "thread-a", text: "tail" });
  assert.match(merged.text, /First/);
  assert.match(merged.text, /1 earlier turn not loaded/);
  assert.equal(merged.historyTotalTurns, 3);
});

test("revision changes replace stale turn state", () => {
  const controller = fixture();
  controller.mergePage({ revision: "rev-a", totalTurns: 1, start: 0, turns: [{ index: 0, text: "old" }] }, "thread-a");
  controller.mergePage({ revision: "rev-b", totalTurns: 1, start: 0, turns: [{ index: 0, text: "new" }] }, "thread-a");
  assert.equal(controller.loadedTurns()[0].text, "new");
});

test("structured capture detection stays source-specific", () => {
  assert.equal(isStructuredCapture({ captureSource: "codex-jsonl" }), true);
  assert.equal(isStructuredCapture({ captureSource: "codex-app-server" }), true);
  assert.equal(isStructuredCapture({ captureSource: "codex-empty" }), true);
  assert.equal(isStructuredCapture({ captureSource: "tmux" }), false);
});
