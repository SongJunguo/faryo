'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const stream = require(path.join(__dirname, '../static/event-stream.js'));

const events = [];
const parser = stream.createParser((event) => events.push(event));
parser.push(': keepalive\r\nev');
parser.push('ent: capture\r\nid: epoch:7\r\ndata: {"ok":true,');
parser.push('"text":"hello"}\r\n\r');
parser.push('\nevent: notice\ndata: first\ndata: second\n\n');

assert.deepEqual(events, [
  { type: 'capture', data: '{"ok":true,"text":"hello"}', id: 'epoch:7' },
  { type: 'notice', data: 'first\nsecond', id: '' },
]);

const finalEvents = [];
const finalParser = stream.createParser((event) => finalEvents.push(event));
finalParser.push('data: final', true);
assert.deepEqual(finalEvents, [{ type: 'message', data: 'final', id: '' }]);
assert.equal(stream.decodeFrame('event: empty\n'), null);

console.log('event stream tests passed');
