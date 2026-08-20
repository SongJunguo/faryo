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

console.log('scroll surface tests passed');
