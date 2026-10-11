import assert from "node:assert/strict";
import test from "node:test";

test("conformance runs on the pinned Node major with node:sqlite", () => {
  assert.equal(process.versions.node.split(".")[0], "22");
  assert.match(process.versions.sqlite ?? "", /^3\./u);
});
