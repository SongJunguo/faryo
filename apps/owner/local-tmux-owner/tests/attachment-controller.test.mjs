import assert from "node:assert/strict";
import test from "node:test";

import {
  attachmentLabel,
  isImageFile,
  jpegName,
  settleWithConcurrency,
  selectedAttachmentFiles,
} from "../static/owner/attachment-controller.mjs";

test("attachment type and labels remain filename safe", () => {
  assert.equal(isImageFile({ type: "image/png", name: "fixture.bin" }), true);
  assert.equal(isImageFile({ type: "", name: "fixture.HEIC" }), true);
  assert.equal(isImageFile({ type: "text/plain", name: "fixture.txt" }), false);
  assert.equal(attachmentLabel({ name: "paper.pdf" }), "PDF");
  assert.equal(attachmentLabel({ name: "README" }), "FILE");
  assert.equal(jpegName("figure.png"), "figure.jpg");
});

test("selection respects the remaining attachment budget", () => {
  const files = Array.from({ length: 40 }, (_value, index) => ({ name: String(index) }));
  assert.deepEqual(selectedAttachmentFiles(files, 33, 35), files.slice(0, 2));
  assert.deepEqual(selectedAttachmentFiles(files, 35, 35), []);
  assert.equal(selectedAttachmentFiles(files, 0, 35).length, 35);
});

test("large attachment batches keep at most four uploads active", async () => {
  let active = 0;
  let maximumActive = 0;
  const results = await settleWithConcurrency(
    Array.from({ length: 35 }, (_value, index) => index),
    4,
    async (value) => {
      active += 1;
      maximumActive = Math.max(maximumActive, active);
      await new Promise((resolve) => setTimeout(resolve, 1));
      active -= 1;
      return value * 2;
    },
  );
  assert.equal(maximumActive, 4);
  assert.equal(results.length, 35);
  assert.equal(results.every((item) => item.status === "fulfilled"), true);
});
