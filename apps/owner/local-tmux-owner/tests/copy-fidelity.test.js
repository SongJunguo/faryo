'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const copy = require(path.join(__dirname, '../static/copy-fidelity.js'));

const rendererSource = fs.readFileSync(
  path.join(__dirname, '../static/vendor/markdown-ast/markdown-ast.min.js'),
  'utf8',
);
const document = {
  compatMode: 'CSS1Compat',
  createElement() {
    return { textContent: '', set innerHTML(value) { this.textContent = value; } };
  },
};
const rendererContext = { console, document, URL, setTimeout, clearTimeout };
vm.runInNewContext(rendererSource, rendererContext, { filename: 'markdown-ast.min.js' });
const markdown = rendererContext.FaryoMarkdownAst;

const source = [
  'Inline \\(x_i^2\\) stays inline.',
  '',
  '\\[',
  'p(t)=\\begin{cases}',
  'a,&t<0,\\\\',
  'b,&t\\ge0.',
  '\\end{cases}',
  '\\]',
  '',
  '```tex',
  '\\[literal code\\]',
  '```',
].join('\n');
const formulas = copy.mathSources(source, markdown.parse);

assert.equal(copy.version, '1');
assert.equal(formulas.length, 2);
assert.deepEqual(
  formulas.map((formula) => ({ raw: formula.raw, tex: formula.tex, display: formula.display })),
  [
    { raw: '\\(x_i^2\\)', tex: 'x_i^2', display: false },
    {
      raw: '\\[\np(t)=\\begin{cases}\na,&t<0,\\\\\nb,&t\\ge0.\n\\end{cases}\n\\]',
      tex: 'p(t)=\\begin{cases}\na,&t<0,\\\\\nb,&t\\ge0.\n\\end{cases}',
      display: true,
    },
  ],
);

const fallback = copy.mathSources('unused', () => ({
  type: 'root',
  children: [{ type: 'math', value: 'A=B', children: [] }],
}));
assert.equal(fallback[0].raw, '\\[\nA=B\n\\]');

const dollarFormulas = copy.mathSources('$x_i$\n\n$$A=B$$', markdown.parse);
assert.deepEqual(dollarFormulas.map((formula) => formula.raw), ['$x_i$', '$$A=B$$']);

const moduleSource = fs.readFileSync(path.join(__dirname, '../static/copy-fidelity.js'), 'utf8');
assert.doesNotMatch(moduleSource, /localStorage|sessionStorage/u);

console.log('copy fidelity source-map tests passed');
