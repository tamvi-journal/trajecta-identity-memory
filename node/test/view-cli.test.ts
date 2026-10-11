import assert from "node:assert/strict";
import test from "node:test";
import { parseArgs } from "../src/cli-runtime.ts";

test("view accepts an ephemeral port and the no-browser flag", () => {
  assert.deepEqual(parseArgs(["view", "--port", "0", "--no-browser"]), {
    command: "view",
    port: 0n,
    no_browser: true,
  });
});

import { copyFileSync, cpSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import { main } from "../src/cli-runtime.ts";
import { InjectedClock } from "../src/clock.ts";
import { inventory, ROOT, temporary } from "./view-support.ts";

for (const state of ["ready", "legacy-v4", "uninitialized"]) {
  test(`CLI view bootstrap rule and printed bound port: ${state}`, async () => {
    const root = temporary(),
      profileRoot = resolve(root, "profiles"),
      data = resolve(root, "data");
    cpSync(resolve(ROOT, "trajecta_identity/profiles"), profileRoot, { recursive: true });
    mkdirSync(data);
    const database = resolve(data, "store.sqlite3");
    if (state !== "uninitialized")
      copyFileSync(
        resolve(ROOT, "spec/golden-view-v1", state === "ready" ? "view-fixture" : "legacy-v4", "store.sqlite3"),
        database,
      );
    const before = inventory(data);
    let line = "";
    try {
      const exit = await main(["--profile", "example", "--db", database, "view", "--port", "0", "--no-browser"], {
        env: {
          ...process.env,
          TRAJECTA_IDENTITY_PROFILES: profileRoot,
          TRAJECTA_IDENTITY_DATA_DIR: resolve(root, "identity"),
        },
        clock: new InjectedClock(),
        stdout(bytes) {
          line += bytes.toString();
          setImmediate(() => process.emit("SIGINT"));
        },
      });
      assert.equal(exit, 0);
      assert.match(
        line,
        /^Identity memory view for example-agent: http:\/\/127\.0\.0\.1:[1-9][0-9]*\/  \(Ctrl\+C to stop\)\n$/u,
      );
      if (state !== "uninitialized") assert.deepEqual(inventory(data), before);
      else assert.equal((inventory(data) as unknown[]).length, 1);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}

import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";
import { EventEmitter } from "node:events";
import { openBrowser } from "../src/view.ts";

test("browser opener uses the OS command and ignores asynchronous failure", (t) => {
  const child = new EventEmitter() as EventEmitter & { unref(): void };
  let unreferenced = false;
  child.unref = () => {
    unreferenced = true;
  };
  const seam = t.mock.method(childProcess, "spawn", () => child);
  syncBuiltinESMExports();
  try {
    const url = "http://127.0.0.1:12345/";
    openBrowser(url);
    const call = seam.mock.calls[0].arguments;
    assert.deepEqual(
      call,
      process.platform === "darwin"
        ? ["open", [url], { stdio: "ignore" }]
        : process.platform === "win32"
          ? ["cmd", ["/c", "start", "", url], { stdio: "ignore" }]
          : ["xdg-open", [url], { stdio: "ignore" }],
    );
    assert(unreferenced);
    assert.doesNotThrow(() => child.emit("error", new Error("synthetic opener failure")));
  } finally {
    seam.mock.restore();
    syncBuiltinESMExports();
  }
});

test("browser opener ignores a synchronous launch failure", (t) => {
  const seam = t.mock.method(childProcess, "spawn", () => {
    throw new Error("synthetic launch failure");
  });
  syncBuiltinESMExports();
  try {
    assert.doesNotThrow(() => openBrowser("http://127.0.0.1:12345/"));
  } finally {
    seam.mock.restore();
    syncBuiltinESMExports();
  }
});
