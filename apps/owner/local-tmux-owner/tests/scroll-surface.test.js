'use strict';

const assert = require('node:assert/strict');
const scrollSurface = require('../static/scroll-surface.js');

assert.equal(scrollSurface.shouldUseDocumentScroller({ routeBase: '/txy', width: 390, standalone: false }), true);
assert.equal(scrollSurface.shouldUseDocumentScroller({ routeBase: '', width: 390, standalone: false }), false);
assert.equal(scrollSurface.shouldUseDocumentScroller({ routeBase: '/txy', width: 720, standalone: false }), false);
assert.equal(scrollSurface.shouldUseDocumentScroller({ routeBase: '/txy', width: 390, standalone: true }), false);

const listeners = new Map();
const scrollingElement = { scrollTop: 12, scrollHeight: 1400 };
const view = {
  innerWidth: 390,
  innerHeight: 844,
  scrollY: 12,
  document: {
    scrollingElement,
    documentElement: { clientWidth: 390, clientHeight: 844, scrollHeight: 1380 },
    body: { scrollHeight: 1450 },
  },
  addEventListener(name, listener) { listeners.set(name, listener); },
  removeEventListener(name, listener) { if (listeners.get(name) === listener) listeners.delete(name); },
  scrollTo(options) { this.lastScroll = options; this.scrollY = Number(options.top || 0); },
};

const surface = scrollSurface.createDocumentScroller(view);
assert.equal(surface.scrollTop, 12);
assert.equal(surface.scrollHeight, 1450);
assert.equal(surface.clientHeight, 844);
assert.deepEqual(surface.getBoundingClientRect(), { top: 0, left: 0, right: 390, bottom: 844, width: 390, height: 844 });
surface.scrollTop = 240;
assert.deepEqual(view.lastScroll, { top: 240, behavior: 'auto' });
surface.scrollTo({ top: 500, behavior: 'smooth' });
assert.deepEqual(view.lastScroll, { top: 500, behavior: 'smooth' });
const listener = () => {};
surface.addEventListener('scroll', listener, { passive: true });
assert.equal(listeners.get('scroll'), listener);
surface.removeEventListener('scroll', listener);
assert.equal(listeners.has('scroll'), false);
assert.throws(() => scrollSurface.createDocumentScroller(null), /requires a window/);

assert.equal(scrollSurface.visualViewportShift({ layoutHeight: 844, visualHeight: 400, offsetTop: 0 }), -444);
assert.equal(scrollSurface.visualViewportShift({ layoutHeight: 844, visualHeight: 400, offsetTop: 180 }), -264);
assert.equal(scrollSurface.visualViewportShift({ layoutHeight: 844, visualHeight: 844, offsetTop: 0 }), 0);
assert.equal(scrollSurface.visualViewportShift({ layoutHeight: 844, visualHeight: 900, offsetTop: 20 }), 0);
assert.equal(scrollSurface.visualViewportShift({ layoutHeight: 844, visualHeight: 100, offsetTop: 2000 }), 0);

assert.deepEqual(
  scrollSurface.visualViewportSnapshot({
    layoutHeight: 844,
    visualHeight: 400,
    offsetTop: 180,
    dockBottom: 844,
  }),
  {
    layoutHeight: 844,
    visualTop: 180,
    visualHeight: 400,
    visualBottom: 580,
    obscuredBottom: 264,
    shift: -264,
  },
);
assert.equal(scrollSurface.visualViewportSnapshot({
  layoutHeight: 844,
  visualHeight: 400,
  offsetTop: 180,
  dockBottom: 700,
}).shift, -120);
assert.equal(scrollSurface.visualViewportSnapshot({
  layoutHeight: 844,
  visualHeight: 400,
  offsetTop: 180,
  dockBottom: 0,
}).shift, -264);
assert.equal(scrollSurface.visualViewportSnapshot({
  layoutHeight: 844,
  visualHeight: 400,
  offsetTop: 180,
  dockBottom: 580,
}).shift, 0);

const dockListeners = new Map();
const viewportListeners = new Map();
const properties = new Map();
const propertyWrites = [];
const dockElement = { bottom: 844, getBoundingClientRect() { return { bottom: this.bottom }; } };
const dockView = {
  innerHeight: 844,
  visualViewport: {
    height: 400,
    offsetTop: 180,
    addEventListener(name, listener) { viewportListeners.set(name, listener); },
    removeEventListener(name, listener) { if (viewportListeners.get(name) === listener) viewportListeners.delete(name); },
  },
  document: {
    documentElement: { style: { setProperty(name, value) { properties.set(name, value); propertyWrites.push([name, value]); } } },
    addEventListener(name, listener) { dockListeners.set(`document:${name}`, listener); },
    removeEventListener(name, listener) { if (dockListeners.get(`document:${name}`) === listener) dockListeners.delete(`document:${name}`); },
  },
  addEventListener(name, listener) { dockListeners.set(name, listener); },
  removeEventListener(name, listener) { if (dockListeners.get(name) === listener) dockListeners.delete(name); },
  requestAnimationFrame(callback) { callback(); return 1; },
  cancelAnimationFrame() {},
  setTimeout() { return 1; },
  clearTimeout() {},
};
const dock = scrollSurface.createVisualViewportDock(dockView, { enabled: true, dock: dockElement });
assert.equal(properties.get('--faryo-visual-viewport-shift-y'), '-264px');
assert.equal(properties.get('--faryo-visual-viewport-obscured-bottom'), '264px');
dockElement.bottom = 580;
propertyWrites.length = 0;
assert.equal(dock.update().shift, 0);
assert.deepEqual(propertyWrites.filter(([name]) => name === '--faryo-visual-viewport-shift-y'), [
  ['--faryo-visual-viewport-shift-y', '0px'],
  ['--faryo-visual-viewport-shift-y', '0px'],
]);
dockView.visualViewport.height = 844;
dock.update();
assert.equal(properties.get('--faryo-visual-viewport-shift-y'), '0px');
dock.destroy();
assert.equal(properties.get('--faryo-visual-viewport-shift-y'), '0px');
assert.equal(properties.get('--faryo-visual-viewport-obscured-bottom'), '0px');
assert.equal(viewportListeners.size, 0);

console.log('scroll surface tests passed');
