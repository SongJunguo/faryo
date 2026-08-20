(function initImmersiveMode(root, factory) {
  'use strict';

  const api = factory();
  if (root) root.FaryoImmersiveMode = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function immersiveModeFactory() {
  'use strict';

  function fullscreenElement(documentRef) {
    return documentRef?.fullscreenElement || documentRef?.webkitFullscreenElement || null;
  }

  function requestMethod(target) {
    return target?.requestFullscreen || target?.webkitRequestFullscreen || null;
  }

  function exitMethod(documentRef) {
    return documentRef?.exitFullscreen || documentRef?.webkitExitFullscreen || null;
  }

  function isSupported(documentRef, target) {
    const enabled = documentRef?.fullscreenEnabled ?? documentRef?.webkitFullscreenEnabled;
    return enabled !== false && Boolean(requestMethod(target) && exitMethod(documentRef));
  }

  function createController(options = {}) {
    const documentRef = options.document;
    const target = options.target || documentRef?.documentElement;
    const rootElement = options.root || documentRef?.documentElement;
    const toggles = Array.from(options.toggleButtons || []).filter(Boolean);
    const exitButton = options.exitButton || null;
    const onError = typeof options.onError === 'function' ? options.onError : () => {};
    const onChange = typeof options.onChange === 'function' ? options.onChange : () => {};
    const supported = isSupported(documentRef, target);
    const clickHandlers = [];
    let busy = false;
    let destroyed = false;
    let previousActive = null;
    let lastErrorAt = 0;

    function reportError(reason) {
      const now = Date.now();
      if (now - lastErrorAt < 120) return;
      lastErrorAt = now;
      onError(reason);
    }

    function active() {
      return fullscreenElement(documentRef) !== null;
    }

    function updateToggle(button, isActive) {
      if (!button) return;
      const label = isActive ? 'Exit full screen' : 'Enter full screen';
      button.dataset.fullscreenActive = isActive ? 'true' : 'false';
      button.dataset.fullscreenSupported = supported ? 'true' : 'false';
      button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      button.setAttribute('aria-label', supported ? label : 'Full screen unavailable');
      button.title = supported ? label : 'Install Faryo from Home for an app-style window';
      const text = button.querySelector?.('[data-fullscreen-label]');
      if (text) text.textContent = supported ? label : 'Full screen unavailable';
    }

    function sync() {
      if (destroyed) return false;
      const isActive = active();
      rootElement?.classList?.toggle('fullscreen-active', isActive);
      if (rootElement?.dataset) rootElement.dataset.faryoFullscreen = isActive ? 'active' : (supported ? 'ready' : 'unsupported');
      for (const button of toggles) updateToggle(button, isActive);
      if (exitButton) {
        exitButton.hidden = !isActive;
        exitButton.setAttribute('aria-hidden', isActive ? 'false' : 'true');
      }
      if (isActive !== previousActive) {
        previousActive = isActive;
        onChange(isActive, { supported });
      }
      return isActive;
    }

    async function enter() {
      if (busy || destroyed) return active();
      const request = requestMethod(target);
      if (!supported || !request) {
        reportError('unsupported');
        sync();
        return false;
      }
      if (active()) return true;
      busy = true;
      try {
        await request.call(target, { navigationUI: 'hide' });
      } catch (_error) {
        reportError('request-failed');
      } finally {
        busy = false;
        sync();
      }
      return active();
    }

    async function exit() {
      if (busy || destroyed) return active();
      const leave = exitMethod(documentRef);
      if (!active()) {
        sync();
        return true;
      }
      if (!leave) {
        reportError('exit-failed');
        return false;
      }
      busy = true;
      try {
        await leave.call(documentRef);
      } catch (_error) {
        reportError('exit-failed');
      } finally {
        busy = false;
        sync();
      }
      return !active();
    }

    function toggle() {
      return active() ? exit() : enter();
    }

    function bind(button, handler) {
      if (!button?.addEventListener) return;
      const listener = (event) => {
        event?.preventDefault?.();
        handler();
      };
      button.addEventListener('click', listener);
      clickHandlers.push([button, listener]);
    }

    const changeListener = () => sync();
    const errorListener = () => {
      reportError('request-failed');
      sync();
    };
    for (const button of toggles) bind(button, toggle);
    bind(exitButton, exit);
    documentRef?.addEventListener?.('fullscreenchange', changeListener);
    documentRef?.addEventListener?.('webkitfullscreenchange', changeListener);
    documentRef?.addEventListener?.('fullscreenerror', errorListener);
    documentRef?.addEventListener?.('webkitfullscreenerror', errorListener);
    sync();

    return {
      active,
      enter,
      exit,
      toggle,
      sync,
      supported: () => supported,
      destroy() {
        if (destroyed) return;
        destroyed = true;
        for (const [button, listener] of clickHandlers) button.removeEventListener?.('click', listener);
        documentRef?.removeEventListener?.('fullscreenchange', changeListener);
        documentRef?.removeEventListener?.('webkitfullscreenchange', changeListener);
        documentRef?.removeEventListener?.('fullscreenerror', errorListener);
        documentRef?.removeEventListener?.('webkitfullscreenerror', errorListener);
      },
    };
  }

  return { createController, fullscreenElement, isSupported };
});
