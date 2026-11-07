/* eslint-disable @typescript-eslint/no-require-imports -- Node 20 CommonJS test harness. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const ts = require("typescript");
const compiled = ts.transpileModule(fs.readFileSync(`${__dirname}/stream.ts`, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const exportsObject = {};
new Function("exports", compiled)(exportsObject);
const { subscribeToFeed } = exportsObject;

function setup() {
  const listeners = {};
  const stream = {
    onopen: null, onerror: null, closed: false,
    addEventListener(name, callback) { listeners[name] = callback; },
    close() { this.closed = true; },
  };
  const live = [];
  let updates = 0;
  const cleanup = subscribeToFeed(stream, (value) => live.push(value), () => updates++);
  return { stream, live, cleanup, emit: (name) => listeners[name](), updates: () => updates };
}

test("healthy first connection and both event kinds", () => {
  const s = setup();
  s.stream.onopen();
  assert.deepEqual(s.live, [false, true]);
  assert.equal(s.updates(), 0);
  s.emit("article"); s.emit("article_updated");
  assert.equal(s.updates(), 2);
});

test("failure before the first connection requests authoritative refresh on recovery", () => {
  const s = setup();
  s.stream.onerror(); s.stream.onerror(); s.stream.onopen();
  assert.deepEqual(s.live, [false, false, false, true]);
  assert.equal(s.updates(), 1);
});

test("reconnection after established stream requests refresh", () => {
  const s = setup();
  s.stream.onopen(); s.stream.onerror(); s.stream.onopen();
  assert.deepEqual(s.live, [false, true, false, true]);
  assert.equal(s.updates(), 1);
});

test("cleanup closes the stream and ignores late connection and article callbacks", () => {
  const s = setup();
  s.stream.onopen(); s.cleanup();
  assert.equal(s.stream.closed, true);
  s.stream.onerror(); s.stream.onopen(); s.emit("article"); s.emit("article_updated");
  assert.deepEqual(s.live, [false, true]);
  assert.equal(s.updates(), 0);
});
