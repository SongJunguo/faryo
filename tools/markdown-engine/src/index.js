import katex from 'katex';
import { fromMarkdown } from 'mdast-util-from-markdown';
import { gfmFromMarkdown } from 'mdast-util-gfm';
import { mathFromMarkdown } from 'mdast-util-math';
import { gfm } from 'micromark-extension-gfm';
import { math } from 'micromark-extension-math';
import { cjkFriendlyStrong } from './cjk-friendly-strong.js';
import { mathCompatibility } from './math-compatibility.js';

const LOCAL_PATH_RE = /^(?:\/(?:home|root|workspace|workspaces|tmp|Users|mnt|opt|srv)\/|~\/|\.{1,2}\/)/u;
const SAFE_ALIGNMENTS = new Set(['left', 'right', 'center']);
const STREAMING_EXTENSIONS = [gfm(), cjkFriendlyStrong()];
const STREAMING_MDAST_EXTENSIONS = [gfmFromMarkdown()];
const SETTLED_EXTENSIONS = [
  gfm(),
  cjkFriendlyStrong(),
  mathCompatibility(),
  math(),
];
const SETTLED_MDAST_EXTENSIONS = [gfmFromMarkdown(), mathFromMarkdown()];
let codeHighlighter = null;

export const engine = 'micromark-mdast';
export const version = '1';

export function setHighlighter(value) {
  codeHighlighter = value && typeof value.highlight === 'function' ? value : null;
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/gu, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character]);
}

function decodeTarget(value) {
  try {
    return decodeURIComponent(String(value ?? ''));
  } catch {
    return String(value ?? '');
  }
}

export function localReference(value) {
  const target = decodeTarget(value).split('#', 1)[0];
  if (target.startsWith('//') || !LOCAL_PATH_RE.test(target)) return null;
  const match = target.match(/^(.*?)(?::(\d+)(?::(\d+))?)?$/u);
  if (!match) return null;
  return {
    path: match[1],
    line: Number(match[2] || 0),
    column: Number(match[3] || 0),
  };
}

export function parse(text, options = {}) {
  const source = String(text ?? '');
  if (options.mode === 'streaming') {
    return fromMarkdown(source, {
      extensions: STREAMING_EXTENSIONS,
      mdastExtensions: STREAMING_MDAST_EXTENSIONS,
    });
  }
  return fromMarkdown(source, {
    extensions: SETTLED_EXTENSIONS,
    mdastExtensions: SETTLED_MDAST_EXTENSIONS,
  });
}

function collectDefinitions(nodes, definitions = new Map()) {
  for (const node of nodes || []) {
    if (node.type === 'definition') {
      const identifier = String(node.identifier || '').toUpperCase();
      if (!definitions.has(identifier)) definitions.set(identifier, node);
    }
    if (Array.isArray(node.children)) collectDefinitions(node.children, definitions);
  }
  return definitions;
}

function safeExternalUrl(value, allowedProtocols) {
  try {
    const url = new URL(String(value ?? ''));
    return allowedProtocols.has(url.protocol) ? String(value) : '';
  } catch {
    return '';
  }
}

function callbackTarget(value) {
  if (value && typeof value === 'object') {
    return {
      href: String(value.href ?? ''),
      fetchHref: String(value.fetchHref ?? ''),
    };
  }
  return { href: String(value ?? ''), fetchHref: '' };
}

function linkTarget(value, environment) {
  const local = localReference(value);
  if (local && typeof environment.localFileHref === 'function') {
    const target = callbackTarget(environment.localFileHref(local.path, local.line, local.column));
    return {
      href: target.href || target.fetchHref,
      fetchHref: target.fetchHref,
      className: 'file-link markdown-file-link',
      external: false,
    };
  }
  const href = safeExternalUrl(value, new Set(['http:', 'https:', 'mailto:']));
  return {
    href,
    fetchHref: '',
    className: '',
    external: /^https?:/iu.test(href),
  };
}

function imageTarget(value, environment) {
  const local = localReference(value);
  if (local && typeof environment.localImageHref === 'function') {
    const target = callbackTarget(environment.localImageHref(local.path));
    return { src: target.href, fetchSrc: target.fetchHref };
  }
  return {
    src: safeExternalUrl(value, new Set(['http:', 'https:'])),
    fetchSrc: '',
  };
}

function renderMath(value, displayMode) {
  const source = String(value ?? '');
  try {
    return katex.renderToString(source, {
      displayMode,
      output: 'htmlAndMathml',
      strict: 'warn',
      throwOnError: true,
      trust: false,
    });
  } catch (firstError) {
    try {
      return katex.renderToString(source, {
        displayMode,
        errorColor: '#cc0000',
        output: 'htmlAndMathml',
        strict: 'ignore',
        throwOnError: false,
        trust: false,
      });
    } catch {
      const title = escapeHtml(String(firstError));
      return '<span class="katex-error" style="color:#cc0000" title="'
        + title + '">' + escapeHtml(source) + '</span>';
    }
  }
}

function renderLink(url, title, content, context) {
  const target = linkTarget(url, context.environment);
  if (!target.href) return content;
  const attributes = [
    'href="' + escapeHtml(target.href) + '"',
  ];
  if (title) attributes.push('title="' + escapeHtml(title) + '"');
  if (target.className) attributes.push('class="' + target.className + '"');
  if (target.fetchHref) {
    attributes.push('data-faryo-fetch-href="' + escapeHtml(target.fetchHref) + '"');
  }
  if (target.external) {
    attributes.push('target="_blank"');
    attributes.push('rel="noopener noreferrer"');
  }
  return '<a ' + attributes.join(' ') + '>' + content + '</a>';
}

function renderImage(url, title, alt, context) {
  const target = imageTarget(url, context.environment);
  if (!target.src && !target.fetchSrc) {
    return '<span class="markdown-image-alt">' + escapeHtml(alt) + '</span>';
  }
  const attributes = [
    'class="chat-image chat-markdown-image"',
    'alt="' + escapeHtml(alt) + '"',
    'loading="lazy"',
    'decoding="async"',
    'referrerpolicy="no-referrer"',
  ];
  if (target.src) attributes.push('src="' + escapeHtml(target.src) + '"');
  if (target.fetchSrc) {
    attributes.push('data-faryo-fetch-src="' + escapeHtml(target.fetchSrc) + '"');
    attributes.push('aria-busy="true"');
  }
  if (title) attributes.push('title="' + escapeHtml(title) + '"');
  return '<img ' + attributes.join(' ') + '>';
}

function referenceSuffix(node) {
  if (node.referenceType === 'collapsed') return '][]';
  if (node.referenceType === 'full') {
    return '][' + escapeHtml(node.label ?? node.identifier ?? '') + ']';
  }
  return ']';
}

function renderInlineNodes(nodes, context) {
  return (nodes || []).map((node) => renderNode(node, context, true)).join('');
}

function renderBlockNodes(nodes, context) {
  return (nodes || [])
    .map((node) => renderNode(node, context, false))
    .filter(Boolean)
    .join('\n');
}

function listIsLoose(node) {
  return Boolean(node.spread)
    || (node.children || []).some((item) => Boolean(item.spread) || item.children.length > 1);
}

function renderListItem(item, context, loose) {
  const children = item.children || [];
  const task = typeof item.checked === 'boolean';
  let checkbox = '';
  if (task) {
    checkbox = '<input type="checkbox" disabled'
      + (item.checked ? ' checked' : '') + '> ';
  }
  const body = children.map((child, index) => {
    if (child.type === 'paragraph' && !loose) {
      const content = renderInlineNodes(child.children, context);
      return (index === 0 ? checkbox : '') + content;
    }
    const content = renderNode(child, context, false);
    if (index === 0 && checkbox) {
      if (child.type === 'paragraph') {
        return '<p>' + checkbox + renderInlineNodes(child.children, context) + '</p>';
      }
      return checkbox + content;
    }
    return content;
  }).join('\n');
  const className = task ? ' class="task-list-item"' : '';
  return '<li' + className + '>' + (children.length ? body : checkbox) + '</li>';
}

function renderList(node, context) {
  const ordered = Boolean(node.ordered);
  const tag = ordered ? 'ol' : 'ul';
  const loose = listIsLoose(node);
  const taskList = (node.children || []).some((item) => typeof item.checked === 'boolean');
  const attributes = [];
  if (ordered && typeof node.start === 'number' && node.start !== 1) {
    attributes.push('start="' + String(node.start) + '"');
  }
  if (taskList) attributes.push('class="contains-task-list"');
  const opening = attributes.length ? '<' + tag + ' ' + attributes.join(' ') + '>' : '<' + tag + '>';
  return opening
    + (node.children || []).map((item) => renderListItem(item, context, loose)).join('\n')
    + '</' + tag + '>';
}

function renderTableRow(row, cellTag, alignments, context) {
  const columns = alignments?.length || row.children.length;
  const cells = [];
  for (let index = 0; index < columns; index += 1) {
    const cell = row.children[index];
    const alignment = alignments?.[index];
    const style = SAFE_ALIGNMENTS.has(alignment)
      ? ' style="text-align:' + alignment + '"'
      : '';
    cells.push('<' + cellTag + style + '>'
      + (cell ? renderInlineNodes(cell.children, context) : '')
      + '</' + cellTag + '>');
  }
  return '<tr>' + cells.join('') + '</tr>';
}

function renderTable(node, context) {
  const rows = node.children || [];
  const alignments = Array.isArray(node.align) ? node.align : null;
  const head = rows[0]
    ? '<thead>' + renderTableRow(rows[0], 'th', alignments, context) + '</thead>'
    : '';
  const body = rows.length > 1
    ? '<tbody>' + rows.slice(1)
      .map((row) => renderTableRow(row, 'td', alignments, context))
      .join('') + '</tbody>'
    : '';
  return '<div class="markdown-table-scroll"><table>' + head + body + '</table></div>';
}

function renderNode(node, context, inline) {
  switch (node.type) {
    case 'root':
      return renderBlockNodes(node.children, context);
    case 'text':
      return escapeHtml(node.value);
    case 'paragraph':
      return '<p>' + renderInlineNodes(node.children, context) + '</p>';
    case 'heading':
      return '<h' + node.depth + '>'
        + renderInlineNodes(node.children, context)
        + '</h' + node.depth + '>';
    case 'blockquote':
      return '<blockquote>\n' + renderBlockNodes(node.children, context) + '\n</blockquote>';
    case 'thematicBreak':
      return '<hr>';
    case 'break':
      return '<br>\n';
    case 'strong':
      return '<strong>' + renderInlineNodes(node.children, context) + '</strong>';
    case 'emphasis':
      return '<em>' + renderInlineNodes(node.children, context) + '</em>';
    case 'delete':
      return '<del>' + renderInlineNodes(node.children, context) + '</del>';
    case 'inlineCode':
      return '<code>' + escapeHtml(String(node.value ?? '').replace(/\r?\n|\r/gu, ' ')) + '</code>';
    case 'code': {
      const language = /^[A-Za-z0-9_+#.-]+/u.exec(String(node.lang || ''))?.[0] || '';
      if (context.mode === 'settled' && language === 'math') {
        return renderMath(String(node.value ?? '') + '\n', true);
      }
      const highlighted = context.mode === 'settled' && language && codeHighlighter
        ? codeHighlighter.highlight(String(node.value ?? ''), language)
        : '';
      const className = language ? ' class="language-' + escapeHtml(language) + '"' : '';
      const code = highlighted
        || '<pre><code' + className + '>' + escapeHtml(node.value) + '</code></pre>';
      if (!language) return code;
      return '<div class="markdown-code-block">'
        + '<div class="markdown-code-banner"><span class="markdown-code-language">'
        + escapeHtml(language)
        + '</span><button class="markdown-code-copy" type="button" aria-label="Copy code">Copy</button></div>'
        + '<div class="markdown-code-content">' + code + '</div></div>';
    }
    case 'inlineMath':
      return context.mode === 'streaming'
        ? escapeHtml(node.value)
        : renderMath(node.value, false);
    case 'math':
      return context.mode === 'streaming'
        ? escapeHtml(node.value)
        : renderMath(node.value, true);
    case 'link': {
      const content = renderInlineNodes(node.children, { ...context, inLink: true });
      return renderLink(node.url, node.title, content, context);
    }
    case 'linkReference': {
      const content = renderInlineNodes(node.children, { ...context, inLink: true });
      const definition = context.definitions.get(String(node.identifier || '').toUpperCase());
      if (!definition) return '[' + content + referenceSuffix(node);
      return renderLink(definition.url, definition.title, content, context);
    }
    case 'image':
      return renderImage(node.url, node.title, node.alt || '', context);
    case 'imageReference': {
      const definition = context.definitions.get(String(node.identifier || '').toUpperCase());
      if (!definition) {
        return '![' + escapeHtml(node.alt || '') + referenceSuffix(node);
      }
      return renderImage(definition.url, definition.title, node.alt || '', context);
    }
    case 'list':
      return renderList(node, context);
    case 'listItem':
      return renderListItem(node, context, false);
    case 'table':
      return renderTable(node, context);
    case 'tableRow':
    case 'tableCell':
      return renderInlineNodes(node.children, context);
    case 'html':
      return escapeHtml(node.value);
    case 'definition':
      return '';
    default:
      if (Array.isArray(node.children)) {
        return inline
          ? renderInlineNodes(node.children, context)
          : renderBlockNodes(node.children, context);
      }
      return typeof node.value === 'string' ? escapeHtml(node.value) : '';
  }
}

export function ready() {
  return true;
}

export function render(text, environment = {}, options = {}) {
  const source = String(text ?? '');
  const mode = options.mode === 'streaming' ? 'streaming' : 'settled';
  try {
    const root = parse(source, { mode });
    const context = {
      definitions: collectDefinitions(root.children),
      environment,
      inLink: false,
      mode,
    };
    return renderBlockNodes(root.children, context);
  } catch {
    return escapeHtml(source).replace(/\n/gu, '<br>\n');
  }
}
