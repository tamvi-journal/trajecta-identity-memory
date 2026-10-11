import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { get, parseLossless } from "../src/json.ts";

// Expanded only after all 31 certification jobs at 63a344e passed (run 38160707120).
test("conformance runs in the certified Node engine range with node:sqlite", () => {
  const metadata = parseLossless(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.equal(get(get(metadata, "engines"), "node"), ">=22.19 <23 || >=24 <25");
  assert.match(process.versions.node, /^\d+\.\d+\.\d+$/u);
  const [major, minor] = process.versions.node.split(".").map(Number);
  assert.ok((major === 22 && minor >= 19) || major === 24, `uncertified Node ${process.versions.node}`);
  assert.match(process.versions.sqlite ?? "", /^3\./u);
});
