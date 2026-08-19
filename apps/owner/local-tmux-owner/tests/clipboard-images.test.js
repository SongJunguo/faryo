'use strict';

const assert = require('node:assert/strict');
const clipboard = require('../static/clipboard-images.js');

const image = { name: 'clipboard.png', type: 'image/png' };
const textFile = { name: 'notes.txt', type: 'text/plain' };

assert.deepEqual(clipboard.filesFromClipboard({
  items: [
    { kind: 'string', type: 'text/plain', getAsFile: () => null },
    { kind: 'file', type: 'image/png', getAsFile: () => image },
  ],
  files: [image],
}), [image], 'items must take precedence without duplicating clipboard files');

assert.deepEqual(
  clipboard.filesFromClipboard({ items: [], files: [textFile, image] }),
  [image],
  'legacy files fallback must keep image files only',
);
assert.deepEqual(clipboard.filesFromClipboard({ files: [textFile] }), []);
assert.equal(clipboard.plainTextFromClipboard({ getData: (type) => type === 'text/plain' ? 'caption' : '<b>caption</b>' }), 'caption');
assert.equal(clipboard.plainTextFromClipboard({ getData: () => { throw new Error('denied'); } }), '');
assert.deepEqual(
  clipboard.insertText('before SELECT after', 7, 13, 'caption'),
  { value: 'before caption after', selectionStart: 14 },
);

console.log('clipboard image paste tests passed');
