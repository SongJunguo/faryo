(function (root, factory) {
  'use strict';

  let MarkdownIt = root && root.markdownit;
  if (!MarkdownIt && typeof module === 'object' && module.exports) {
    MarkdownIt = require('./vendor/markdown-it/markdown-it.min.js');
  }
  const api = factory(MarkdownIt);
  if (root) root.FaryoMarkdown = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : null, function (MarkdownIt) {
  'use strict';

  const MATH_ENVIRONMENTS = 'equation\\*?|align\\*?|alignat\\*?|gather\\*?|CD';
  const LOCAL_PATH_RE = /^(?:\/(?:home|root|workspace|workspaces|tmp|Users|mnt|opt|srv)\/|~\/|\.{1,2}\/)/u;

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char]);
  }

  function mark(mask, start, end) {
    for (let index = Math.max(0, start); index < Math.min(mask.length, end); index += 1) mask[index] = 1;
  }

  function markInlineCode(line, offset, mask) {
    let cursor = 0;
    while (cursor < line.length) {
      const open = line.indexOf('`', cursor);
      if (open < 0) return;
      let width = 1;
      while (line[open + width] === '`') width += 1;
      const marker = '`'.repeat(width);
      const close = line.indexOf(marker, open + width);
      if (close < 0) {
        mark(mask, offset + open, offset + line.length);
        return;
      }
      mark(mask, offset + open, offset + close + width);
      cursor = close + width;
    }
  }

  function codeMask(source) {
    const mask = new Uint8Array(source.length);
    const lines = source.match(/[^\n]*(?:\n|$)/gu) || [];
    let offset = 0;
    let fence = null;

    for (const segment of lines) {
      if (!segment) continue;
      const line = segment.endsWith('\n') ? segment.slice(0, -1) : segment;
      const fenceMatch = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/u);
      if (fence) {
        mark(mask, offset, offset + segment.length);
        if (fenceMatch && fenceMatch[1][0] === fence.char && fenceMatch[1].length >= fence.width && !fenceMatch[2].trim()) fence = null;
      } else if (fenceMatch) {
        mark(mask, offset, offset + segment.length);
        fence = { char: fenceMatch[1][0], width: fenceMatch[1].length };
      } else if (/^(?: {4}|\t)/u.test(line)) {
        mark(mask, offset, offset + segment.length);
      } else {
        markInlineCode(line, offset, mask);
      }
      offset += segment.length;
    }
    return mask;
  }

  function escapedAt(source, index) {
    let slashes = 0;
    for (let cursor = index - 1; cursor >= 0 && source[cursor] === '\\'; cursor -= 1) slashes += 1;
    return slashes % 2 === 1;
  }

  function unmaskedAt(mask, start, length) {
    for (let index = start; index < start + length; index += 1) {
      if (mask[index]) return false;
    }
    return true;
  }

  function findClose(source, marker, start, mask) {
    let index = source.indexOf(marker, start);
    while (index >= 0) {
      if (unmaskedAt(mask, index, marker.length) && !escapedAt(source, index)) return index;
      index = source.indexOf(marker, index + 1);
    }
    return -1;
  }

  function protectMath(text) {
    const source = String(text || '');
    const mask = codeMask(source);
    let prefix = 'FARYOMATHPLACEHOLDER';
    while (source.includes(prefix)) prefix += 'X';
    const segments = [];
    let output = '';
    let cursor = 0;
    let index = 0;

    const save = (start, end) => {
      const token = `\uE000${prefix}${segments.length}\uE001`;
      output += source.slice(cursor, start) + token;
      segments.push({ token, value: source.slice(start, end) });
      cursor = end;
      index = end;
    };

    while (index < source.length) {
      if (mask[index]) {
        index += 1;
        continue;
      }

      const environment = source.slice(index).match(new RegExp(`^\\\\begin\\{(${MATH_ENVIRONMENTS})\\}`, 'u'));
      if (environment && !escapedAt(source, index)) {
        const closeMarker = `\\end{${environment[1]}}`;
        const close = findClose(source, closeMarker, index + environment[0].length, mask);
        if (close >= 0) {
          save(index, close + closeMarker.length);
          continue;
        }
      }

      let opener = '';
      let closer = '';
      if (source.startsWith('$$', index) && !escapedAt(source, index)) {
        opener = closer = '$$';
      } else if (source.startsWith('\\[', index) && !escapedAt(source, index)) {
        opener = '\\[';
        closer = '\\]';
      } else if (source.startsWith('\\(', index) && !escapedAt(source, index)) {
        opener = '\\(';
        closer = '\\)';
      }
      if (opener) {
        const close = findClose(source, closer, index + opener.length, mask);
        if (close >= 0) {
          save(index, close + closer.length);
          continue;
        }
      }
      index += 1;
    }

    output += source.slice(cursor);
    return { text: output, segments };
  }

  function restoreMath(html, segments) {
    let output = String(html || '');
    for (const segment of segments || []) output = output.split(segment.token).join(escapeHtml(segment.value));
    return output;
  }

  function addClass(token, name) {
    const current = token.attrGet('class');
    token.attrSet('class', current ? `${current} ${name}` : name);
  }

  function decodeTarget(value) {
    try { return decodeURIComponent(String(value || '')); }
    catch (_error) { return String(value || ''); }
  }

  function localReference(value) {
    const target = decodeTarget(value).split('#', 1)[0];
    if (target.startsWith('//') || !LOCAL_PATH_RE.test(target)) return null;
    const match = target.match(/^(.*?)(?::(\d+)(?::(\d+))?)?$/u);
    return match ? { path: match[1], line: Number(match[2] || 0), column: Number(match[3] || 0) } : null;
  }

  function createParser() {
    if (typeof MarkdownIt !== 'function') return null;
    const parser = MarkdownIt({ html: false, breaks: true, linkify: true, typographer: false });
    const validateLink = parser.validateLink.bind(parser);
    parser.validateLink = (url) => !/^\s*data:/iu.test(String(url || '')) && validateLink(url);

    const defaultLinkOpen = parser.renderer.rules.link_open || ((tokens, index, options, _env, self) => self.renderToken(tokens, index, options));
    parser.renderer.rules.link_open = (tokens, index, options, env, self) => {
      const token = tokens[index];
      const href = token.attrGet('href') || '';
      const local = localReference(href);
      if (local && typeof env.localFileHref === 'function') {
        token.attrSet('href', env.localFileHref(local.path, local.line, local.column));
        addClass(token, 'file-link markdown-file-link');
      } else if (/^https?:\/\//iu.test(href)) {
        token.attrSet('target', '_blank');
        token.attrSet('rel', 'noopener noreferrer');
      }
      return defaultLinkOpen(tokens, index, options, env, self);
    };

    const defaultImage = parser.renderer.rules.image;
    parser.renderer.rules.image = (tokens, index, options, env, self) => {
      const token = tokens[index];
      const src = token.attrGet('src') || '';
      const local = localReference(src);
      if (local && typeof env.localImageHref === 'function') token.attrSet('src', env.localImageHref(local.path));
      token.attrSet('loading', 'lazy');
      token.attrSet('referrerpolicy', 'no-referrer');
      addClass(token, 'chat-image chat-markdown-image');
      return defaultImage(tokens, index, options, env, self);
    };
    return parser;
  }

  const parser = createParser();

  function ready() {
    return Boolean(parser);
  }

  function render(text, env = {}) {
    const source = String(text || '');
    if (!parser) return escapeHtml(source).replace(/\n/gu, '<br>');
    const protectedSource = protectMath(source);
    try {
      return restoreMath(parser.render(protectedSource.text, env), protectedSource.segments);
    } catch (_error) {
      return escapeHtml(source).replace(/\n/gu, '<br>');
    }
  }

  return { escapeHtml, localReference, protectMath, restoreMath, ready, render };
});
