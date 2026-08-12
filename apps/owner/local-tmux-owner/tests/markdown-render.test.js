'use strict';

const assert = require('node:assert/strict');
const markdown = require('../static/markdown-render.js');

assert.equal(markdown.ready(), true);

const mixed = markdown.render([
  '# Result',
  '',
  '1. **Bounded** with \\(x_i\\).',
  '2. A [reference](https://example.com/doc).',
  '',
  '> Important',
  '',
  '| Item | Value |',
  '| --- | ---: |',
  '| bound | \\(M\\) |',
  '',
  '\\[',
  'p(s)=\\begin{cases}',
  'a,&0\\le s<s_0,\\\\',
  'b,&s\\ge s_0,',
  '\\end{cases}',
  '\\]',
  '',
  '```tex',
  '\\[not_math_inside_code\\]',
  '```',
].join('\n'));

assert.match(mixed, /<h1>Result<\/h1>/);
assert.match(mixed, /<ol>/);
assert.match(mixed, /<strong>Bounded<\/strong>/);
assert.match(mixed, /<blockquote>/);
assert.match(mixed, /<table>/);
assert.match(mixed, /target="_blank"/);
assert.match(mixed, /rel="noopener noreferrer"/);
assert.match(mixed, /\\\(x_i\\\)/);
assert.match(mixed, /\\begin\{cases\}/);
assert.match(mixed, /a,&amp;0\\le s&lt;s_0,\\\\/);
assert.match(mixed, /<code class="language-tex">\\\[not_math_inside_code\\\]/);

const scientificMath = markdown.render([
  'Generic mathematical notation:',
  '',
  '\\[',
  'q(\\tau)=\\begin{cases}',
  '\\alpha,&0\\le \\tau<\\tau_0,\\\\',
  '\\beta,&\\tau\\ge\\tau_0,',
  '\\end{cases}',
  '\\]',
  '',
  'with \\(\\zeta_m\\in[-R,R]\\), an indicator expansion',
  '',
  '\\[',
  'v(s)=\\alpha\\mathbf 1_{[0,1)}(s)+\\beta\\mathbf 1_{[1,2)}(s),',
  '\\]',
  '',
  'and a square-root map',
  '',
  '\\[',
  'j(r)=\\gamma\\,\\operatorname{sgn}(r)\\sqrt{|r|}.',
  '\\]',
].join('\n'));
assert.match(scientificMath, /\\begin\{cases\}/);
assert.match(scientificMath, /\\zeta_m\\in\[-R,R\]/);
assert.match(scientificMath, /\\mathbf 1_\{\[0,1\)\}/);
assert.match(scientificMath, /\\operatorname\{sgn\}\(r\)\\sqrt\{\|r\|\}/);

// Protect block math before Markdown's Setext-heading rule sees an equals-only
// row. Mature math previews enforce the same parser boundary.
const setextSensitiveMath = markdown.render([
  '$$',
  '\\begin{aligned}',
  'A',
  '=',
  'B,',
  '\\end{aligned}',
  '$$',
].join('\n'));
assert.doesNotMatch(setextSensitiveMath, /<h1>/);
assert.match(setextSensitiveMath, /\$\$[\s\S]*\\begin\{aligned\}[\s\S]*\$\$/);

const unsafe = markdown.render([
  '<img src=x onerror="globalThis.pwned=1">',
  '[run](javascript:alert(1))',
  '![payload](data:image/svg+xml,%3Csvg/onload=alert(1)%3E)',
].join('\n'));
assert.doesNotMatch(unsafe, /<img src=x/);
assert.doesNotMatch(unsafe, /href="javascript:/i);
assert.doesNotMatch(unsafe, /src="data:/i);
assert.match(unsafe, /&lt;img src=x onerror=/);

const local = markdown.render(
  '[paper](/home/user/paper.tex:17) ![plot](/home/user/plot.png)',
  {
    localFileHref: (path, line) => `/view?path=${encodeURIComponent(path)}&line=${line}`,
    localImageHref: (path) => `/image?path=${encodeURIComponent(path)}`,
  },
);
assert.match(local, /class="file-link markdown-file-link"/);
assert.match(local, /href="\/view\?path=%2Fhome%2Fuser%2Fpaper\.tex&amp;line=17"/);
assert.match(local, /src="\/image\?path=%2Fhome%2Fuser%2Fplot\.png"/);
assert.match(local, /class="chat-image chat-markdown-image"/);

console.log('markdown-render tests passed');
