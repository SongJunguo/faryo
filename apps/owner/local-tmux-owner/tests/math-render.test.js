'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const installedSource = path.join(__dirname, '../static/math-render.js');
const sourcePath = fs.existsSync(installedSource) ? installedSource : path.join(__dirname, 'math-render.js');
const math = require(sourcePath);

const cases = [
  ['single variable', 'Use $x$ here.', 'Use \\(x\\) here.'],
  ['subscript', 'Let $L_B$ be bounded.', 'Let \\(L_B\\) be bounded.'],
  ['latex command', 'Take $\\eta_i$.', 'Take \\(\\eta_i\\).'],
  ['function', 'Assume $V(x)>0$.', 'Assume \\(V(x)>0\\).'],
  ['display dollar untouched', '$$x^2+y^2$$', '$$x^2+y^2$$'],
  ['paren latex untouched', '\\(x+y\\)', '\\(x+y\\)'],
  ['shell pair rejected', 'echo "$HOME and $PATH"', 'echo "$HOME and $PATH"'],
  ['home token rejected', 'literal $HOME$ token', 'literal $HOME$ token'],
  ['inline code skipped', 'Run `echo $x$` now.', 'Run `echo $x$` now.'],
  ['indented code skipped', '    echo $x$', '    echo $x$'],
  ['escaped dollar skipped', 'Price \\$x$ stays.', 'Price \\$x$ stays.'],
  ['multiple formulas', '$x$ and $y$', '\\(x\\) and \\(y\\)'],
];

for (const [name, input, expected] of cases) {
  assert.equal(math.normalizeInlineDollarMath(input), expected, name);
}

assert.equal(
  math.normalizeInlineDollarMath('Before $x$\n```bash\necho $y$\n```\nAfter $z$'),
  'Before \\(x\\)\n```bash\necho $y$\n```\nAfter \\(z\\)'
);

assert.equal(math.ready(), false);
assert.equal(math.prepareText('Use $x$ here.'), 'Use $x$ here.');

const browserSource = fs.readFileSync(sourcePath, 'utf8');
const calls = [];
const browserWindow = {
  renderMathInElement(element, options) {
    calls.push({ element, options });
  },
};
const context = {
  window: browserWindow,
  module: { exports: {} },
  console,
};
vm.runInNewContext(browserSource, context, { filename: 'math-render.js' });
const browserMath = browserWindow.FaryoMath;
assert.equal(browserMath.ready(), true);
assert.equal(browserMath.prepareText('Use $x$ here.'), 'Use \\(x\\) here.');
const fakeBlocks = [{ id: 1 }, { id: 2 }];
assert.equal(browserMath.renderOutput({ querySelectorAll: () => fakeBlocks }), true);
assert.equal(calls.length, 2);
assert.equal(calls[0].element, fakeBlocks[0]);
assert.equal(calls[0].options.trust, false);
assert.equal(calls[0].options.delimiters.some((item) => item.left === '$'), false);

console.log('math-render tests passed');
