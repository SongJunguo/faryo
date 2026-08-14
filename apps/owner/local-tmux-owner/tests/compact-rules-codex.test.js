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

const markdownTable = [
  '• Result',
  '',
  '| Operator | Recommendation |',
  '| --- | --- |',
  '| \\(A_j\\) | exact form |',
  '| \\(B_j\\) | related mechanism |',
  '',
  'The table remains part of the answer.',
].join('\n');
const tableBlocks = rules.compactBlocks(markdownTable);
assert.equal(tableBlocks.length, 1);
assert.equal(tableBlocks[0].kind, 'output');
assert.match(tableBlocks[0].text, /\| Operator \| Recommendation \|/);
assert.equal(rules.isMarkdownTableLine('| Operator | Recommendation |'), true);
assert.equal(rules.isMarkdownTableLine('| command output continuation'), false);

console.log('compact-rules-codex tests passed');
