import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import {
  engine,
  localReference,
  parse,
  ready,
  render,
  setHighlighter,
} from '../src/index.js';

const count = (source, pattern) => [...source.matchAll(pattern)].length;

test('renders semantic CommonMark, GFM, and CJK emphasis', () => {
  const source = [
    '# Result',
    '',
    '**注意：**内容',
    '',
    '- [x] complete',
    '- [ ] pending',
    '',
    '| Item | Value |',
    '| --- | ---: |',
    '| bound | finite |',
    '',
    '> Important',
  ].join('\n');
  const html = render(source);

  assert.equal(engine, 'micromark-mdast');
  assert.equal(ready(), true);
  assert.match(html, /<h1>Result<\/h1>/u);
  assert.match(html, /<strong>注意：<\/strong>内容/u);
  assert.equal(count(html, /type="checkbox"/gu), 2);
  assert.match(html, /<div class="markdown-table-scroll"><table>/u);
  assert.match(html, /text-align:right/u);
  assert.match(html, /<blockquote>/u);
});

test('renders all supported math delimiters through one AST node path', () => {
  const source = [
    'Inline \\(x_i\\), dollar $y_i$, and:',
    '',
    '\\[',
    'p(s)=\\begin{cases}',
    'a,&0\\le s<s_0,\\\\',
    'b,&s\\ge s_0,',
    '\\end{cases}',
    '\\]',
    '',
    '$$j(r)=\\gamma\\,\\operatorname{sgn}(r)\\sqrt{|r|}.$$',
  ].join('\n');
  const root = parse(source);
  const html = render(source);

  assert.equal(root.children.filter((node) => node.type === 'math').length, 2);
  assert.equal(count(html, /class="katex"/gu), 4);
  assert.equal(count(html, /class="katex-display"/gu), 2);
  assert.doesNotMatch(html, /class="katex-error"/u);
  assert.match(html, /annotation encoding="application\/x-tex">x_i<\/annotation>/u);
  assert.match(html, /\\begin\{cases\}/u);
  assert.match(html, /\\operatorname\{sgn\}/u);
});

test('keeps one formula node per mathematical GFM table cell', () => {
  const source = [
    '| Operator | Recommendation |',
    '| --- | --- |',
    '| \\(\\Psi_i=\\eta_i\\) | exact recovery |',
    '| \\(\\Psi_i=e_i\\) | standard integral |',
    '| \\(\\Psi_i=\\vartheta_{i,\\nu_i}(k_i)e_i\\) | bounded scheduling |',
    '| \\(\\Psi_i=\\delta_i\\tanh(e_i/\\gamma_i)\\) | nonlinear gain |',
    '| \\(\\Psi_i=e_i-\\sigma_i z_i\\) | leakage |',
  ].join('\n');
  const html = render(source);

  assert.equal(count(html, /<tr>/gu), 6);
  assert.equal(count(html, /class="katex"/gu), 5);
  assert.equal(count(html, /<td><span class="katex">/gu), 5);
});

test('does not interpret TeX or dollars inside code', () => {
  const html = render([
    '`$HOME and \\(x\\)`',
    '',
    '```tex',
    '\\[not_math_inside_code\\]',
    '$also_not_math$',
    '```',
  ].join('\n'));

  assert.equal(count(html, /class="katex"/gu), 0);
  assert.match(html, /<code>\$HOME and \\\(x\\\)<\/code>/u);
  assert.match(html, /<code class="language-tex">/u);
  assert.match(html, /\$also_not_math\$/u);
});

test('neutralizes raw HTML, dangerous protocols, and unsupported images', () => {
  const html = render([
    '<img src=x onerror="globalThis.pwned=1">',
    '[run](javascript:alert(1))',
    '![payload](data:text/plain,boom)',
  ].join('\n\n'));

  assert.doesNotMatch(html, /<img src=x/iu);
  assert.doesNotMatch(html, /href="javascript:/iu);
  assert.doesNotMatch(html, /src="data:/iu);
  assert.match(html, /&lt;img src=x onerror=/u);
  assert.match(html, /<span class="markdown-image-alt">payload<\/span>/u);
});

test('routes explicit local links and images through owner callbacks', () => {
  const html = render(
    '[paper](/home/user/paper.tex:17) ![plot](/home/user/plot.png)',
    {
      localFileHref: (path, line) => '/view?path=' + encodeURIComponent(path) + '&line=' + line,
      localImageHref: (path) => '/image?path=' + encodeURIComponent(path),
    },
  );

  assert.deepEqual(localReference('/home/user/paper.tex:17'), {
    path: '/home/user/paper.tex',
    line: 17,
    column: 0,
  });
  assert.match(html, /class="file-link markdown-file-link"/u);
  assert.match(html, /href="\/view\?path=%2Fhome%2Fuser%2Fpaper\.tex&amp;line=17"/u);
  assert.match(html, /src="\/image\?path=%2Fhome%2Fuser%2Fplot\.png"/u);
});

test('streaming grammar leaves incomplete and complete TeX literal', () => {
  for (const source of ['partial \\(x_i', 'complete \\(x_i\\)', '$$x^2$$']) {
    const html = render(source, {}, { mode: 'streaming' });
    assert.equal(count(html, /class="katex"/gu), 0);
  }
  assert.match(render('complete \\(x_i\\)', {}, { mode: 'streaming' }), /complete \(x_i\)/u);
  assert.match(render('complete \\(x_i\\)'), /class="katex"/u);
});

test('delegates settled fenced code to a highlighter and preserves streaming fallback', () => {
  const calls = [];
  setHighlighter({
    highlight(code, language) {
      calls.push({ code, language });
      return '<pre class="shiki"><code><span>highlighted</span></code></pre>';
    },
  });
  try {
    const settled = render('```c++\nint main() {}\n```');
    const streaming = render('```c++\nint main() {}\n```', {}, { mode: 'streaming' });

    assert.deepEqual(calls, [{ code: 'int main() {}', language: 'c++' }]);
    assert.match(settled, /class="markdown-code-block"/u);
    assert.match(settled, /class="shiki"/u);
    assert.match(settled, />c\+\+</u);
    assert.doesNotMatch(streaming, /class="shiki"/u);
    assert.match(streaming, /class="language-c\+\+"/u);
  } finally {
    setHighlighter(null);
  }
});

test('committed browser bundle exposes the same engine API', async () => {
  const bundle = await readFile(new URL(
    '../../../apps/owner/local-tmux-owner/static/vendor/markdown-ast/markdown-ast.min.js',
    import.meta.url,
  ), 'utf8');
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
  vm.runInNewContext(bundle, context, { filename: 'markdown-ast.min.js' });

  assert.equal(context.FaryoMarkdownAst.ready(), true);
  assert.match(context.FaryoMarkdownAst.render('$x$'), /class="katex"/u);
});
