'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const annotations = require(path.join(__dirname, '../static/internal-annotations.js'));

const source = [
  'The rendered answer remains visible.',
  '',
  '<oai-mem-citation>',
  '<citation_entries>',
  'MEMORY.md:1-43|note=[Faryo deployment context]',
  'rollout_summaries/example.md:10-12|note=[Prior verification]',
  '</citation_entries>',
  '<rollout_ids>',
  '00000000-0000-0000-0000-000000000000',
  '</rollout_ids>',
  '</oai-mem-citation>',
].join('\n');

const parsed = annotations.parse(source);
assert.equal(parsed.body, 'The rendered answer remains visible.');
assert.equal(parsed.citations.length, 1);
assert.deepEqual(parsed.citations[0].entries, [
  { source: 'MEMORY.md:1-43', note: 'Faryo deployment context' },
  { source: 'rollout_summaries/example.md:10-12', note: 'Prior verification' },
]);
assert.ok(!JSON.stringify(parsed).includes('00000000-0000-0000-0000-000000000000'));
assert.equal(annotations.strip(source), 'The rendered answer remains visible.');

const malformed = annotations.parse('Visible text\n<oai-mem-citation>internal data');
assert.equal(malformed.body, 'Visible text');
assert.equal(malformed.citations[0].malformed, true);
assert.equal(annotations.parse('ordinary <tag> text').body, 'ordinary <tag> text');

console.log('internal annotation tests passed');
