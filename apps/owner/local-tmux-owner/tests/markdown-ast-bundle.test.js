'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '../static/vendor/markdown-ast/markdown-ast.min.js'),
  'utf8',
);
const document = {
  compatMode: 'CSS1Compat',
  createElement() {
    return {
      textContent: '',
      set innerHTML(value) {
        this.textContent = value;
      },
    };
  },
};
const context = { console, document, URL, setTimeout, clearTimeout };
vm.runInNewContext(source, context, { filename: 'markdown-ast.min.js' });

const markdown = context.FaryoMarkdownAst;
assert.equal(markdown.ready(), true);
assert.equal(markdown.engine, 'micromark-mdast');

const rendered = markdown.render([
  '# Result',
  '',
  '**注意：**内容',
  '',
  '| Operator | Recommendation |',
  '| --- | --- |',
  '| \\(\\Psi_i=\\eta_i\\) | exact form |',
  '| \\(\\Psi_i=e_i\\) | standard integral |',
  '',
  '\\[',
  'p(s)=\\begin{cases}',
  'a,&0\\le s<s_0,\\\\',
  'b,&s\\ge s_0,',
  '\\end{cases}',
  '\\]',
].join('\n'));

assert.match(rendered, /<h1>Result<\/h1>/u);
assert.match(rendered, /<strong>注意：<\/strong>内容/u);
assert.match(rendered, /<div class="markdown-table-scroll"><table>/u);
assert.equal((rendered.match(/class="katex"/gu) || []).length, 3);
assert.equal((rendered.match(/class="katex-display"/gu) || []).length, 1);
assert.doesNotMatch(rendered, /class="katex-error"/u);

const tick = String.fromCharCode(96);
const code = markdown.render([
  tick + '$HOME and \\(x\\)' + tick,
  '',
  tick.repeat(3) + 'tex',
  '\\[not math\\]',
  tick.repeat(3),
].join('\n'));
assert.doesNotMatch(code, /class="katex"/u);
assert.match(code, /\$HOME and \\\(x\\\)/u);

const unsafe = markdown.render([
  '<img src=x onerror="globalThis.pwned=1">',
  '',
  '[run](javascript:alert(1))',
  '',
  '![payload](data:text/plain,boom)',
].join('\n'));
assert.doesNotMatch(unsafe, /<img src=x/iu);
assert.doesNotMatch(unsafe, /href="javascript:/iu);
assert.doesNotMatch(unsafe, /src="data:/iu);

const streaming = markdown.render('partial \\(x_i', {}, { mode: 'streaming' });
assert.doesNotMatch(streaming, /class="katex"/u);

console.log('markdown-ast bundle tests passed');
