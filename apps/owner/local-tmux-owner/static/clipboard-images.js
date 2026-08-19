(function initClipboardImages(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.FaryoClipboardImages = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function clipboardImagesFactory() {
  'use strict';

  function isImageFile(file) {
    return Boolean(file && /^image\//i.test(String(file.type || '')));
  }

  function filesFromClipboard(data) {
    if (!data) return [];
    const fromItems = Array.from(data.items || [])
      .filter((item) => item && item.kind === 'file' && /^image\//i.test(String(item.type || '')))
      .map((item) => {
        try { return item.getAsFile(); } catch (_) { return null; }
      })
      .filter(isImageFile);
    if (fromItems.length) return fromItems;
    return Array.from(data.files || []).filter(isImageFile);
  }

  function plainTextFromClipboard(data) {
    if (!data || typeof data.getData !== 'function') return '';
    try { return String(data.getData('text/plain') || ''); } catch (_) { return ''; }
  }

  function insertText(value, start, end, text) {
    const source = String(value || '');
    const from = Math.max(0, Math.min(source.length, Number.isFinite(start) ? start : source.length));
    const to = Math.max(from, Math.min(source.length, Number.isFinite(end) ? end : from));
    const inserted = String(text || '');
    return {
      value: source.slice(0, from) + inserted + source.slice(to),
      selectionStart: from + inserted.length,
    };
  }

  return { isImageFile, filesFromClipboard, plainTextFromClipboard, insertText };
});
