import assert from "node:assert/strict";
import test from "node:test";

import { createApiClient, sessionApiPath } from "../static/owner/api-client.mjs";

function response(value, options = {}) {
  return {
    ok: options.ok !== false,
    status: options.status || 200,
    statusText: options.statusText || "OK",
    async json() { return value; },
    async text() { return typeof value === "string" ? value : JSON.stringify(value); },
  };
}

test("session API paths preserve queries and encode the selected session", () => {
  assert.equal(sessionApiPath("/api/status", "codex one"), "/api/status?session=codex%20one");
  assert.equal(sessionApiPath("/api/events?lines=320", "codex"), "/api/events?lines=320&session=codex");
  assert.equal(sessionApiPath("/asset.js", "codex"), "/asset.js");
});

test("direct Owner requests add only the Owner token", async () => {
  const calls = [];
  const client = createApiClient({
    ownerToken: "fixture-owner-token",
    routeBase: "",
    fetch: async (...args) => { calls.push(args); return response({ ok: true, value: 1 }); },
  });

  const result = await client.request("/api/status");

  assert.equal(result.value, 1);
  assert.equal(calls[0][0], "/api/status");
  assert.deepEqual(calls[0][1].headers, { "X-Owner-Token": "fixture-owner-token" });
});

test("Gateway writes cache CSRF and retain route-local API paths", async () => {
  const calls = [];
  const client = createApiClient({
    routeBase: "/lab",
    fetch: async (path, options) => {
      calls.push([path, options]);
      return path === "/api/csrf"
        ? response({ ok: true, csrf: "fixture-csrf" })
        : response({ ok: true });
    },
  });

  await client.request("/api/send", { method: "POST", body: "{}" });

  assert.equal(calls.filter(([path]) => path === "/api/csrf").length, 1);
  assert.equal(calls[1][0], "/lab/api/send");
  assert.equal(calls[1][1].headers["X-Faryo-Csrf"], "fixture-csrf");
  assert.equal(calls[1][1].headers["Content-Type"], "application/json");
});

test("non-JSON responses become bounded API errors", async () => {
  const client = createApiClient({
    fetch: async () => response("<!doctype html>", { ok: false, status: 502, statusText: "Bad Gateway" }),
  });

  await assert.rejects(
    client.request("/api/status"),
    (error) => error.status === 502 && error.nonJson === true,
  );
});
