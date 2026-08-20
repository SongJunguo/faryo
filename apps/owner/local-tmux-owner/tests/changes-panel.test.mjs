import assert from "node:assert/strict";
import test from "node:test";

import { diffReviewAssetPath, workspaceSummaryText } from "../static/owner/changes-panel.mjs";

test("workspace summary stays bounded and explicit", () => {
  assert.equal(
    workspaceSummaryText({ files: 4, staged: 1, unstaged: 2, untracked: 1, diffTruncated: true }),
    "4 files · 1 staged · 2 unstaged · 1 untracked · diff truncated",
  );
  assert.equal(workspaceSummaryText(), "0 files · 0 staged · 0 unstaged · 0 untracked");
});

test("diff review assets remain route-local", () => {
  assert.equal(diffReviewAssetPath("", "bundle.js"), "/vendor/diff-review/bundle.js");
  assert.equal(diffReviewAssetPath("/txy", "bundle.js"), "/txy/vendor/diff-review/bundle.js");
});
