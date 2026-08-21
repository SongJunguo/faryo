import assert from "node:assert/strict";
import test from "node:test";

import {
  createRichBlockController,
  estimatedBlockHeight,
  shouldRenderEagerly,
} from "../static/owner/rich-block-controller.mjs";

test("rich block estimates stay bounded and keep the newest tail eager", () => {
  assert.equal(estimatedBlockHeight("short", "user"), 52);
  assert.ok(estimatedBlockHeight("line\n".repeat(80), "output") > 1000);
  assert.equal(estimatedBlockHeight("x".repeat(100000), "output"), 2400);
  assert.equal(shouldRenderEagerly(11, 20, 8), false);
  assert.equal(shouldRenderEagerly(12, 20, 8), true);
});

test("offscreen rich blocks release their DOM and hydrate again on demand", () => {
  const frames = [];
  const timers = [];
  const observers = [];
  let selectionActive = false;
  class FakeIntersectionObserver {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe() {}
    unobserve() {}
    disconnect() {}
    trigger(target, isIntersecting) { this.callback([{ target, isIntersecting }]); }
  }
  const document = {
    createElement() {
      return {
        className: "",
        setAttribute() {},
      };
    },
  };
  const style = {
    blockSize: "",
    removeProperty(name) { if (name === "block-size") this.blockSize = ""; },
  };
  const node = {
    ownerDocument: document,
    dataset: {},
    style,
    isConnected: true,
    nextElementSibling: null,
    height: 120,
    replaceChildren(...children) { this.children = children; },
    setAttribute(name, value) { this[name] = value; },
    removeAttribute(name) { delete this[name]; },
    getBoundingClientRect() { return { top: 40, bottom: 40 + this.height, height: this.height }; },
  };
  let rendered = 0;
  const view = {
    IntersectionObserver: FakeIntersectionObserver,
    requestAnimationFrame(callback) { frames.push(callback); return frames.length; },
    cancelAnimationFrame() {},
    setTimeout(callback) { timers.push(callback); return timers.length; },
    clearTimeout() {},
    getSelection() {
      return selectionActive
        ? { isCollapsed: false, rangeCount: 1, getRangeAt: () => ({ intersectsNode: () => true }) }
        : { isCollapsed: true, rangeCount: 0 };
    },
  };
  const controller = createRichBlockController({
    view,
    scroller: {
      scrollTop: 0,
      scrollHeight: 1000,
      clientHeight: 400,
      getBoundingClientRect: () => ({ top: 0 }),
    },
    observerRoot: {},
    releaseDelayMs: 1,
    renderBlock(target) {
      rendered += 1;
      target.height = 240;
      target.replaceChildren({ className: "rendered" });
    },
  });

  controller.prepare(node, {
    signature: "answer-a",
    kind: "output",
    text: "A long answer",
  });
  assert.equal(node.dataset.faryoRichState, "deferred");
  assert.equal(controller.pendingCount, 1);

  observers[0].trigger(node, true);
  frames.shift()();
  assert.equal(rendered, 1);
  assert.equal(node.dataset.faryoRichState, "rendered");

  observers[0].trigger(node, false);
  timers.shift()();
  assert.equal(node.dataset.faryoRichState, "deferred");
  assert.equal(node.style.blockSize, "240px");

  controller.ensure(node);
  assert.equal(rendered, 2);
  assert.equal(node.dataset.faryoRichState, "rendered");

  controller.prepare(node, {
    signature: "answer-a",
    kind: "output",
    text: "A long answer",
  }, { eager: true });
  observers[0].trigger(node, false);
  controller.setTailPinned(false);
  selectionActive = true;
  timers.shift()();
  assert.equal(node.dataset.faryoRichState, "rendered");
  selectionActive = false;
  timers.shift()();
  assert.equal(node.dataset.faryoRichState, "deferred");
});
