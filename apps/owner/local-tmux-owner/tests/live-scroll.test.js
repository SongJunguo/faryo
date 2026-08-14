'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const liveScroll = require(path.join(__dirname, '../static/live-scroll.js'));

function pane(scrollHeight, clientHeight, scrollTop) {
  return { scrollHeight, clientHeight, scrollTop };
}

assert.equal(liveScroll.snapshot(null), null);
assert.deepEqual(
  liveScroll.snapshot(pane(1000, 300, 680)),
  { scrollTop: 680, followLatest: true },
  'a pane near the bottom should keep following live output',
);
assert.deepEqual(
  liveScroll.snapshot(pane(1000, 300, 120)),
  { scrollTop: 120, followLatest: false },
  'a manually scrolled pane should preserve its reading position',
);

const initial = pane(1200, 300, 0);
liveScroll.restore(initial, null);
assert.equal(initial.scrollTop, 900, 'a new live pane should start at the latest output');

const following = pane(1500, 300, 0);
liveScroll.restore(following, { scrollTop: 680, followLatest: true });
assert.equal(following.scrollTop, 1200, 'new output should keep a following pane at the bottom');

const reading = pane(1500, 300, 120);
liveScroll.restore(reading, { scrollTop: 120, followLatest: false });
assert.equal(reading.scrollTop, 120, 'refresh must not move a manually scrolled pane');

const shortened = pane(350, 300, 120);
liveScroll.restore(shortened, { scrollTop: 120, followLatest: false });
assert.equal(shortened.scrollTop, 50, 'preserved positions should clamp to the new scroll range');

assert.equal(liveScroll.defaultExpanded(390), false, 'a phone live panel should start collapsed');
assert.equal(liveScroll.defaultExpanded(720), true, 'a tablet or desktop live panel should start expanded');
assert.equal(
  liveScroll.resolveExpanded('codex-a', { session: 'codex-a', expanded: false }, '1', 1200),
  false,
  'the currently rendered session state should survive a live refresh',
);
assert.equal(
  liveScroll.resolveExpanded('codex-b', { session: 'codex-a', expanded: true }, '0', 1200),
  false,
  'a different session should use only its own stored preference',
);
assert.equal(liveScroll.resolveExpanded('codex-c', null, null, 390), false);
assert.equal(liveScroll.resolveExpanded('codex-c', null, null, 1200), true);

console.log('live-scroll tests passed');
