'use strict';

const assert = require('node:assert/strict');
const immersive = require('../static/immersive-mode.js');

class FakeClassList {
  constructor() { this.values = new Set(); }
  toggle(name, enabled) { if (enabled) this.values.add(name); else this.values.delete(name); }
  contains(name) { return this.values.has(name); }
}

class FakeButton {
  constructor(withLabel = false) {
    this.dataset = {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.hidden = false;
    this.title = '';
    this.label = withLabel ? { textContent: '' } : null;
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  addEventListener(name, listener) { this.listeners.set(name, listener); }
  removeEventListener(name, listener) { if (this.listeners.get(name) === listener) this.listeners.delete(name); }
  querySelector(selector) { return selector === '[data-fullscreen-label]' ? this.label : null; }
  click() { this.listeners.get('click')?.({ preventDefault() {} }); }
}

class FakeDocument {
  constructor() {
    this.listeners = new Map();
    this.fullscreenEnabled = true;
    this.fullscreenElement = null;
    this.requestOptions = null;
    this.documentElement = { classList: new FakeClassList(), dataset: {} };
    this.documentElement.requestFullscreen = async (options) => {
      this.requestOptions = options;
      this.fullscreenElement = this.documentElement;
      this.emit('fullscreenchange');
    };
    this.exitFullscreen = async () => {
      this.fullscreenElement = null;
      this.emit('fullscreenchange');
    };
  }
  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(listener);
  }
  removeEventListener(name, listener) { this.listeners.get(name)?.delete(listener); }
  emit(name) { for (const listener of this.listeners.get(name) || []) listener(); }
}

(async () => {
  const documentRef = new FakeDocument();
  const topButton = new FakeButton();
  const detailsButton = new FakeButton(true);
  const exitButton = new FakeButton();
  const changes = [];
  const errors = [];
  const controller = immersive.createController({
    document: documentRef,
    toggleButtons: [topButton, detailsButton],
    exitButton,
    onChange: (active, state) => changes.push([active, state.supported]),
    onError: (reason) => errors.push(reason),
  });

  assert.equal(controller.supported(), true);
  assert.equal(documentRef.documentElement.dataset.faryoFullscreen, 'ready');
  assert.equal(topButton.attributes.get('aria-label'), 'Enter full screen');
  assert.equal(detailsButton.label.textContent, 'Enter full screen');
  assert.equal(exitButton.hidden, true);

  assert.equal(await controller.enter(), true);
  assert.deepEqual(documentRef.requestOptions, { navigationUI: 'hide' });
  assert.equal(controller.active(), true);
  assert.equal(documentRef.documentElement.classList.contains('fullscreen-active'), true);
  assert.equal(topButton.dataset.fullscreenActive, 'true');
  assert.equal(detailsButton.label.textContent, 'Exit full screen');
  assert.equal(exitButton.hidden, false);

  documentRef.fullscreenElement = null;
  documentRef.emit('fullscreenchange');
  assert.equal(controller.active(), false, 'external browser exit must immediately update the UI');
  assert.equal(exitButton.hidden, true);

  await controller.enter();
  assert.equal(await controller.exit(), true);
  assert.equal(errors.length, 0);
  assert.deepEqual(changes, [[false, true], [true, true], [false, true], [true, true], [false, true]]);

  controller.destroy();
  assert.equal(topButton.listeners.has('click'), false, 'destroy must detach control handlers');

  const unsupportedDocument = new FakeDocument();
  unsupportedDocument.fullscreenEnabled = false;
  const unsupportedButton = new FakeButton(true);
  const unsupportedErrors = [];
  const unsupported = immersive.createController({
    document: unsupportedDocument,
    toggleButtons: [unsupportedButton],
    onError: (reason) => unsupportedErrors.push(reason),
  });
  assert.equal(unsupported.supported(), false);
  assert.equal(await unsupported.enter(), false);
  assert.deepEqual(unsupportedErrors, ['unsupported']);
  assert.equal(unsupportedButton.label.textContent, 'Full screen unavailable');
  assert.equal(unsupportedDocument.documentElement.dataset.faryoFullscreen, 'unsupported');

  const rejectedDocument = new FakeDocument();
  rejectedDocument.documentElement.requestFullscreen = async () => { throw new Error('denied'); };
  const rejectedErrors = [];
  const rejected = immersive.createController({
    document: rejectedDocument,
    onError: (reason) => rejectedErrors.push(reason),
  });
  assert.equal(await rejected.enter(), false);
  assert.deepEqual(rejectedErrors, ['request-failed']);

  console.log('immersive mode tests passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
