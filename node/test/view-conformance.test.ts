import assert from "node:assert/strict";
import { copyFileSync, readFileSync, readdirSync, rmSync, statSync, unlinkSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import { InjectedClock } from "../src/clock.ts";
import { IdentityMemory } from "../src/identity.ts";
import { parseLossless } from "../src/json.ts";
import { startView } from "../src/view.ts";
import {
  ROOT,
  CORPUS,
  PROFILE,
  sha,
  plain,
  readJson,
  inventory,
  temporary,
  request,
  compare,
  dumpDatabase,
} from "./view-support.ts";

test("view manifest authenticates every corpus file and normalization table; assets are identical", () => {
  const manifest = readJson(resolve(CORPUS, "MANIFEST.json"));
  const actual: Record<string, string> = {};
  for (const name of readdirSync(CORPUS, { recursive: true }).map(String)) {
    const path = resolve(CORPUS, name);
    if (statSync(path).isFile() && name !== "MANIFEST.json")
      actual[name.replaceAll("\\", "/")] = sha(readFileSync(path));
  }
  for (const name of readdirSync(resolve(ROOT, "memory_core/tables")).filter((name) => name.endsWith(".json")))
    actual[`tables/${name}`] = sha(readFileSync(resolve(ROOT, "memory_core/tables", name)));
  assert.deepEqual(actual, manifest.files);
  const canonical = readFileSync(resolve(ROOT, "trajecta_identity/assets/view.html"));
  const node = readFileSync(resolve(ROOT, "node/assets/view.html"));
  assert.deepEqual(node, canonical);
  assert.equal(sha(node), sha(canonical));
  for (const name of ["decimal", "isalnum", "whitespace"])
    assert.deepEqual(
      readFileSync(resolve(ROOT, `node/tables/cli-${name}.json`)),
      readFileSync(resolve(ROOT, `spec/golden-cli-v1/${name}.json`)),
    );
});

for (const scenario of readdirSync(CORPUS)
  .filter((name) => statSync(resolve(CORPUS, name)).isDirectory())
  .sort()) {
  test(`view-v1 ${scenario}`, async () => {
    const directory = resolve(CORPUS, scenario),
      original = inventory(directory),
      root = temporary();
    const database = resolve(root, "store.sqlite3");
    copyFileSync(resolve(directory, "store.sqlite3"), database);
    let clock = new InjectedClock();
    const memory = new IdentityMemory(PROFILE, database, {
      surface: "view",
      displayDatabase: "store.sqlite3",
      clock: { seconds: () => clock.seconds(), micros: () => clock.micros() },
    });
    const server = await startView(memory, { port: 0 });
    const cases = readFileSync(resolve(directory, "cases.jsonl"), "utf8")
      .trimEnd()
      .split("\n")
      .map((line) => plain(parseLossless(line)));
    const before = inventory(root);
    try {
      for (const item of cases) {
        clock = new InjectedClock();
        if (item.action === "delete-store-while-serving") {
          memory.close();
          unlinkSync(database);
        }
        let actual;
        try {
          actual = await request(server, item);
        } catch (error) {
          throw new Error(item.label, { cause: error });
        }
        compare(item, actual, directory);
        if (scenario !== "g15-disappear") {
          assert.equal(item.store_unchanged, true);
          assert.deepEqual(inventory(root), before, item.label);
        } else {
          assert.deepEqual(dumpDatabase(database), readJson(resolve(directory, "dump.json")));
          const result = readFileSync(database);
          memory.close();
          unlinkSync(database);
          clock = new InjectedClock();
          memory.bootstrap();
          memory.close();
          assert.deepEqual(readFileSync(database), result, "G15 equals a direct local bootstrap");
        }
      }
      assert.deepEqual(inventory(directory), original);
    } finally {
      await server.close();
      memory.close();
      rmSync(root, { recursive: true, force: true });
    }
  });
}
