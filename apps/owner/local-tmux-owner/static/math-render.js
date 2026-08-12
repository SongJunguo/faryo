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

  function looksLikeTerminalDisplayMath(body) {
    const value = String(body || '').trim();
    if (!value || value.length > 8000 || /```|~~~/u.test(value)) return false;
    if (/["'`]/u.test(value)) return false;
    if (/\\[A-Za-z]+/u.test(value)) return true;
    return /[_^=<>+*/]/u.test(value) && /[A-Za-z0-9()[\]{}]/u.test(value);
  }

  function restoreTerminalRowBreaks(lines) {
    const values = Array.from(lines || [], (line) => String(line));
    if (!/\\begin\{(?:cases|aligned|alignedat|array|matrix|pmatrix|bmatrix|Bmatrix|vmatrix|Vmatrix|smallmatrix)\}/u.test(values.join('\n'))) {
      return values;
    }
    return values.map((line) => {
      const match = line.match(/(\\+)(\s*)$/u);
      if (!match || match[1].length % 2 === 0) return line;
      return `${line.slice(0, -(match[1].length + match[2].length))}${match[1]}\\${match[2]}`;
    });
  }

  function normalizeTerminalDisplayMath(text) {
    const lines = String(text || '').split('\n');
    const out = [];
    let fenceChar = '';

    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      const trimmed = line.trimStart();
      const fenceMatch = trimmed.match(/^(`{3,}|~{3,})/);
      if (fenceMatch) {
        const char = fenceMatch[1][0];
        if (!fenceChar) fenceChar = char;
        else if (fenceChar === char) fenceChar = '';
        out.push(line);
        continue;
      }
      if (fenceChar || line.trim() !== '[') {
        out.push(line);
        continue;
      }

      let close = index + 1;
      while (close < lines.length && close - index <= 80 && lines[close].trim() !== ']') close += 1;
      if (close >= lines.length || close - index > 80) {
        out.push(line);
        continue;
      }
      const bodyLines = restoreTerminalRowBreaks(lines.slice(index + 1, close));
      const body = bodyLines.join('\n');
      if (!looksLikeTerminalDisplayMath(body)) {
        out.push(line);
        continue;
      }
      out.push('\\[', ...bodyLines, '\\]');
      index = close;
    }
    return out.join('\n');
  }

  function replaceTerminalParenthesisMath(segment) {
    let out = '';
    let cursor = 0;
    while (cursor < segment.length) {
      const open = segment.indexOf('(', cursor);
      if (open < 0) {
        out += segment.slice(cursor);
        break;
      }
      out += segment.slice(cursor, open);
      const before = open > 0 ? segment[open - 1] : '';
      if (before === '\\' || before === '$' || /[A-Za-z0-9_]/u.test(before)) {
        out += '(';
        cursor = open + 1;
        continue;
      }
      let depth = 1;
      let close = open + 1;
      while (close < segment.length && depth > 0) {
        if (segment[close] === '(') depth += 1;
        else if (segment[close] === ')') depth -= 1;
        close += 1;
      }
      if (depth !== 0) {
        out += segment.slice(open);
        break;
      }
      const body = segment.slice(open + 1, close - 1);
      const after = segment[close] || '';
      if (!/[A-Za-z0-9_]/u.test(after) && looksLikeInlineMath(body)) out += `\\(${body}\\)`;
      else out += segment.slice(open, close);
      cursor = close;
    }
    return out;
  }

  function normalizeTerminalInlineMath(text) {
    const lines = String(text || '').split('\n');
    let fenceChar = '';
    let displayEnd = '';
    return lines.map((line) => {
      const trimmed = line.trimStart();
      const value = line.trim();
      const fenceMatch = trimmed.match(/^(`{3,}|~{3,})/);
      if (fenceMatch) {
        const char = fenceMatch[1][0];
        if (!fenceChar) fenceChar = char;
        else if (fenceChar === char) fenceChar = '';
        return line;
      }
      if (fenceChar) return line;
      if (displayEnd) {
        if (value === displayEnd) displayEnd = '';
        return line;
      }
      if (value === '\\[') {
        displayEnd = '\\]';
        return line;
      }
      if (value === '$$') {
        displayEnd = '$$';
        return line;
      }
      const begin = value.match(/^\\begin\{(equation|align|alignat|gather|CD)\}/u);
      if (begin) {
        if (!value.includes(`\\end{${begin[1]}}`)) displayEnd = `\\end{${begin[1]}}`;
        return line;
      }
      if (/^(?: {4}|\t)/u.test(line) || value.includes('$$')) return line;
      return transformOutsideInlineCode(line, replaceTerminalParenthesisMath);
    }).join('\n');
  }

  function normalizeTerminalMath(text) {
    return normalizeTerminalInlineMath(normalizeTerminalDisplayMath(text));
  }

  function ready() {
    return Boolean(root && typeof root.renderMathInElement === 'function');
  }

  function prepareText(text, options = {}) {
    if (!ready()) return String(text || '');
    const normalized = normalizeInlineDollarMath(text);
    return options.terminal === false ? normalized : normalizeTerminalMath(normalized);
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
    looksLikeTerminalDisplayMath,
    restoreTerminalRowBreaks,
    normalizeInlineDollarMath,
    normalizeTerminalDisplayMath,
    normalizeTerminalInlineMath,
    normalizeTerminalMath,
    prepareText,
    ready,
    renderElement,
    renderOutput,
  };
});
