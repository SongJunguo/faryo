import assert from 'node:assert/strict';
import test from 'node:test';

import {
  BRACKETED_PASTE_END,
  BRACKETED_PASTE_START,
  compactProbe,
  TerminalDeliveryParser,
} from './terminal-delivery-receiver.mjs';

test('fragmented bracketed paste preserves Chinese, TeX, and newlines', () => {
  const parser = new TerminalDeliveryParser();
  const text = '中文第一行\n\\[x_i^2+y_i^2\\]';
  const chunks = [
    `ignored${BRACKETED_PASTE_START.slice(0, 3)}`,
    `${BRACKETED_PASTE_START.slice(3)}${text.slice(0, 5)}`,
    `${text.slice(5)}${BRACKETED_PASTE_END.slice(0, 4)}`,
    `${BRACKETED_PASTE_END.slice(4)}\r`,
  ];
  const events = chunks.flatMap((chunk) => parser.push(chunk));

  assert.deepEqual(events, [
    { type: 'paste', text },
    { type: 'submit', text },
  ]);
});

test('newlines inside a paste do not submit early and sequential turns stay separate', () => {
  const parser = new TerminalDeliveryParser();
  const first = 'one\ntwo\nthree';
  const second = '**Markdown** and \\(z^2\\)';

  assert.deepEqual(parser.push(`${BRACKETED_PASTE_START}${first}`), []);
  assert.deepEqual(parser.push(`${BRACKETED_PASTE_END}`), [{ type: 'paste', text: first }]);
  assert.deepEqual(parser.push(`\r${BRACKETED_PASTE_START}${second}${BRACKETED_PASTE_END}\n`), [
    { type: 'submit', text: first },
    { type: 'paste', text: second },
    { type: 'submit', text: second },
  ]);
});

test('compact probe mirrors Owner whitespace compaction', () => {
  assert.equal(compactProbe('  first\n\tsecond   中文  '), 'first second 中文');
});
