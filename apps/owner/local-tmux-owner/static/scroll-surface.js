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

  return { createDocumentScroller, shouldUseDocumentScroller };
});
