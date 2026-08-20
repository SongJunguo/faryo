import assert from "node:assert/strict";
import test from "node:test";

import { createComposerDelivery, isAmbiguousDeliveryError } from "../static/owner/composer-delivery.mjs";

class Storage {
  constructor() { this.values = new Map(); }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}

function fixture(overrides = {}) {
  const storage = new Storage();
  const attempts = [];
  let id = 0;
  const controller = createComposerDelivery({
    storage,
    routeKey: "/lab",
    getSession: () => "codex",
    crypto: { randomUUID: () => `id-${++id}` },
    AbortController,
    setTimeout: (callback, delay) => delay === 180 ? (callback(), 1) : setTimeout(callback, delay),
    clearTimeout,
    timeoutMs: 1000,
    sendAction: async (payload) => { attempts.push(payload); return { ok: true }; },
    ...overrides,
  });
  return { controller, storage, attempts };
}

test("draft restore stays scoped to route and session", () => {
  const { controller } = fixture();
  controller.persistDraft("codex", "draft-a");
  assert.equal(controller.restore("codex").inputValue, "draft-a");
  assert.equal(controller.restore("other").inputValue, "");
  assert.match(controller.draftKey("codex"), /^faryoPromptDraft:\/lab:codex$/);
});

test("identical pending content reuses its message ID", () => {
  const { controller } = fixture();
  const values = { session: "codex", browserText: "hello", outboundText: "hello", attachmentPaths: [] };
  const first = controller.prepareSubmission(values);
  const second = controller.prepareSubmission(values);
  const changed = controller.prepareSubmission({ ...values, outboundText: "changed" });
  assert.equal(second.id, first.id);
  assert.notEqual(changed.id, first.id);
});

test("editing the composer discards only the stale pending checkpoint", () => {
  const { controller, storage } = fixture();
  controller.prepareSubmission({
    session: "codex",
    browserText: "old",
    outboundText: "old",
    attachmentPaths: [],
  });
  assert.equal(controller.discardPendingIfChanged("new", "codex"), true);
  assert.equal(controller.pendingSubmission, null);
  assert.equal(storage.getItem(controller.pendingKey("codex")), null);
});

test("success clears only matching draft and pending state", () => {
  const { controller, storage } = fixture();
  const submission = controller.prepareSubmission({
    session: "codex",
    browserText: "hello",
    outboundText: "hello",
    attachmentPaths: [],
  });
  controller.persistDraft("codex", "hello");
  controller.clearDeliveredDraft(submission);
  controller.clearPending(submission);
  assert.equal(storage.getItem(controller.draftKey("codex")), null);
  assert.equal(storage.getItem(controller.pendingKey("codex")), null);
  assert.equal(controller.pendingSubmission, null);
});

test("failed delivery restores draft and checkpoint", () => {
  const { controller, storage } = fixture();
  const submission = controller.prepareSubmission({
    session: "codex",
    browserText: "keep me",
    outboundText: "keep me",
    attachmentPaths: [],
  });
  storage.removeItem(controller.draftKey("codex"));
  controller.preserveFailedDraft(submission);
  assert.equal(storage.getItem(controller.draftKey("codex")), "keep me");
  assert.ok(storage.getItem(controller.pendingKey("codex")));
});

test("ambiguous failure retries once with the same payload", async () => {
  let calls = 0;
  let checking = 0;
  const { controller } = fixture({
    sendAction: async (payload) => {
      calls += 1;
      if (calls === 1) {
        const error = new Error("ambiguous");
        error.status = 504;
        throw error;
      }
      return payload;
    },
    onChecking: () => { checking += 1; },
  });
  const payload = { session: "codex", text: "hello", clientMessageId: "web-id" };
  assert.deepEqual(await controller.send(payload), payload);
  assert.equal(calls, 2);
  assert.equal(checking, 1);
  assert.equal(isAmbiguousDeliveryError({ status: 400 }), false);
});
