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

function fakeView({ virtualKeyboard = null } = {}) {
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
    document: { documentElement: root },
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
    listeners,
    flush() {
      const pending = [...frames.values()];
      frames.clear();
      for (const callback of pending) callback();
    },
  };
}

const keyboard = { overlaysContent: false, boundingRect: { height: 0 } };
const supported = fakeView({ virtualKeyboard: keyboard });
const observed = [];
const controller = keyboardLayout.createKeyboardLayout(supported.view, {
  onChange: (snapshot) => observed.push(snapshot),
});
assert.equal(keyboard.overlaysContent, true);
assert.equal(controller.getSnapshot().mode, 'virtual-keyboard');
assert.equal(supported.root.dataset.faryoKeyboardLayout, 'virtual-keyboard');
assert.equal(supported.root.dataset.faryoKeyboardOpen, '0');
assert.equal(supported.root.classList.contains('virtual-keyboard-layout'), true);
assert.equal(supported.listeners.has('keyboard:geometrychange'), true);
assert.equal(supported.listeners.has('viewport:resize'), false);

keyboard.boundingRect.height = 318;
supported.listeners.get('keyboard:geometrychange')();
supported.flush();
assert.deepEqual(controller.getSnapshot(), {
  mode: 'virtual-keyboard',
  visible: true,
  insetHeight: 318,
  changed: true,
});
assert.equal(supported.root.dataset.faryoKeyboardOpen, '1');
controller.destroy();
assert.equal(keyboard.overlaysContent, false);
assert.equal(supported.listeners.size, 0);
assert.equal(supported.root.classList.contains('virtual-keyboard-layout'), false);
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
assert.equal(refused.listeners.has('viewport:resize'), true);
refusedController.destroy();

console.log('keyboard layout tests passed');
