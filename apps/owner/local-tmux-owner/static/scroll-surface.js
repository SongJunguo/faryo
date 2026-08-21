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
    currentShift = 0,
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
    const previousShift = Number(currentShift) || 0;
    if (obscuredBottom && dockBottom !== null && Number.isFinite(measuredBottom) && measuredBottom > 0) {
      const unshiftedDockBottom = measuredBottom - previousShift;
      shift = visualBottom - unshiftedDockBottom;
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
    let frame = 0, destroyed = false, currentShift = 0;
    let currentSnapshot = visualViewportSnapshot();
    const apply = () => {
      frame = 0;
      if (destroyed) return currentSnapshot;
      const dock = enabled ? dockElement() : null;
      const dockBottom = dock?.getBoundingClientRect?.().bottom;
      const next = enabled && viewport
        ? visualViewportSnapshot({
          layoutHeight: view.innerHeight,
          visualHeight: viewport.height,
          offsetTop: viewport.offsetTop,
          dockBottom: Number.isFinite(Number(dockBottom)) && Number(dockBottom) > 0
            ? Number(dockBottom)
            : null,
          currentShift,
        })
        : visualViewportSnapshot();
      const changed = next.shift !== currentSnapshot.shift
        || next.obscuredBottom !== currentSnapshot.obscuredBottom
        || next.visualHeight !== currentSnapshot.visualHeight
        || next.visualTop !== currentSnapshot.visualTop;
      currentShift = next.shift;
      currentSnapshot = { ...next, changed };
      rootElement?.style?.setProperty('--faryo-visual-viewport-shift-y', `${next.shift}px`);
      rootElement?.style?.setProperty('--faryo-visual-viewport-obscured-bottom', `${next.obscuredBottom}px`);
      rootElement?.style?.setProperty('--faryo-visual-viewport-height', `${next.visualHeight}px`);
      options.onChange?.(currentSnapshot);
      return currentSnapshot;
    };
    const schedule = () => {
      if (destroyed || frame) return;
      frame = (view.requestAnimationFrame || ((callback) => view.setTimeout(callback, 0)))(apply);
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
