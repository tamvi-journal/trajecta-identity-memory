import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";
import { ROOT, temporary, request } from "./view-support.ts";

test("npm pack serves the canonical asset outside the checkout", async () => {
  const root = temporary(),
    outside = resolve(root, "outside"),
    unpack = resolve(root, "unpacked");
  mkdirSync(outside);
  mkdirSync(unpack);
  const env = {
    ...process.env,
    HOME: root,
    USERPROFILE: root,
    TRAJECTA_IDENTITY_DATA_DIR: resolve(root, "data"),
    TRAJECTA_IDENTITY_PROFILES: resolve(root, "profiles"),
    npm_config_cache: resolve(root, "npm-cache"),
  };
  const npm = process.env.npm_execpath;
  assert(npm, "run this installed-distribution acceptance through npm test");
  let child;
  try {
    execFileSync(process.execPath, [npm, "pack", "--ignore-scripts", "--pack-destination", root], {
      cwd: resolve(ROOT, "node"),
      env,
      stdio: "pipe",
    });
    const archive = readdirSync(root).find((name) => name.endsWith(".tgz"));
    assert(archive);
    execFileSync("tar", ["-xzf", resolve(root, archive), "-C", unpack], { env, stdio: "pipe" });
    const installed = resolve(unpack, "package");
    assert.deepEqual(
      readFileSync(resolve(installed, "assets/view.html")),
      readFileSync(resolve(ROOT, "trajecta_identity/assets/view.html")),
    );
    const profile = resolve(outside, "profile.json");
    copyFileSync(resolve(ROOT, "trajecta_identity/profiles/example/profile.json"), profile);
    child = spawn(
      process.execPath,
      [
        "--experimental-strip-types",
        resolve(installed, "src/cli.ts"),
        "--profile",
        profile,
        "--db",
        resolve(outside, "store.sqlite3"),
        "view",
        "--port",
        "0",
        "--no-browser",
      ],
      {
        // All writable roots remain in the clone; the process cwd is outside it.
        cwd: resolve(ROOT, ".."),
        env,
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    let stderr = "";
    child.stderr!.on("data", (bytes) => {
      stderr += bytes;
    });
    const line = await new Promise<string>((resolve, reject) => {
      let output = "";
      const timer = setTimeout(() => reject(new Error(`installed view failed to start: ${stderr}`)), 15000);
      child!.once("error", reject);
      child!.once("exit", (code) => {
        clearTimeout(timer);
        reject(new Error(`installed view exited ${code}: ${stderr}`));
      });
      child!.stdout!.on("data", (bytes) => {
        output += bytes;
        if (output.includes("\n")) {
          clearTimeout(timer);
          resolve(output);
        }
      });
    });
    const port = /http:\/\/127\.0\.0\.1:(\d+)\//u.exec(line);
    assert(port, line);
    const response = await request({ port: Number(port[1]) }, { path: "/" });
    assert.equal(response.status, 200);
    assert.deepEqual(response.body, readFileSync(resolve(ROOT, "trajecta_identity/assets/view.html")));
    assert.equal(stderr, "");
  } finally {
    if (child && child.exitCode === null) {
      const exited = new Promise<void>((resolve) => child!.once("exit", () => resolve()));
      child.kill("SIGTERM");
      await exited;
    }
    rmSync(root, { recursive: true, force: true });
  }
});
