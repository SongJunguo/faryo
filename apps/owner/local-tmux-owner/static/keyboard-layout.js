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

  function createKeyboardLayout(view, options = {}) {
    if (!view?.document) throw new TypeError('keyboard layout requires a window');
    const rootElement = options.root || view.document.documentElement;
    const keyboard = virtualKeyboardOf(options.navigator || view.navigator);
    let mode = 'viewport-resize';
    let restoreOverlay = null;
    if (keyboard) {
      try {
        const previous = Boolean(keyboard.overlaysContent);
        keyboard.overlaysContent = true;
        if (keyboard.overlaysContent === true) {
          mode = 'virtual-keyboard';
          restoreOverlay = previous;
        }
      } catch (_error) {
        mode = 'viewport-resize';
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
  };
});
