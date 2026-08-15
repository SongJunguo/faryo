(() => {
  'use strict';

  const blockRe = /<oai-mem-citation\b[^>]*>([\s\S]*?)<\/oai-mem-citation\s*>/gi;
  const openingRe = /<oai-mem-citation\b[^>]*>/i;

  function cleanText(value) {
    return String(value || '')
      .replace(/<[^>]*>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function parseEntries(block) {
    const section = String(block || '').match(/<citation_entries\b[^>]*>([\s\S]*?)<\/citation_entries\s*>/i);
    if (!section) return [];
    return section[1].split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
      const match = line.match(/^(.+?)(?:\|note=\[([\s\S]*?)\])?$/);
      return {
        source: cleanText(match?.[1] || line).slice(0, 160),
        note: cleanText(match?.[2] || '').slice(0, 240),
      };
    }).filter((entry) => entry.source || entry.note);
  }

  function parse(value) {
    const source = String(value || '');
    const citations = [];
    let body = source.replace(blockRe, (_whole, inner) => {
      citations.push({ entries: parseEntries(inner), malformed: false });
      return '';
    });
    const incomplete = body.search(openingRe);
    if (incomplete >= 0) {
      body = body.slice(0, incomplete);
      citations.push({ entries: [], malformed: true });
    }
    body = body.replace(/\n{3,}/g, '\n\n').trim();
    return { body, citations };
  }

  function strip(value) {
    return parse(value).body;
  }

  const api = Object.freeze({ version: '1', parse, strip });
  if (typeof module === 'object' && module.exports) module.exports = api;
  globalThis.FaryoInternalAnnotations = api;
})();
