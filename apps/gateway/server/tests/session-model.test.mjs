import assert from "node:assert/strict";
import test from "node:test";

import { sessionViewModel } from "../../ui/session-model.mjs";

test("session model preserves explicit lifecycle and safe text", () => {
  const model = sessionViewModel({
    id: "thread-a",
    title: "<unsafe>",
    route: "txy",
    routeLabel: "Workstation",
    tmuxSession: "codex",
    state: "exited",
    source: "codex-cli",
    managed: true,
    updatedAt: "now",
  });
  assert.equal(model.lifecycle, "exited");
  assert.equal(model.canReceive, false);
  assert.equal(model.title, "<unsafe>");
  assert.match(model.meta, /Codex/);
});

test("resumable limit and archived state stay distinct", () => {
  assert.equal(sessionViewModel({ state: "resumable", limitReached: true }).state, "Limit reached");
  const archived = sessionViewModel({ state: "archived", archived: true });
  assert.equal(archived.archived, true);
  assert.equal(archived.canReceive, false);
});
