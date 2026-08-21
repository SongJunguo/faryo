(() => {
  'use strict';

  function fingerprint(value) {
    const source = String(value ?? '');
    let hash = 0x811c9dc5;
    for (let index = 0; index < source.length; index += 1) {
      hash ^= source.charCodeAt(index);
      hash = Math.imul(hash, 0x01000193);
    }
    return (hash >>> 0).toString(36);
  }

  function plan(blocks, options = {}) {
    const source = Array.isArray(blocks) ? blocks : [];
    const mode = options.mode === 'streaming' ? 'streaming' : 'settled';
    const revision = Number.isFinite(options.revision) ? options.revision : 0;
    const tailCount = Math.max(0, Number.isFinite(options.tailCount) ? options.tailCount : 2);
    const stableLimit = Math.max(0, source.length - tailCount);
    const occurrences = new Map();

    return source.map((block, index) => {
      const kind = String(block?.kind || 'output');
      const text = String(block?.text ?? '');
      const signature = [mode, revision, kind, text].join('\u0000');
      const digest = fingerprint(signature);
      const keyHint = String(block?.keyHint || '');
      const mutable = Boolean(block?.mutable && keyHint);
      const identity = keyHint
        ? `h-${fingerprint([kind, keyHint].join('\u0000'))}`
        : `${digest}-${text.length.toString(36)}`;
      const occurrence = occurrences.get(identity) || 0;
      occurrences.set(identity, occurrence + 1);
      return {
        ...block,
        kind,
        text,
        signature,
        key: `b-${identity}-${occurrence.toString(36)}`,
        stable: index < stableLimit,
        mutable,
      };
    });
  }

  function reconcile(container, models, createNode) {
    if (!container || typeof createNode !== 'function') {
      throw new TypeError('A container and node factory are required');
    }
    const desired = Array.isArray(models) ? models : [];
    const buckets = new Map();
    for (const child of Array.from(container.children || [])) {
      const key = child.dataset?.faryoBlockKey;
      if (!key) continue;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(child);
    }

    const retained = new Set();
    let created = 0;
    let reused = 0;
    desired.forEach((model, index) => {
      const candidates = buckets.get(model.key) || [];
      let node = candidates.find((candidate) => (
        !retained.has(candidate)
        && (
          candidate.__faryoBlockSignature === model.signature
          || (model.mutable && candidate.dataset?.faryoBlockMutable === 'true')
        )
      ));
      if (node) {
        reused += 1;
      } else {
        node = createNode(model);
        if (!node || !node.dataset) throw new TypeError('Block factory must return an element');
        created += 1;
      }
      node.dataset.faryoBlockKey = model.key;
      node.dataset.faryoBlockStable = model.stable ? 'true' : 'false';
      node.dataset.faryoBlockMutable = model.mutable ? 'true' : 'false';
      node.__faryoBlockSignature = model.signature;
      retained.add(node);
      const current = container.children[index] || null;
      if (current !== node) container.insertBefore(node, current);
    });

    let removed = 0;
    for (const child of Array.from(container.children || [])) {
      if (retained.has(child)) continue;
      if (child.dataset?.faryoTransient) continue;
      child.remove();
      removed += 1;
    }
    return { created, reused, removed, stable: desired.filter((model) => model.stable).length };
  }

  const api = Object.freeze({ version: '1', fingerprint, plan, reconcile });
  if (typeof module === 'object' && module.exports) module.exports = api;
  globalThis.FaryoStableBlocks = api;
})();
