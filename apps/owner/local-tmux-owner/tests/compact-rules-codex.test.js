'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../static/compact-rules-codex.js');
const browserWindow = {};
vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), { window: browserWindow }, { filename: sourcePath });

const rules = browserWindow.FaryoCodexCompactRules;
const boundedness = [
  '• Boundedness means there is an M such that',
  '',
  '[',
  '|d(t)|\\le M.',
  ']',
  '',
  '2. Measurability follows.',
].join('\n');

const blocks = rules.compactBlocks(boundedness);
assert.equal(blocks.length, 1);
assert.equal(blocks[0].kind, 'output');
assert.match(blocks[0].text, /\[\n\|d\(t\)\|\\le M\.\n\]/);

console.log('compact-rules-codex tests passed');
