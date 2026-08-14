'use strict';

const assert = require('node:assert/strict');
const stableBlocks = require('../static/stable-blocks.js');

class FakeElement {
  constructor(label) {
    this.label = label;
    this.dataset = {};
    this.parent = null;
  }

  remove() {
    if (!this.parent) return;
    const index = this.parent.children.indexOf(this);
    if (index >= 0) this.parent.children.splice(index, 1);
    this.parent = null;
  }
}

class FakeContainer {
  constructor() {
    this.children = [];
  }

  insertBefore(node, reference) {
    node.remove();
    const index = reference ? this.children.indexOf(reference) : this.children.length;
    this.children.splice(index < 0 ? this.children.length : index, 0, node);
    node.parent = this;
  }
}

const initialBlocks = [
  { kind: 'user', text: 'Question' },
  { kind: 'output', text: 'Answer one' },
  { kind: 'user', text: 'Follow-up' },
  { kind: 'process', text: 'Working' },
  { kind: 'output', text: 'Partial' },
];
const firstPlan = stableBlocks.plan(initialBlocks, { mode: 'settled', revision: 0 });
assert.deepEqual(firstPlan.map((model) => model.stable), [true, true, true, false, false]);
assert.deepEqual(
  stableBlocks.plan(initialBlocks, { mode: 'settled', revision: 0 }).map((model) => model.key),
  firstPlan.map((model) => model.key),
);
assert.notDeepEqual(
  stableBlocks.plan(initialBlocks, { mode: 'streaming', revision: 0 }).map((model) => model.key),
  firstPlan.map((model) => model.key),
);

const container = new FakeContainer();
const createdNodes = [];
const createNode = (model) => {
  const node = new FakeElement(model.text);
  createdNodes.push(node);
  return node;
};
const firstResult = stableBlocks.reconcile(container, firstPlan, createNode);
const originalNodes = [...container.children];
assert.deepEqual(firstResult, { created: 5, reused: 0, removed: 0, stable: 3 });

const unchangedResult = stableBlocks.reconcile(container, firstPlan, createNode);
assert.deepEqual(unchangedResult, { created: 0, reused: 5, removed: 0, stable: 3 });
assert.deepEqual(container.children, originalNodes);

const appendedPlan = stableBlocks.plan([
  ...initialBlocks,
  { kind: 'status', text: 'Done' },
], { mode: 'settled', revision: 0 });
const appendedResult = stableBlocks.reconcile(container, appendedPlan, createNode);
assert.deepEqual(appendedResult, { created: 1, reused: 5, removed: 0, stable: 4 });
assert.deepEqual(container.children.slice(0, 5), originalNodes);

const changedTailPlan = stableBlocks.plan([
  ...initialBlocks,
  { kind: 'status', text: 'Complete' },
], { mode: 'settled', revision: 0 });
const changedResult = stableBlocks.reconcile(container, changedTailPlan, createNode);
assert.deepEqual(changedResult, { created: 1, reused: 5, removed: 1, stable: 4 });
assert.deepEqual(container.children.slice(0, 5), originalNodes);

const longContainer = new FakeContainer();
const longBlocks = Array.from({ length: 200 }, (_, index) => ({
  kind: index % 2 ? 'output' : 'user',
  text: `anonymous block ${index}`,
}));
const longFirst = stableBlocks.reconcile(
  longContainer,
  stableBlocks.plan(longBlocks, { mode: 'settled', revision: 0 }),
  createNode,
);
const longOriginalNodes = [...longContainer.children];
const longAppend = stableBlocks.reconcile(
  longContainer,
  stableBlocks.plan([...longBlocks, { kind: 'status', text: 'complete' }], {
    mode: 'settled',
    revision: 0,
  }),
  createNode,
);
assert.deepEqual(longFirst, { created: 200, reused: 0, removed: 0, stable: 198 });
assert.deepEqual(longAppend, { created: 1, reused: 200, removed: 0, stable: 199 });
assert.deepEqual(longContainer.children.slice(0, 200), longOriginalNodes);

console.log('stable-block reconciliation tests passed');
