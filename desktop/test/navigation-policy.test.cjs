const assert = require("node:assert/strict");
const { test } = require("node:test");

const { isInternalNavigation, externalHttpUrl } = require("../src/navigation-policy.cjs");

test("only the exact backend origin is internal", () => {
  const origin = "http://127.0.0.1:18848";
  assert.equal(isInternalNavigation(`${origin}/tasks`, origin), true);
  assert.equal(isInternalNavigation("http://127.0.0.1:18849/", origin), false);
  assert.equal(isInternalNavigation("https://example.com/", origin), false);
  assert.equal(isInternalNavigation("not a URL", origin), false);
});

test("only credential-free HTTP(S) links may open externally", () => {
  assert.equal(externalHttpUrl("https://chaoxing.com/course"), "https://chaoxing.com/course");
  assert.equal(externalHttpUrl("http://example.com/"), "http://example.com/");
  assert.equal(externalHttpUrl("file:///C:/secret.txt"), null);
  assert.equal(externalHttpUrl("javascript:alert(1)"), null);
  assert.equal(externalHttpUrl("https://user:pass@example.com/"), null);
});
