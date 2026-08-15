(() => {
  'use strict';

  function frameBoundary(value) {
    const match = /\r?\n\r?\n/.exec(value);
    return match ? { index: match.index, length: match[0].length } : null;
  }

  function decodeFrame(frame) {
    let type = 'message';
    const data = [];
    for (const line of String(frame || '').split(/\r?\n/)) {
      if (!line || line.startsWith(':')) continue;
      const separator = line.indexOf(':');
      const field = separator < 0 ? line : line.slice(0, separator);
      let value = separator < 0 ? '' : line.slice(separator + 1);
      if (value.startsWith(' ')) value = value.slice(1);
      if (field === 'event') type = value || 'message';
      else if (field === 'data') data.push(value);
    }
    return data.length ? { type, data: data.join('\n') } : null;
  }

  function createParser(onEvent) {
    if (typeof onEvent !== 'function') throw new TypeError('onEvent must be a function');
    let buffer = '';
    const dispatch = (frame) => {
      const event = decodeFrame(frame);
      if (event) onEvent(event);
    };
    return {
      push(chunk, final = false) {
        buffer += String(chunk || '');
        let boundary;
        while ((boundary = frameBoundary(buffer))) {
          dispatch(buffer.slice(0, boundary.index));
          buffer = buffer.slice(boundary.index + boundary.length);
        }
        if (final && buffer.trim()) {
          dispatch(buffer);
          buffer = '';
        }
      },
    };
  }

  const api = Object.freeze({ version: '1', createParser, decodeFrame });
  if (typeof module === 'object' && module.exports) module.exports = api;
  globalThis.FaryoEventStream = api;
})();
