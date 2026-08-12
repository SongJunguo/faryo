(function (root, factory) {
  'use strict';

  const api = factory(root);
  if (root) root.FaryoMath = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : null, function (root) {
  'use strict';

  const MATH_BLOCK_SELECTOR = '.compact-block.output, .compact-block.user, .compact-block.plan';
  const DEFAULT_DELIMITERS = [
    { left: '$$', right: '$$', display: true },
    { left: '\\(', right: '\\)', display: false },
    { left: '\\begin{equation}', right: '\\end{equation}', display: true },
    { left: '\\begin{align}', right: '\\end{align}', display: true },
    { left: '\\begin{alignat}', right: '\\end{alignat}', display: true },
    { left: '\\begin{gather}', right: '\\end{gather}', display: true },
    { left: '\\begin{CD}', right: '\\end{CD}', display: true },
    { left: '\\[', right: '\\]', display: true },
  ];

  function looksLikeInlineMath(body) {
    const value = String(body || '');
    if (!value || value.trim() !== value || value.length > 240) return false;
    if (/[\r\n`"';&]/.test(value) || /(?:&&|\|\|)/.test(value)) return false;

    // Strong math signals: TeX commands/operators, scripts, grouping, relations,
    // arithmetic, function calls, set notation, etc.
    if (/\\[A-Za-z]+/.test(value)) return true;
    if (/[_^{}=<>+\-*/()[\]|,:]/.test(value)) return true;

    // Common atomic math tokens. Keeping this deliberately conservative avoids
    // treating shell variables such as $HOME ... $PATH as a single formula.
    if (/^[A-Za-z]\d*$/.test(value)) return true;
    if (/^[A-Za-z]{1,3}$/.test(value)) return true;
    if (/^\d+(?:\.\d+)?$/.test(value)) return true;
    if (/^[\u0370-\u03ff](?:_[A-Za-z0-9]+)?$/u.test(value)) return true;

    return false;
  }

  function replaceInlineDollarMath(segment) {
    return segment.replace(/(^|[^\\$])\$(?!\$)([^$\n]+?)\$(?!\$)/g, (match, prefix, body) => {
      if (!looksLikeInlineMath(body)) return match;
      return `${prefix}\\(${body}\\)`;
    });
  }

  function transformOutsideInlineCode(line, transform) {
    let out = '';
    let cursor = 0;

    while (cursor < line.length) {
      const tick = line.indexOf('`', cursor);
      if (tick < 0) {
        out += transform(line.slice(cursor));
        break;
      }

      out += transform(line.slice(cursor, tick));

      let width = 1;
      while (line[tick + width] === '`') width += 1;
      const marker = '`'.repeat(width);
      const close = line.indexOf(marker, tick + width);

      if (close < 0) {
        // Unclosed inline code: preserve the remainder rather than risk
        // interpreting shell/code dollars as math.
        out += line.slice(tick);
        break;
      }

      out += line.slice(tick, close + width);
      cursor = close + width;
    }

    return out;
  }

  function normalizeInlineDollarMath(text) {
    const lines = String(text || '').split('\n');
    let fenceChar = '';

    return lines.map((line) => {
      const trimmed = line.trimStart();
      const fenceMatch = trimmed.match(/^(`{3,}|~{3,})/);

      if (fenceMatch) {
        const char = fenceMatch[1][0];
        if (!fenceChar) fenceChar = char;
        else if (fenceChar === char) fenceChar = '';
        return line;
      }

      if (fenceChar || /^(?: {4}|\t)/.test(line)) return line;
      return transformOutsideInlineCode(line, replaceInlineDollarMath);
    }).join('\n');
  }

  function ready() {
    return Boolean(root && typeof root.renderMathInElement === 'function');
  }

  function prepareText(text) {
    return ready() ? normalizeInlineDollarMath(text) : String(text || '');
  }

  function renderElement(element) {
    if (!element || !ready()) return false;

    try {
      root.renderMathInElement(element, {
        delimiters: DEFAULT_DELIMITERS,
        throwOnError: false,
        strict: false,
        trust: false,
        ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'],
        ignoredClasses: ['math-ignore', 'file-link', 'chat-image-thumb', 'copy-output-block'],
        errorCallback: (message) => console.debug('Faryo math render skipped:', message),
      });
      return true;
    } catch (error) {
      console.debug('Faryo math render failed:', error);
      return false;
    }
  }

  function renderOutput(container) {
    if (!container || !ready()) return false;
    let rendered = false;
    for (const block of container.querySelectorAll(MATH_BLOCK_SELECTOR)) {
      rendered = renderElement(block) || rendered;
    }
    return rendered;
  }

  return {
    DEFAULT_DELIMITERS,
    looksLikeInlineMath,
    normalizeInlineDollarMath,
    prepareText,
    ready,
    renderElement,
    renderOutput,
  };
});
