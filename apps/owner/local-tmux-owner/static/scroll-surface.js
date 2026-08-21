(function initScrollSurface(root, factory) {
  'use strict';

  const api = factory();
  if (root) root.FaryoScrollSurface = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function scrollSurfaceFactory() {
  'use strict';

  function shouldUseDocumentScroller({ routeBase = '', width = 0, standalone = false } = {}) {
    return Boolean(routeBase) && Number(width || 0) < 720 && !standalone;
  }

  function createDocumentScroller(view) {
    if (!view?.document) throw new TypeError('document scroller requires a window');
    const documentRef = view.document;
    const element = () => documentRef.scrollingElement || documentRef.documentElement || documentRef.body;
    const viewportRect = () => {
      const viewport = view.visualViewport;
      const width = Number(viewport?.width || view.innerWidth || documentRef.documentElement?.clientWidth || 0);
      const height = Number(viewport?.height || view.innerHeight || documentRef.documentElement?.clientHeight || 0);
      const top = Math.max(0, Number(viewport?.offsetTop || 0));
      const left = Math.max(0, Number(viewport?.offsetLeft || 0));
      return { top, left, right: left + width, bottom: top + height, width, height };
    };
    const surface = {
      getBoundingClientRect() {
        return viewportRect();
      },
      addEventListener(name, listener, options) { view.addEventListener(name, listener, options); },
      removeEventListener(name, listener, options) { view.removeEventListener(name, listener, options); },
      scrollTo(options) { view.scrollTo(options); },
    };
    Object.defineProperties(surface, {
      scrollTop: {
        enumerable: true,
        get: () => Number(view.scrollY ?? element()?.scrollTop ?? 0),
        set: (value) => view.scrollTo({ top: Math.max(0, Number(value || 0)), behavior: 'auto' }),
      },
      scrollHeight: {
        enumerable: true,
        get: () => Math.max(
          Number(element()?.scrollHeight || 0),
          Number(documentRef.documentElement?.scrollHeight || 0),
          Number(documentRef.body?.scrollHeight || 0),
        ),
      },
      clientHeight: {
        enumerable: true,
        get: () => viewportRect().height,
      },
    });
    return surface;
  }

  function visualViewportShift({ layoutHeight = 0, visualHeight = 0, offsetTop = 0 } = {}) {
    const layout = Math.max(0, Number(layoutHeight) || 0);
    const visual = Math.max(0, Number(visualHeight) || 0);
    const offset = Math.max(0, Number(offsetTop) || 0);
    if (!layout || !visual || visual >= layout) return 0;
    return Math.max(-layout, Math.min(0, visual - layout + offset));
  }

  function visualViewportSnapshot({
    layoutHeight = 0,
    visualHeight = 0,
    offsetTop = 0,
    dockBottom = null,
  } = {}) {
    const layout = Math.max(0, Number(layoutHeight) || 0);
    const visual = Math.max(0, Number(visualHeight) || 0);
    const top = Math.max(0, Number(offsetTop) || 0);
    const visualBottom = layout
      ? Math.min(layout, Math.max(0, top + visual))
      : Math.max(0, top + visual);
    const obscuredBottom = layout && visual
      ? Math.max(0, layout - visualBottom)
      : 0;
    let shift = obscuredBottom ? -obscuredBottom : 0;
    const measuredBottom = Number(dockBottom);
    if (obscuredBottom && dockBottom !== null && Number.isFinite(measuredBottom) && measuredBottom > 0) {
      shift = visualBottom - measuredBottom;
    }
    shift = layout
      ? Math.max(-layout, Math.min(0, shift))
      : Math.min(0, shift);
    return {
      layoutHeight: layout,
      visualTop: top,
      visualHeight: visual,
      visualBottom,
      obscuredBottom,
      shift,
    };
  }

  function createVisualViewportDock(view, options = {}) {
    if (!view?.document) throw new TypeError('visual viewport dock requires a window');
    const rootElement = options.root || view.document.documentElement;
    const dockElement = typeof options.dock === 'function' ? options.dock : () => options.dock || null;
    const enabled = options.enabled !== false;
    const viewport = view.visualViewport;
    let frame = 0, destroyed = false;
    let baselineWidth = Math.max(0, Number(view.innerWidth) || 0);
    let maximumLayoutHeight = Math.max(0, Number(view.innerHeight) || 0);
    const settleTimers = new Set();
    let currentSnapshot = visualViewportSnapshot();
    const apply = () => {
      if (destroyed) return currentSnapshot;
      const layoutWidth = Math.max(0, Number(view.innerWidth) || 0);
      const layoutHeight = Math.max(0, Number(view.innerHeight) || 0);
      if (baselineWidth && layoutWidth && Math.abs(layoutWidth - baselineWidth) > 48) {
        baselineWidth = layoutWidth;
        maximumLayoutHeight = layoutHeight;
      } else {
        if (!baselineWidth) baselineWidth = layoutWidth;
        maximumLayoutHeight = Math.max(maximumLayoutHeight, layoutHeight);
      }
      const layoutResizeThreshold = Math.max(110, maximumLayoutHeight * 0.16);
      const layoutViewportResized = maximumLayoutHeight - layoutHeight > layoutResizeThreshold;
      const dock = enabled ? dockElement() : null;
      // Mobile Chromium may already anchor fixed elements to the visual
      // viewport. Measure the dock with our previous correction removed so a
      // keyboard inset is never applied twice.
      if (dock) rootElement?.style?.setProperty('--faryo-visual-viewport-shift-y', '0px');
      const dockBottom = dock?.getBoundingClientRect?.().bottom;
      const measured = enabled && viewport
        ? visualViewportSnapshot({
          layoutHeight,
          visualHeight: viewport.height,
          offsetTop: viewport.offsetTop,
          dockBottom: Number.isFinite(Number(dockBottom)) && Number(dockBottom) > 0
            ? Number(dockBottom)
            : null,
        })
        : visualViewportSnapshot();
      const viewportMode = layoutViewportResized ? 'layout-resized'
        : measured.obscuredBottom ? 'visual-fallback'
          : 'layout-stable';
      const next = layoutViewportResized
        ? { ...measured, obscuredBottom: 0, shift: 0, viewportMode }
        : { ...measured, viewportMode };
      const changed = next.shift !== currentSnapshot.shift
        || next.obscuredBottom !== currentSnapshot.obscuredBottom
        || next.visualHeight !== currentSnapshot.visualHeight
        || next.visualTop !== currentSnapshot.visualTop
        || next.viewportMode !== currentSnapshot.viewportMode;
      currentSnapshot = { ...next, changed };
      rootElement?.style?.setProperty('--faryo-visual-viewport-shift-y', `${next.shift}px`);
      rootElement?.style?.setProperty('--faryo-visual-viewport-obscured-bottom', `${next.obscuredBottom}px`);
      rootElement?.style?.setProperty('--faryo-visual-viewport-height', `${next.visualHeight}px`);
      if (rootElement?.dataset) {
        rootElement.dataset.faryoViewportMode = viewportMode;
        rootElement.dataset.faryoViewportShift = String(next.shift);
      }
      options.onChange?.(currentSnapshot);
      return currentSnapshot;
    };
    const runScheduled = () => {
      frame = 0;
      apply();
    };
    const settle = () => {
      for (const timer of settleTimers) (view.clearTimeout || clearTimeout)(timer);
      settleTimers.clear();
      for (const delay of [80, 240]) {
        const timer = (view.setTimeout || setTimeout)(() => {
          settleTimers.delete(timer);
          apply();
        }, delay);
        settleTimers.add(timer);
      }
    };
    const schedule = () => {
      if (destroyed) return;
      if (!frame) frame = (view.requestAnimationFrame || ((callback) => view.setTimeout(callback, 0)))(runScheduled);
      settle();
    };
    for (const target of [viewport, view]) {
      target?.addEventListener?.('resize', schedule, { passive: true });
      target?.addEventListener?.('scroll', schedule, { passive: true });
    }
    view.addEventListener?.('orientationchange', schedule, { passive: true });
    view.document.addEventListener?.('focusin', schedule, { passive: true });
    view.document.addEventListener?.('focusout', schedule, { passive: true });
    apply();
    return {
      update: apply,
      getSnapshot() { return currentSnapshot; },
      destroy() {
        destroyed = true;
        if (frame) (view.cancelAnimationFrame || view.clearTimeout)?.call(view, frame);
        for (const timer of settleTimers) (view.clearTimeout || clearTimeout)(timer);
        settleTimers.clear();
        for (const target of [viewport, view]) {
          target?.removeEventListener?.('resize', schedule);
          target?.removeEventListener?.('scroll', schedule);
        }
        view.removeEventListener?.('orientationchange', schedule);
        view.document.removeEventListener?.('focusin', schedule);
        view.document.removeEventListener?.('focusout', schedule);
        rootElement?.style?.setProperty('--faryo-visual-viewport-shift-y', '0px');
        rootElement?.style?.setProperty('--faryo-visual-viewport-obscured-bottom', '0px');
        rootElement?.style?.setProperty('--faryo-visual-viewport-height', '0px');
        if (rootElement?.dataset) {
          delete rootElement.dataset.faryoViewportMode;
          delete rootElement.dataset.faryoViewportShift;
        }
      },
    };
  }

  return {
    createDocumentScroller,
    createVisualViewportDock,
    shouldUseDocumentScroller,
    visualViewportShift,
    visualViewportSnapshot,
  };
});
