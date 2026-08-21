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
    const surface = {
      getBoundingClientRect() {
        const width = Number(view.innerWidth || documentRef.documentElement?.clientWidth || 0);
        const height = Number(view.innerHeight || documentRef.documentElement?.clientHeight || 0);
        return { top: 0, left: 0, right: width, bottom: height, width, height };
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
        get: () => Number(view.innerHeight || documentRef.documentElement?.clientHeight || 0),
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

  function createVisualViewportDock(view, options = {}) {
    if (!view?.document) throw new TypeError('visual viewport dock requires a window');
    const rootElement = options.root || view.document.documentElement;
    const enabled = options.enabled !== false;
    const viewport = view.visualViewport;
    let frame = 0, destroyed = false;
    const apply = () => {
      frame = 0;
      if (destroyed) return 0;
      const shift = enabled && viewport
        ? visualViewportShift({
          layoutHeight: view.innerHeight,
          visualHeight: viewport.height,
          offsetTop: viewport.offsetTop,
        })
        : 0;
      rootElement?.style?.setProperty('--faryo-visual-viewport-shift-y', `${shift}px`);
      return shift;
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
      },
    };
  }

  return {
    createDocumentScroller,
    createVisualViewportDock,
    shouldUseDocumentScroller,
    visualViewportShift,
  };
});
