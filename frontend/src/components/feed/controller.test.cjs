/* eslint-disable @typescript-eslint/no-require-imports -- Node 20 runs this dependency-free CommonJS test harness. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const ts = require("typescript");
const compiled = ts.transpileModule(fs.readFileSync(`${__dirname}/controller.ts`, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const exportsObject = {};
new Function("exports", compiled)(exportsObject);
const { FeedController } = exportsObject;
const page = (ids, cursor = null) => ({ items: ids.map((id) => ({ id })), next_before: cursor });
function setup(filters = {}) {
  const requests = [];
  const controller = new FeedController((query) => new Promise((resolve, reject) => {
    requests.push({ query, resolve, reject });
  }), filters);
  return { controller, requests };
}
const ids = (controller) => controller.snapshot().items.map((item) => item.id);

test("reverse completion cannot overwrite the latest refresh", async () => {
  const { controller: c, requests: r } = setup();
  const first = c.start();
  const second = c.refresh();
  r[1].resolve(page([2], "new")); await second;
  r[0].resolve(page([1], "old")); await first;
  assert.deepEqual(ids(c), [2]);
  assert.equal(c.snapshot().nextBefore, "new");
});

test("new filter controller starts empty and disposed pagination cannot cross filters", async () => {
  const { controller: c, requests: r } = setup({ ticker: "A" });
  const first = c.start(); r[0].resolve(page([1], "cursor")); await first;
  const more = c.loadMore();
  c.dispose();
  const { controller: next, requests: nr } = setup({ ticker: "B" });
  assert.deepEqual(ids(next), []);
  const loading = next.start(); nr[0].resolve(page([3])); await loading;
  r[1].resolve(page([2])); await more;
  assert.deepEqual(ids(next), [3]); assert.deepEqual(ids(c), [1]);
  assert.equal(nr[0].query.ticker, "B");
});

test("pagination locks synchronously and deduplicates overlapping rows", async () => {
  const { controller: c, requests: r } = setup();
  const first = c.start(); r[0].resolve(page([1, 1, 2], "cursor")); await first;
  const more = c.loadMore(); await c.loadMore();
  assert.equal(r.length, 2);
  r[1].resolve(page([2, 3, 3])); await more;
  assert.deepEqual(ids(c), [1, 2, 3]);
});

test("failed pagination keeps rows and cursor and retry repeats that page", async () => {
  const { controller: c, requests: r } = setup();
  const first = c.start(); r[0].resolve(page([1], "cursor")); await first;
  const more = c.loadMore(); r[1].reject(new Error("offline")); await more;
  assert.deepEqual(ids(c), [1]); assert.equal(c.snapshot().nextBefore, "cursor");
  assert.equal(c.snapshot().error, "offline"); assert.equal(c.snapshot().loadingMore, false);
  const retry = c.retry(); assert.equal(r[2].query.before, "cursor");
  r[2].resolve(page([2])); await retry;
  assert.deepEqual(ids(c), [1, 2]); assert.equal(c.snapshot().error, null);
});

test("refresh failure preserves paginated rows and pending notification", async () => {
  const { controller: c, requests: r } = setup();
  const first = c.start(); r[0].resolve(page([1], "cursor")); await first;
  const more = c.loadMore(); r[1].resolve(page([2], "older")); await more;
  c.markUpdated(); const refresh = c.refresh(); r[2].reject(new Error("offline")); await refresh;
  assert.deepEqual(ids(c), [1, 2]); assert.equal(c.snapshot().nextBefore, "older");
  assert.equal(c.snapshot().pending, true);
  const retry = c.retry(); assert.equal(r[3].query.before, undefined);
  r[3].resolve(page([3])); await retry;
  assert.deepEqual(ids(c), [3]); assert.equal(c.snapshot().pending, false);
});

test("refresh invalidates outstanding pagination", async () => {
  const { controller: c, requests: r } = setup();
  const first = c.start(); r[0].resolve(page([1], "cursor")); await first;
  const more = c.loadMore(); const refresh = c.refresh();
  r[2].resolve(page([3], "new")); await refresh;
  r[1].resolve(page([2], "old")); await more;
  assert.deepEqual(ids(c), [3]); assert.equal(c.snapshot().nextBefore, "new");
});

test("disposal ignores completion and supports React strict effect restart", async () => {
  const { controller: c, requests: r } = setup();
  const first = c.start(); c.dispose(); const snapshot = c.snapshot();
  r[0].reject(new Error("late")); await first;
  assert.equal(c.snapshot(), snapshot);
  const restart = c.start(); r[1].resolve(page([2])); await restart;
  assert.deepEqual(ids(c), [2]);
});

test("events during refresh keep the notification, bursts coalesce", async () => {
  const { controller: c, requests: r } = setup();
  const first = c.start(); r[0].resolve(page([1])); await first;
  let notifications = 0;
  c.subscribe(() => notifications++);
  c.markUpdated(); c.markUpdated(); c.markUpdated();
  assert.equal(notifications, 1);
  const refresh = c.refresh(); c.markUpdated();
  r[1].resolve(page([2])); await refresh;
  assert.equal(c.snapshot().pending, true);
  assert.equal(r.length, 2);
});
