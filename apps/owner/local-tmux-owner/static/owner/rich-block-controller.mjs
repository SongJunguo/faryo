const DEFAULT_EAGER_TAIL = 2;
const DEFAULT_ROOT_MARGIN = "1200px 0px";
const DEFAULT_RELEASE_DELAY_MS = 700;

export function estimatedBlockHeight(text, kind = "output") {
  const source = String(text || "");
  const explicitLines = source ? source.split("\n").length : 1;
  const wrapWidth = kind === "user" ? 54 : 82;
  const wrappedLines = Math.ceil(Array.from(source).length / wrapWidth);
  const visualLines = Math.max(explicitLines, wrappedLines);
  const lineHeight = kind === "user" ? 22 : 25;
  const minimum = kind === "user" ? 52 : 92;
  const maximum = kind === "user" ? 360 : 2400;
  return Math.max(minimum, Math.min(maximum, 30 + visualLines * lineHeight));
}

export function shouldRenderEagerly(index, total, eagerTail = DEFAULT_EAGER_TAIL) {
  const count = Math.max(1, Number(eagerTail) || DEFAULT_EAGER_TAIL);
  return Number(index) >= Math.max(0, Number(total || 0) - count);
}

export function createRichBlockController(options = {}) {
  const view = options.view || globalThis;
  const renderBlock = options.renderBlock;
  if (typeof renderBlock !== "function") {
    throw new TypeError("Rich block controller requires a renderer");
  }

  const scroller = options.scroller;
  const entries = new Map();
  const priority = [];
  const queued = new Set();
  const releaseDelayMs = Math.max(0, Number(options.releaseDelayMs ?? DEFAULT_RELEASE_DELAY_MS));
  let priorityFrame = 0;
  let destroyed = false;
  let tailPinned = true;

  const requestFrame = typeof view.requestAnimationFrame === "function"
    ? view.requestAnimationFrame.bind(view)
    : (callback) => view.setTimeout(callback, 0);
  const cancelFrame = typeof view.cancelAnimationFrame === "function"
    ? view.cancelAnimationFrame.bind(view)
    : view.clearTimeout.bind(view);

  function isNearBottom() {
    return typeof options.isNearBottom === "function" && options.isNearBottom();
  }

  function scrollerTop() {
    return Number(scroller?.getBoundingClientRect?.().top || 0);
  }

  function preserveScrollAnchor(node, before, wasNearBottom) {
    if (wasNearBottom || !before || !scroller) return;
    const after = node.getBoundingClientRect?.();
    // A tall deferred block can start above the viewport while its lower edge
    // still overlaps it. Preserve the content below that block (the history
    // anchor) whenever the block itself begins above the reading surface.
    if (!after || before.top >= scrollerTop() + 1) return;
    const delta = Number(after.height || 0) - Number(before.height || 0);
    if (Math.abs(delta) > 0.5) scroller.scrollTop = Number(scroller.scrollTop || 0) + delta;
  }

  function placeholder(entry, height = 0) {
    const node = entry.node;
    const preservedHeight = Math.max(1, Number(height) || estimatedBlockHeight(entry.descriptor.text, entry.descriptor.kind));
    const skeleton = node.ownerDocument.createElement("span");
    skeleton.className = "rich-block-placeholder math-ignore";
    skeleton.setAttribute("aria-hidden", "true");
    node.replaceChildren(skeleton);
    node.style.blockSize = `${Math.round(preservedHeight)}px`;
    node.dataset.faryoRichState = "deferred";
    node.setAttribute("aria-busy", "true");
    entry.state = "deferred";
    entry.height = preservedHeight;
  }

  function hydrate(entry) {
    if (!entry || entry.state === "rendered" || !entry.node.isConnected || destroyed) return false;
    queued.delete(entry.node);
    const node = entry.node;
    const before = node.getBoundingClientRect?.() || null;
    const wasNearBottom = isNearBottom();
    node.style.removeProperty("block-size");
    renderBlock(node, entry.descriptor);
    node.dataset.faryoRichState = "rendered";
    node.removeAttribute("aria-busy");
    entry.state = "rendered";
    entry.height = Number(node.getBoundingClientRect?.().height || entry.height || 0);
    preserveScrollAnchor(node, before, wasNearBottom);
    options.onHydrated?.(node, entry.descriptor, { wasNearBottom });
    return true;
  }

  function containsActiveSelection(node) {
    const selection = view.getSelection?.();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return false;
    try {
      return selection.getRangeAt(0).intersectsNode(node);
    } catch (_error) {
      return false;
    }
  }

  function dehydrate(entry) {
    if (
      !entry
      || entry.state !== "rendered"
      || entry.visible
      || entry.pinned
      || !entry.node.isConnected
      || containsActiveSelection(entry.node)
      || destroyed
    ) return false;
    const height = Number(entry.node.getBoundingClientRect?.().height || entry.height || 0);
    placeholder(entry, height);
    options.onReleased?.(entry.node, entry.descriptor);
    return true;
  }

  function drainPriority() {
    priorityFrame = 0;
    while (priority.length) {
      const entry = priority.shift();
      if (!entry || !queued.has(entry.node) || !entry.visible) continue;
      hydrate(entry);
      break;
    }
    if (priority.some((entry) => entry?.visible && queued.has(entry.node))) {
      priorityFrame = requestFrame(drainPriority);
    }
  }

  function prioritize(entry) {
    if (!entry || entry.state === "rendered" || queued.has(entry.node)) return;
    queued.add(entry.node);
    priority.push(entry);
    if (!priorityFrame) priorityFrame = requestFrame(drainPriority);
  }

  function scheduleRelease(entry) {
    if (!entry || entry.releaseTimer || entry.state !== "rendered" || entry.visible || entry.pinned) return;
    entry.releaseTimer = view.setTimeout(() => {
      entry.releaseTimer = 0;
      if (!dehydrate(entry) && !entry.visible && !entry.pinned) scheduleRelease(entry);
    }, releaseDelayMs);
  }

  const Observer = view.IntersectionObserver;
  const observer = typeof Observer === "function"
    ? new Observer((changes) => {
      for (const change of changes) {
        const entry = entries.get(change.target);
        if (!entry) continue;
        entry.visible = Boolean(change.isIntersecting);
        if (entry.releaseTimer) {
          view.clearTimeout(entry.releaseTimer);
          entry.releaseTimer = 0;
        }
        if (entry.visible) {
          prioritize(entry);
        } else scheduleRelease(entry);
      }
    }, {
      root: options.observerRoot || null,
      rootMargin: options.rootMargin || DEFAULT_ROOT_MARGIN,
    })
    : null;

  function prepare(node, descriptor, prepareOptions = {}) {
    if (!node || !descriptor) return;
    const signature = String(descriptor.signature || "");
    const eager = Boolean(prepareOptions.eager);
    const pinned = eager && tailPinned;
    let entry = entries.get(node);
    if (entry && entry.signature !== signature) {
      if (entry.releaseTimer) view.clearTimeout(entry.releaseTimer);
      observer?.unobserve(node);
      queued.delete(node);
      entries.delete(node);
      entry = null;
    }
    if (!entry) {
      entry = {
        node,
        descriptor,
        signature,
        state: "new",
        height: 0,
        visible: false,
        eager,
        pinned,
        releaseTimer: 0,
      };
      entries.set(node, entry);
      if (pinned) {
        hydrate(entry);
      } else {
        placeholder(entry);
        if (!observer) prioritize(entry);
      }
      observer?.observe(node);
      return;
    }
    entry.descriptor = descriptor;
    entry.eager = eager;
    entry.pinned = pinned;
    if (pinned && entry.state !== "rendered") hydrate(entry);
    observer?.observe(node);
  }

  function setTailPinned(value) {
    const next = Boolean(value);
    if (tailPinned === next) return;
    tailPinned = next;
    for (const entry of entries.values()) {
      entry.pinned = entry.eager && tailPinned;
      if (entry.pinned) {
        if (entry.releaseTimer) {
          view.clearTimeout(entry.releaseTimer);
          entry.releaseTimer = 0;
        }
        if (entry.visible && entry.state !== "rendered") prioritize(entry);
      } else scheduleRelease(entry);
    }
  }

  function ensure(node, siblings = 0) {
    let target = node;
    let remaining = Math.max(0, Number(siblings) || 0) + 1;
    let prepared = 0;
    while (target && remaining > 0) {
      const entry = entries.get(target);
      if (entry) {
        hydrate(entry);
        remaining -= 1;
        prepared += 1;
      }
      target = target.nextElementSibling;
    }
    return prepared;
  }

  function prune() {
    for (const [node, entry] of entries) {
      if (node.isConnected) continue;
      if (entry.releaseTimer) view.clearTimeout(entry.releaseTimer);
      observer?.unobserve(node);
      queued.delete(node);
      entries.delete(node);
    }
  }

  function clear() {
    for (const [node, entry] of entries) {
      if (entry.releaseTimer) view.clearTimeout(entry.releaseTimer);
      observer?.unobserve(node);
    }
    entries.clear();
    queued.clear();
    priority.length = 0;
    tailPinned = true;
    if (priorityFrame) cancelFrame(priorityFrame);
    priorityFrame = 0;
  }

  function destroy() {
    destroyed = true;
    clear();
    observer?.disconnect();
  }

  return Object.freeze({
    clear,
    destroy,
    ensure,
    prepare,
    prune,
    setTailPinned,
    get pendingCount() {
      let total = 0;
      for (const entry of entries.values()) if (entry.state !== "rendered") total += 1;
      return total;
    },
    get renderedCount() {
      let total = 0;
      for (const entry of entries.values()) if (entry.state === "rendered") total += 1;
      return total;
    },
  });
}

export const RICH_BLOCK_EAGER_TAIL = DEFAULT_EAGER_TAIL;
