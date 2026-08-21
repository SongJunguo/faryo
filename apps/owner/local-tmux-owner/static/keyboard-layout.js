(function initKeyboardLayout(root, factory) {
  'use strict';

  const api = factory();
  if (root) root.FaryoKeyboardLayout = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function keyboardLayoutFactory() {
  'use strict';

  function virtualKeyboardOf(navigatorRef) {
    const keyboard = navigatorRef?.virtualKeyboard;
    return keyboard && 'overlaysContent' in keyboard ? keyboard : null;
  }

  function keyboardSnapshot() {
    return {
      mode: 'viewport-resize',
      visible: false,
      insetHeight: 0,
    };
  }

  function withInteractiveWidget(content, value) {
    const parts = String(content || '')
      .split(',')
      .map((part) => part.trim())
      .filter((part) => part && !/^interactive-widget\s*=/i.test(part));
    parts.push(`interactive-widget=${value}`);
    return parts.join(', ');
  }

  function createKeyboardLayout(view, options = {}) {
    if (!view?.document) throw new TypeError('keyboard layout requires a window');
    const rootElement = options.root || view.document.documentElement;
    const keyboard = virtualKeyboardOf(options.navigator || view.navigator);
    const viewportMeta = options.viewportMeta
      || view.document.querySelector?.('meta[name="viewport"]')
      || null;
    if (viewportMeta) {
      viewportMeta.setAttribute(
        'content',
        withInteractiveWidget(viewportMeta.getAttribute('content'), 'resizes-content'),
      );
    }
    if (keyboard) {
      try {
        keyboard.overlaysContent = false;
      } catch (_error) {}
    }

    let destroyed = false;
    let frame = 0;
    let current = { ...keyboardSnapshot(), changed: true };
    const publish = (forceChanged = false) => {
      frame = 0;
      if (destroyed) return current;
      const next = keyboardSnapshot();
      const changed = forceChanged;
      current = { ...next, changed };
      if (rootElement?.dataset) {
        rootElement.dataset.faryoKeyboardLayout = next.mode;
        rootElement.dataset.faryoKeyboardOpen = '0';
      }
      options.onChange?.(current);
      return current;
    };
    const publishScheduled = () => publish(true);
    const schedule = () => {
      if (destroyed || frame) return;
      const request = view.requestAnimationFrame || ((callback) => view.setTimeout(callback, 0));
      frame = request.call(view, publishScheduled);
    };
    const eventTargets = [[view.visualViewport, 'resize'], [view, 'resize']];
    for (const [target, name] of eventTargets) target?.addEventListener?.(name, schedule, { passive: true });
    publish();

    return {
      update: publish,
      getSnapshot() { return current; },
      destroy() {
        if (destroyed) return;
        destroyed = true;
        if (frame) (view.cancelAnimationFrame || view.clearTimeout)?.call(view, frame);
        for (const [target, name] of eventTargets) target?.removeEventListener?.(name, schedule);
        if (rootElement?.dataset) {
          delete rootElement.dataset.faryoKeyboardLayout;
          delete rootElement.dataset.faryoKeyboardOpen;
        }
      },
    };
  }

  return {
    createKeyboardLayout,
    keyboardSnapshot,
    virtualKeyboardOf,
    withInteractiveWidget,
  };
});
