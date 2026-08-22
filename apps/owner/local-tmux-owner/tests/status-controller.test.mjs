import assert from "node:assert/strict";
import test from "node:test";

import { createStatusController } from "../static/owner/status-controller.mjs";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function fixture(overrides = {}) {
  const statuses = [];
  const errors = [];
  let scope = { session: "alpha", generation: 1 };
  const controller = createStatusController({
    view: { AbortController, clearTimeout, setTimeout },
    timeoutMs: 1000,
    getScope: () => ({ ...scope }),
    acceptScope: (candidate) =>
      candidate.session === scope.session &&
      candidate.generation === scope.generation,
    loadStatus: async () => ({ ok: true, session: scope.session }),
    onStatus: (status, meta) => statuses.push([status, meta]),
    setError: (message) => errors.push(message),
    ...overrides,
  });
  return {
    controller,
    errors,
    statuses,
    setScope(next) {
      scope = { ...next };
    },
  };
}

test("status refresh delivers the current session snapshot", async () => {
  const { controller, errors, statuses } = fixture();
  const status = await controller.refresh();

  assert.equal(status.session, "alpha");
  assert.equal(statuses.length, 1);
  assert.equal(statuses[0][1].scope.generation, 1);
  assert.deepEqual(errors, [""]);
  assert.equal(controller.refreshInFlight, false);
});

test("a late status response cannot overwrite a different session", async () => {
  const request = deferred();
  const state = fixture({ loadStatus: () => request.promise });

  const pending = state.controller.refresh({ silent: true });
  state.setScope({ session: "beta", generation: 2 });
  request.resolve({ ok: true, session: "alpha" });

  assert.equal(await pending, null);
  assert.deepEqual(state.statuses, []);
});

test("cancel aborts and rejects a late status response", async () => {
  const request = deferred();
  let signal;
  const state = fixture({
    loadStatus: (candidate) => {
      signal = candidate;
      return request.promise;
    },
  });

  const pending = state.controller.refresh({ silent: true });
  state.controller.cancel();
  assert.equal(signal.aborted, true);
  request.resolve({ ok: true, session: "alpha" });

  assert.equal(await pending, null);
  assert.deepEqual(state.statuses, []);
  assert.equal(state.controller.refreshInFlight, false);
});

test("concurrent refreshes coalesce behind the active request", async () => {
  const request = deferred();
  let calls = 0;
  const state = fixture({
    loadStatus: () => {
      calls += 1;
      return request.promise;
    },
  });

  const first = state.controller.refresh({ silent: true });
  assert.equal(await state.controller.refresh({ silent: true }), null);
  assert.equal(calls, 1);
  request.resolve({ ok: true, session: "alpha" });
  await first;

  assert.equal(state.statuses.length, 1);
  assert.equal(state.controller.refreshInFlight, false);
});

test("an aborted status request is a quiet timeout", async () => {
  const state = fixture({
    timeoutMs: 5,
    loadStatus: (_signal) =>
      new Promise((_resolve, reject) => {
        _signal.addEventListener("abort", () => {
          const error = new Error("aborted");
          error.name = "AbortError";
          reject(error);
        });
      }),
  });

  assert.equal(await state.controller.refresh({ silent: true }), null);
  assert.deepEqual(state.statuses, []);
  assert.equal(state.controller.refreshInFlight, false);
});
