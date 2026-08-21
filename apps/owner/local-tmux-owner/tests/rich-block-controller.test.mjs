import assert from "node:assert/strict";
import test from "node:test";

import {
  createRichBlockController,
  estimatedBlockHeight,
  isRapidScroll,
  shouldRenderEagerly,
} from "../static/owner/rich-block-controller.mjs";

function createHarness(options = {}) {
  const frames = new Map();
  const timers = new Map();
  const listeners = new Map();
  let installedObserver = null;
  let nextFrame = 1;
  let nextTimer = 1;
  let now = 0;
  let rendered = 0;
  let selectionActive = false;
  let scrollTop = Number(options.scrollTop || 0);

  class FakeIntersectionObserver {
    constructor(callback) {
      this.callback = callback;
      installedObserver = this;
    }
    observe() {}
    unobserve() {}
    disconnect() {}
    trigger(target, isIntersecting) {
      this.callback([{ target, isIntersecting }]);
    }
  }

  const style = {
    blockSize: "",
    removeProperty(name) {
      if (name === "block-size") this.blockSize = "";
    },
  };
  const node = {
    ownerDocument: {
      createElement: () => ({ className: "", setAttribute() {} }),
    },
    dataset: {},
    style,
    isConnected: true,
    nextElementSibling: null,
    height: Number(options.height || 120),
    replaceChildren(...children) {
      this.children = children;
    },
    setAttribute(name, value) {
      this[name] = value;
    },
    removeAttribute(name) {
      delete this[name];
    },
    getBoundingClientRect() {
      const top = Number(options.top ?? 40);
      return { top, bottom: top + this.height, height: this.height };
    },
  };
  const scroller = {
    get scrollTop() {
      return scrollTop;
    },
    set scrollTop(value) {
      scrollTop = Number(value);
      if (options.emitProgrammaticScroll) listeners.get("scroll")?.();
    },
    scrollHeight: Number(options.scrollHeight || 3000),
    clientHeight: Number(options.clientHeight || 500),
    getBoundingClientRect: () => ({ top: 0 }),
    addEventListener(name, callback) {
      listeners.set(name, callback);
    },
    removeEventListener(name, callback) {
      if (listeners.get(name) === callback) listeners.delete(name);
    },
  };
  const view = {
    IntersectionObserver: FakeIntersectionObserver,
    performance: { now: () => now },
    requestAnimationFrame(callback) {
      const id = nextFrame++;
      frames.set(id, callback);
      return id;
    },
    cancelAnimationFrame(id) {
      frames.delete(id);
    },
    setTimeout(callback) {
      const id = nextTimer++;
      timers.set(id, callback);
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    getSelection() {
      return selectionActive
        ? {
            isCollapsed: false,
            rangeCount: 1,
            getRangeAt: () => ({ intersectsNode: () => true }),
          }
        : { isCollapsed: true, rangeCount: 0 };
    },
  };
  const controller = createRichBlockController({
    view,
    scroller,
    observerRoot: {},
    releaseDelayMs: options.releaseDelayMs,
    scrollIdleMs: options.scrollIdleMs,
    renderBlock(target) {
      rendered += 1;
      target.height = Number(options.renderHeight || 240);
      target.replaceChildren({ className: "rendered" });
      if (options.nativeAnchorTop !== undefined) {
        scrollTop = Number(options.nativeAnchorTop);
      }
    },
  });

  function runScheduled(collection, fromEnd = false) {
    const ids = [...collection.keys()];
    const id = fromEnd ? ids.at(-1) : ids[0];
    assert.ok(id, "expected scheduled work");
    const callback = collection.get(id);
    collection.delete(id);
    callback();
  }

  return {
    controller,
    frames,
    listeners,
    node,
    observer: installedObserver,
    scroller,
    timers,
    dispatchScroll() {
      listeners.get("scroll")?.();
    },
    runNextFrame() {
      runScheduled(frames);
    },
    runFirstTimer() {
      runScheduled(timers);
    },
    runLastTimer() {
      runScheduled(timers, true);
    },
    setNow(value) {
      now = Number(value);
    },
    setScrollTop(value) {
      scrollTop = Number(value);
    },
    setSelection(value) {
      selectionActive = Boolean(value);
    },
    get rendered() {
      return rendered;
    },
  };
}

test("rich block estimates stay bounded and keep the newest tail eager", () => {
  assert.equal(estimatedBlockHeight("short", "user"), 52);
  assert.ok(estimatedBlockHeight("line\n".repeat(80), "output") > 1000);
  assert.equal(estimatedBlockHeight("x".repeat(100000), "output"), 2400);
  assert.equal(shouldRenderEagerly(11, 20, 8), false);
  assert.equal(shouldRenderEagerly(12, 20, 8), true);
  assert.equal(isRapidScroll(20, 16), false);
  assert.equal(isRapidScroll(220, 100), true);
  assert.equal(isRapidScroll(64, 20), true);
});

test("rapid scrolling defers hydration until the viewport settles", () => {
  const harness = createHarness({
    top: 20,
    renderHeight: 220,
    scrollIdleMs: 80,
  });
  harness.controller.prepare(harness.node, {
    signature: "rapid-answer",
    kind: "output",
    text: "A long answer",
  });

  harness.setNow(10);
  harness.setScrollTop(420);
  harness.dispatchScroll();
  harness.observer.trigger(harness.node, true);
  assert.equal(harness.controller.rapidScrolling, true);
  assert.equal(harness.frames.size, 0);
  assert.equal(harness.rendered, 0);

  harness.runLastTimer();
  harness.runNextFrame();
  assert.equal(harness.controller.rapidScrolling, false);
  assert.equal(harness.rendered, 1);

  harness.observer.trigger(harness.node, false);
  harness.controller.clear();
  harness.controller.destroy();
  assert.equal(harness.listeners.size, 0);
});

test("hydrating the first block keeps an explicit top position", () => {
  const harness = createHarness({
    top: 0,
    renderHeight: 1800,
    nativeAnchorTop: 900,
  });
  harness.controller.prepare(harness.node, {
    signature: "first-answer",
    kind: "output",
    text: "A very long first answer",
  });

  harness.observer.trigger(harness.node, true);
  harness.runNextFrame();

  assert.equal(harness.node.dataset.faryoRichState, "rendered");
  assert.equal(harness.scroller.scrollTop, 0);
  harness.controller.destroy();
});

test("programmatic anchor correction is not treated as reader scrolling", () => {
  const harness = createHarness({
    top: -20,
    scrollTop: 300,
    renderHeight: 340,
    emitProgrammaticScroll: true,
  });
  harness.controller.prepare(harness.node, {
    signature: "anchor-answer",
    kind: "output",
    text: "An answer above the viewport",
  });

  harness.observer.trigger(harness.node, true);
  harness.runNextFrame();

  assert.equal(harness.scroller.scrollTop, 520);
  assert.equal(harness.controller.rapidScrolling, false);
  harness.controller.destroy();
});

test("offscreen rich blocks release their DOM and hydrate again on demand", () => {
  const harness = createHarness({ releaseDelayMs: 1, renderHeight: 240 });
  harness.controller.prepare(harness.node, {
    signature: "answer-a",
    kind: "output",
    text: "A long answer",
  });
  assert.equal(harness.node.dataset.faryoRichState, "deferred");
  assert.equal(harness.controller.pendingCount, 1);

  harness.observer.trigger(harness.node, true);
  harness.runNextFrame();
  assert.equal(harness.rendered, 1);
  assert.equal(harness.node.dataset.faryoRichState, "rendered");

  harness.observer.trigger(harness.node, false);
  harness.runFirstTimer();
  assert.equal(harness.node.dataset.faryoRichState, "deferred");
  assert.equal(harness.node.style.blockSize, "240px");

  harness.controller.ensure(harness.node);
  assert.equal(harness.rendered, 2);
  assert.equal(harness.node.dataset.faryoRichState, "rendered");

  harness.controller.prepare(
    harness.node,
    {
      signature: "answer-a",
      kind: "output",
      text: "A long answer",
    },
    { eager: true },
  );
  harness.observer.trigger(harness.node, false);
  harness.controller.setTailPinned(false);
  harness.setSelection(true);
  harness.runFirstTimer();
  assert.equal(harness.node.dataset.faryoRichState, "rendered");
  harness.setSelection(false);
  harness.runFirstTimer();
  assert.equal(harness.node.dataset.faryoRichState, "deferred");
});
