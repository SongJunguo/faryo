'use strict';

const assert = require('node:assert/strict');
const navigator = require('../static/question-navigator.js');

assert.equal(navigator.previewText('  ›   First question\nwith detail  '), 'First question with detail');
assert.equal(navigator.previewText('中文问题需要按字符安全截断', 10), '中文问题需要按字符…');
assert.equal(navigator.previewText('', 24), 'Untitled question');

assert.equal(navigator.activeIndex([], 100), -1);
assert.equal(navigator.activeIndex([180, 420, 760], 100), 0);
assert.equal(navigator.activeIndex([40, 220, 680], 300), 1);
assert.equal(navigator.activeIndex([40, 220, 680], 900), 2);

assert.equal(navigator.targetScrollTop(400, 500, 100, 20, 2000), 780);
assert.equal(navigator.targetScrollTop(20, 10, 100, 20, 2000), 0);
assert.equal(navigator.targetScrollTop(1900, 700, 100, 20, 2000), 2000);

console.log('question navigator tests passed');
