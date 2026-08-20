import assert from "node:assert/strict";
import test from "node:test";

import { goalViewModel, renderGoalStatus } from "../static/owner/goal-status.mjs";

test("goal status is compact and never uses objective text", () => {
  const model = goalViewModel({
    status: "active",
    objective: "private objective",
    timeUsedSeconds: 9_000,
  });

  assert.deepEqual(model, {
    visible: true,
    compact: "Goal Active",
    detail: "Active · 2h 30m",
    tone: "active",
  });
  assert.doesNotMatch(JSON.stringify(model), /private objective/);
});

test("complete, blocked, limited, and missing goals stay distinct", () => {
  assert.equal(goalViewModel({ status: "complete" }).compact, "Goal Done");
  assert.equal(goalViewModel({ status: "blocked" }).tone, "blocked");
  assert.equal(goalViewModel({ status: "usage_limited" }).detail, "Usage limited");
  assert.deepEqual(goalViewModel(null), {
    visible: false,
    compact: "",
    detail: "No goal",
    tone: "none",
  });
});

test("renderer replaces prior tone and hides cleared goals", () => {
  const classes = new Set(["pill", "goal-pill", "goal-active"]);
  const pill = {
    hidden: false,
    textContent: "Goal Active",
    title: "",
    attributes: new Map(),
    classList: {
      add: (value) => classes.add(value),
      remove: (value) => classes.delete(value),
    },
    setAttribute(name, value) { this.attributes.set(name, value); },
    removeAttribute(name) { this.attributes.delete(name); },
  };
  const details = { textContent: "" };

  renderGoalStatus({ status: "blocked", timeUsedSeconds: 90 }, { pill, details });
  assert.equal(pill.textContent, "Goal Blocked");
  assert.equal(details.textContent, "Blocked · 1m");
  assert.equal(classes.has("goal-active"), false);
  assert.equal(classes.has("goal-blocked"), true);

  renderGoalStatus({ status: "none" }, { pill, details });
  assert.equal(pill.hidden, true);
  assert.equal(pill.textContent, "");
  assert.equal(details.textContent, "No goal");
});
