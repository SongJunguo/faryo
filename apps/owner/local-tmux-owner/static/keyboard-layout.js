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

  function keyboardSnapshot(mode, keyboard) {
    const insetHeight = mode === 'virtual-keyboard'
      ? Math.max(0, Number(keyboard?.boundingRect?.height) || 0)
      : 0;
    return {
      mode,
      visible: insetHeight > 0,
      insetHeight,
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
    let mode = 'viewport-resize';
    let restoreOverlay = null;
    let restoreViewportContent = null;
    const restoreViewport = () => {
      if (restoreViewportContent === null || !viewportMeta) return;
      viewportMeta.setAttribute('content', restoreViewportContent);
      restoreViewportContent = null;
    };
    if (keyboard) {
      try {
        const previous = Boolean(keyboard.overlaysContent);
        if (viewportMeta) {
          restoreViewportContent = viewportMeta.getAttribute('content') || '';
          viewportMeta.setAttribute(
            'content',
            withInteractiveWidget(restoreViewportContent, 'overlays-content'),
          );
        }
        keyboard.overlaysContent = true;
        if (keyboard.overlaysContent === true) {
          mode = 'virtual-keyboard';
          restoreOverlay = previous;
        } else {
          restoreViewport();
        }
      } catch (_error) {
        mode = 'viewport-resize';
        try { restoreViewport(); } catch (_restoreError) {}
      }
    }

    let destroyed = false;
    let frame = 0;
    let current = { ...keyboardSnapshot(mode, keyboard), changed: true };
    const publish = (forceChanged = false) => {
      frame = 0;
      if (destroyed) return current;
      const next = keyboardSnapshot(mode, keyboard);
      const changed = forceChanged
        || next.mode !== current.mode
        || next.visible !== current.visible
        || next.insetHeight !== current.insetHeight;
      current = { ...next, changed };
      if (rootElement?.dataset) {
        rootElement.dataset.faryoKeyboardLayout = next.mode;
        rootElement.dataset.faryoKeyboardOpen = next.visible ? '1' : '0';
      }
      rootElement?.classList?.toggle('virtual-keyboard-layout', next.mode === 'virtual-keyboard');
      options.onChange?.(current);
      return current;
    };
    const publishScheduled = () => publish(true);
    const schedule = () => {
      if (destroyed || frame) return;
      const request = view.requestAnimationFrame || ((callback) => view.setTimeout(callback, 0));
      frame = request.call(view, publishScheduled);
    };
    const eventTargets = mode === 'virtual-keyboard'
      ? [[keyboard, 'geometrychange'], [view, 'resize']]
      : [[view.visualViewport, 'resize'], [view, 'resize']];
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
        if (restoreOverlay !== null) {
          try {
            keyboard.overlaysContent = restoreOverlay;
          } catch (_error) {}
        }
        try { restoreViewport(); } catch (_error) {}
        rootElement?.classList?.remove('virtual-keyboard-layout');
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
