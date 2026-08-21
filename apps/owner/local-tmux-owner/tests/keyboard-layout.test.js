'use strict';

const assert = require('node:assert/strict');
const keyboardLayout = require('../static/keyboard-layout.js');

assert.equal(keyboardLayout.virtualKeyboardOf({}), null);
assert.equal(keyboardLayout.virtualKeyboardOf({ virtualKeyboard: {} }), null);
assert.deepEqual(keyboardLayout.keyboardSnapshot('viewport-resize', null), {
  mode: 'viewport-resize',
  visible: false,
  insetHeight: 0,
});
assert.equal(
  keyboardLayout.withInteractiveWidget(
    'width=device-width, initial-scale=1, interactive-widget=resizes-content',
    'overlays-content',
  ),
  'width=device-width, initial-scale=1, interactive-widget=overlays-content',
);
assert.equal(
  keyboardLayout.withInteractiveWidget('width=device-width', 'resizes-content'),
  'width=device-width, interactive-widget=resizes-content',
);

function fakeView({ virtualKeyboard = null, viewport = 'resizes-content' } = {}) {
  const listeners = new Map();
  const classes = new Set();
  const frames = new Map();
  let nextFrame = 1;
  const root = {
    dataset: {},
    classList: {
      toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
  };
  let viewportContent = `width=device-width, initial-scale=1, interactive-widget=${viewport}`;
  const viewportMeta = {
    getAttribute(name) { return name === 'content' ? viewportContent : null; },
    setAttribute(name, value) { if (name === 'content') viewportContent = String(value); },
  };
  const add = (scope) => (name, listener) => listeners.set(`${scope}:${name}`, listener);
  const remove = (scope) => (name, listener) => {
    if (listeners.get(`${scope}:${name}`) === listener) listeners.delete(`${scope}:${name}`);
  };
  if (virtualKeyboard) {
    virtualKeyboard.addEventListener = add('keyboard');
    virtualKeyboard.removeEventListener = remove('keyboard');
  }
  const visualViewport = {
    addEventListener: add('viewport'),
    removeEventListener: remove('viewport'),
  };
  const view = {
    document: {
      documentElement: root,
      querySelector(selector) { return selector === 'meta[name="viewport"]' ? viewportMeta : null; },
    },
    navigator: virtualKeyboard ? { virtualKeyboard } : {},
    visualViewport,
    addEventListener: add('window'),
    removeEventListener: remove('window'),
    requestAnimationFrame(callback) { const id = nextFrame++; frames.set(id, callback); return id; },
    cancelAnimationFrame(id) { frames.delete(id); },
  };
  return {
    view,
    root,
    viewportMeta,
    listeners,
    flush() {
      const pending = [...frames.values()];
      frames.clear();
      for (const callback of pending) callback();
    },
  };
}

const keyboard = { overlaysContent: true, boundingRect: { height: 318 } };
const supported = fakeView({ virtualKeyboard: keyboard, viewport: 'overlays-content' });
const observed = [];
const controller = keyboardLayout.createKeyboardLayout(supported.view, {
  onChange: (snapshot) => observed.push(snapshot),
});
assert.equal(keyboard.overlaysContent, false);
assert.match(supported.viewportMeta.getAttribute('content'), /interactive-widget=resizes-content/);
assert.deepEqual(controller.getSnapshot(), {
  mode: 'viewport-resize',
  visible: false,
  insetHeight: 0,
  changed: false,
});
assert.equal(supported.root.dataset.faryoKeyboardLayout, 'viewport-resize');
assert.equal(supported.root.dataset.faryoKeyboardOpen, '0');
assert.equal(supported.listeners.has('keyboard:geometrychange'), false);
assert.equal(supported.listeners.has('viewport:resize'), true);
assert.equal(supported.listeners.has('window:resize'), true);
supported.listeners.get('viewport:resize')();
supported.flush();
assert.deepEqual(controller.getSnapshot(), {
  mode: 'viewport-resize',
  visible: false,
  insetHeight: 0,
  changed: true,
});
controller.destroy();
assert.equal(keyboard.overlaysContent, false);
assert.match(supported.viewportMeta.getAttribute('content'), /interactive-widget=resizes-content/);
assert.equal(supported.listeners.size, 0);
assert.equal('faryoKeyboardLayout' in supported.root.dataset, false);
assert.ok(observed.length >= 2);

const fallback = fakeView();
const fallbackController = keyboardLayout.createKeyboardLayout(fallback.view);
assert.deepEqual(fallbackController.getSnapshot(), {
  mode: 'viewport-resize',
  visible: false,
  insetHeight: 0,
  changed: false,
});
assert.equal(fallback.listeners.has('viewport:resize'), true);
assert.equal(fallback.listeners.has('window:resize'), true);
fallback.listeners.get('viewport:resize')();
fallback.flush();
assert.equal(fallbackController.getSnapshot().mode, 'viewport-resize');
assert.equal(fallbackController.getSnapshot().changed, true);
fallbackController.destroy();
assert.equal(fallback.listeners.size, 0);

const refusingKeyboard = {
  boundingRect: { height: 240 },
  get overlaysContent() { return false; },
  set overlaysContent(_value) {},
};
const refused = fakeView({ virtualKeyboard: refusingKeyboard });
const refusedController = keyboardLayout.createKeyboardLayout(refused.view);
assert.equal(refusedController.getSnapshot().mode, 'viewport-resize');
assert.match(refused.viewportMeta.getAttribute('content'), /interactive-widget=resizes-content/);
assert.equal(refused.listeners.has('viewport:resize'), true);
refusedController.destroy();

console.log('keyboard layout tests passed');
