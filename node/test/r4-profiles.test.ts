import assert from "node:assert/strict";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { resolve, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { resolveProfile } from "../src/recipe.ts";
import { InjectedClock } from "../src/clock.ts";
import { MemoryStore } from "../src/store.ts";
import { main } from "../src/cli.ts";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const fixture = (t: any) => {
  const root = fs.mkdtempSync(join(tmpdir(), "r4-profile-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const env = {
    TRAJECTA_IDENTITY_DATA_DIR: join(root, "data"),
    TRAJECTA_IDENTITY_PROFILES: join(root, "data/profiles"),
  };
  const incoming = join(root, "incoming.json");
  const raw = fs.readFileSync(join(ROOT, "trajecta_identity/profiles/example/profile.json"), "utf8");
  fs.writeFileSync(incoming, raw);
  const target = join(root, "data/profiles/example/profile.json");
  return { root, env, incoming, target, raw };
};
function inventory(root: string): Record<string, string | null> {
  const result: Record<string, string | null> = {};
  const walk = (dir: string, prefix = "") => {
    for (const name of fs.readdirSync(dir)) {
      const path = join(dir, name),
        key = prefix + name;
      if (fs.statSync(path).isDirectory()) {
        result[key] = null;
        walk(path, key + "/");
      } else result[key] = fs.readFileSync(path).toString("hex");
    }
  };
  walk(root);
  return result;
}

test("P25 conflict is typed exit 1, no file or last-choice write", async (t) => {
  const f = fixture(t);
  await resolveProfile(f.incoming, { env: f.env, rememberChoice: false });
  fs.writeFileSync(f.incoming, f.raw.replace('"name": "example"', '"name": "example", "extra": true'));
  const before = inventory(f.root);
  let err = "";
  const code = await main(["-p", f.incoming, "status"], {
    env: f.env,
    stderr: (text: string) => {
      err += text;
    },
  });
  assert.equal(code, 1);
  assert.equal(
    err,
    "ProfileConflict: profile 'example' differs from the installed copy; pass --replace-profile to overwrite\n",
  );
  assert.deepEqual(inventory(f.root), before);
});

for (const replace of [false, true])
  for (const extra of ["null", "NaN", "Infinity", "-Infinity"])
    test(`P25 identical writer bytes no-op: ${extra}, replace=${replace}`, async (t) => {
      const f = fixture(t);
      fs.writeFileSync(f.incoming, f.raw.replace('"name": "example"', `"name": "example", "extra": ${extra}`));
      await resolveProfile(f.incoming, { env: f.env, rememberChoice: false });
      const before = inventory(f.root),
        mtime = fs.statSync(f.target, { bigint: true }).mtimeNs;
      await resolveProfile(f.incoming, { env: f.env, rememberChoice: false, replaceProfile: replace });
      assert.deepEqual(inventory(f.root), before);
      assert.equal(fs.statSync(f.target, { bigint: true }).mtimeNs, mtime);
    });

for (const difference of ["spacing", "invalid-installed", "key-order"])
  test(`P25 conflict without parsing installed: ${difference}`, async (t) => {
    const f = fixture(t);
    await resolveProfile(f.incoming, { env: f.env, rememberChoice: false });
    if (difference === "key-order") {
      // Adding and then moving an unused key preserves meaning but changes writer order.
      fs.writeFileSync(f.incoming, f.raw.replace("{", '{"unused": null,'));
      fs.writeFileSync(f.target, fs.readFileSync(f.target, "utf8").replace(/\}\s*$/u, ', "unused": null}\n'));
    } else fs.writeFileSync(f.target, difference === "spacing" ? fs.readFileSync(f.target, "utf8") + " " : "{broken");
    const before = inventory(f.root);
    await assert.rejects(
      resolveProfile(f.incoming, { env: f.env, rememberChoice: false }),
      (e: any) => e.constructor.name === "ProfileConflict",
    );
    assert.deepEqual(inventory(f.root), before);
  });

test("P25 replace backs up exact bytes, skips collisions, commits new recipe", async (t) => {
  const f = fixture(t);
  await resolveProfile(f.incoming, { env: f.env, rememberChoice: false });
  const old = fs.readFileSync(f.target);
  const backup = f.target + ".20260930T000000000001Z.bak";
  fs.writeFileSync(backup, "collision zero");
  fs.writeFileSync(backup + ".1", "collision one");
  fs.writeFileSync(f.incoming, f.raw.replace('"name": "example"', '"name": "example", "extra": true'));
  await resolveProfile(f.incoming, {
    env: f.env,
    rememberChoice: false,
    replaceProfile: true,
    clock: new InjectedClock(),
  });
  assert.deepEqual(fs.readFileSync(backup + ".2"), old);
  assert.equal(fs.readFileSync(backup, "utf8"), "collision zero");
  assert.equal(fs.readFileSync(backup + ".1", "utf8"), "collision one");
  assert.match(fs.readFileSync(f.target, "utf8"), /"extra": true/u);
  assert(!fs.readdirSync(dirname(f.target)).some((name) => name.startsWith(".profile-")));
});

for (const failure of ["backup", "write", "replace", "close"])
  test(`P25 ${failure} failure keeps original and reports backup`, async (t) => {
    const f = fixture(t);
    await resolveProfile(f.incoming, { env: f.env, rememberChoice: false });
    const old = fs.readFileSync(f.target);
    fs.writeFileSync(f.incoming, f.raw.replace('"name": "example"', '"name": "example", "extra": true'));
    const error = new Error("injected failure"),
      originalWrite = fs.writeFileSync,
      originalRename = fs.renameSync,
      originalClose = fs.closeSync;
    let reported = "";
    const stderr = process.stderr.write;
    process.stderr.write = ((text: any) => {
      reported += text;
      return true;
    }) as any;
    let writes = 0;
    if (failure === "close")
      fs.closeSync = (fd) => {
        originalClose(fd);
        if (fs.existsSync(f.target + ".20260930T000000000001Z.bak")) throw error;
      };
    else if (failure === "replace")
      fs.renameSync = () => {
        throw error;
      };
    else
      fs.writeFileSync = ((path: any, bytes: any, ...rest: any[]) => {
        if (typeof path === "number") writes++;
        if (typeof path === "number" && writes === (failure === "backup" ? 1 : 2)) {
          originalWrite(path, Buffer.from(bytes).subarray(0, 7));
          throw error;
        }
        return (originalWrite as any)(path, bytes, ...rest);
      }) as any;
    syncBuiltinESMExports();
    try {
      await assert.rejects(
        resolveProfile(f.incoming, {
          env: f.env,
          rememberChoice: false,
          replaceProfile: true,
          clock: new InjectedClock(),
        }),
        (e) => e === error,
      );
    } finally {
      fs.writeFileSync = originalWrite;
      fs.renameSync = originalRename;
      fs.closeSync = originalClose;
      process.stderr.write = stderr;
      syncBuiltinESMExports();
    }
    const backup = f.target + ".20260930T000000000001Z.bak";
    assert(reported.includes(backup));
    assert.deepEqual(fs.readFileSync(f.target), old);
    assert.deepEqual(fs.readFileSync(backup), failure === "backup" ? old.subarray(0, 7) : old);
    assert(!fs.readdirSync(dirname(f.target)).some((name) => name.startsWith(".profile-")));
  });

for (const failure of [false, true])
  test(`P26 missing chain is removed on every exit, failure=${failure}`, (t) => {
    const root = fs.mkdtempSync(join(tmpdir(), "r4-dry-"));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    const source = join(root, "source.sqlite3");
    fs.copyFileSync(join(ROOT, "spec/golden/identity-open/store.sqlite3"), source);
    const before = inventory(root),
      real = fs.copyFileSync;
    if (failure)
      fs.copyFileSync = () => {
        throw new Error("copy failed");
      };
    syncBuiltinESMExports();
    try {
      const run = () => new MemoryStore(source).migrateTo(join(root, "new/deep/target.sqlite3"), { dryRun: true });
      if (failure) assert.throws(run, /copy failed/u);
      else assert.equal((run() as any).state, "ready");
    } finally {
      fs.copyFileSync = real;
      syncBuiltinESMExports();
    }
    assert.deepEqual(inventory(root), before);
  });

test("P26 concurrent parent belongs to the other process and is retained", (t) => {
  const root = fs.mkdtempSync(join(tmpdir(), "r4-dry-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const source = join(root, "source.sqlite3"),
    parent = join(root, "external");
  fs.copyFileSync(join(ROOT, "spec/golden/identity-open/store.sqlite3"), source);
  const before = inventory(root),
    real = fs.mkdirSync;
  let triggered = false;
  fs.mkdirSync = ((path: any, ...args: any[]) => {
    if (path === parent && !triggered) {
      triggered = true;
      const child = spawnSync(process.execPath, ["-e", "require('node:fs').mkdirSync(process.argv[1])", parent]);
      assert.equal(child.status, 0, child.stderr.toString());
    }
    return (real as any)(path, ...args);
  }) as any;
  syncBuiltinESMExports();
  try {
    new MemoryStore(source).migrateTo(join(parent, "owned/deep/target.sqlite3"), { dryRun: true });
  } finally {
    fs.mkdirSync = real;
    syncBuiltinESMExports();
  }
  assert(triggered);
  assert.deepEqual(inventory(root), { ...before, external: null });
});

test("P26 rehearsal creation failure never deletes another actor's target", (t) => {
  const root = fs.mkdtempSync(join(tmpdir(), "r4-dry-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const source = join(root, "source.sqlite3"),
    target = join(root, "owned/deep/target.sqlite3");
  fs.copyFileSync(join(ROOT, "spec/golden/identity-open/store.sqlite3"), source);
  const before = fs.readFileSync(source),
    original = fs.mkdtempSync;
  fs.mkdtempSync = (() => {
    fs.writeFileSync(target, "another actor");
    throw new Error("rehearsal creation failed");
  }) as any;
  syncBuiltinESMExports();
  try {
    assert.throws(() => new MemoryStore(source).migrateTo(target, { dryRun: true }), /rehearsal creation failed/u);
  } finally {
    fs.mkdtempSync = original;
    syncBuiltinESMExports();
  }
  assert.equal(fs.readFileSync(target, "utf8"), "another actor");
  assert.deepEqual(fs.readFileSync(source), before);
});

for (const mode of [0o644, 0o640])
  test(
    `P25 replacement preserves POSIX mode ${mode.toString(8)}`,
    { skip: process.platform === "win32" },
    async (t) => {
      const f = fixture(t);
      await resolveProfile(f.incoming, { env: f.env, rememberChoice: false });
      fs.chmodSync(f.target, mode);
      fs.writeFileSync(f.incoming, f.raw.replace('"name": "example"', '"name": "example", "extra": true'));
      await resolveProfile(f.incoming, { env: f.env, rememberChoice: false, replaceProfile: true });
      assert.equal(fs.statSync(f.target).mode & 0o7777, mode);
    },
  );

test("P26 unreachable root rethrows the original ENOENT", (t) => {
  const f = fixture(t),
    source = join(f.root, "source.sqlite3");
  fs.copyFileSync(join(ROOT, "spec/golden/identity-open/store.sqlite3"), source);
  const before = inventory(f.root),
    original = fs.mkdirSync;
  const error = Object.assign(new Error("synthetic unreachable root"), { code: "ENOENT" });
  fs.mkdirSync = (() => {
    throw error;
  }) as any;
  syncBuiltinESMExports();
  try {
    assert.throws(
      () => new MemoryStore(source).migrateTo(join(f.root, "missing/target.sqlite3"), { dryRun: true }),
      (caught) => caught === error,
    );
  } finally {
    fs.mkdirSync = original;
    syncBuiltinESMExports();
  }
  assert.deepEqual(inventory(f.root), before);
});
