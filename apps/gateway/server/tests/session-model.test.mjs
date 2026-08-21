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
  const blocked = sessionViewModel({
    state: "resumable",
    limitReached: true,
    source: "codex-cli",
  });
  assert.equal(blocked.state, "Limit reached");
  assert.equal(blocked.canChooseFolder, true);
  assert.equal(blocked.chooseFolderDisabled, true);
  const archived = sessionViewModel({ state: "archived", archived: true });
  assert.equal(archived.archived, true);
  assert.equal(archived.canReceive, false);
  assert.equal(archived.canChooseFolder, false);
});

test("folder choice belongs only to inactive resumable Codex sessions", () => {
  const resumable = sessionViewModel({
    id: "thread-a",
    state: "resumable",
    source: "codex-cli",
  });
  assert.equal(resumable.canChooseFolder, true);
  assert.equal(resumable.chooseFolderDisabled, false);
  assert.equal(
    sessionViewModel({
      id: "thread-a",
      state: "waiting",
      source: "codex-cli",
      tmuxSession: "faryo1",
    }).canChooseFolder,
    false,
  );
  assert.equal(
    sessionViewModel({ state: "resumable", source: "other" })
      .canChooseFolder,
    false,
  );
});
