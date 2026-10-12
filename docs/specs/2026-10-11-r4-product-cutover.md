# R4: the Trajecta product layer, installer, and cutover

Status: approved by Lam @ 8dae7e3; §12 added after Ty's product question (Lam settlement 2026-10-11), revised after Lam #41 @ f10c11a (F41-1..F41-3) and @ 6cf5d29 (F41-4, F41-5); PR 4a preflight settlements (Codex P4a-1..4) added; §2.3 pass-through moved in-process so signals are delivered exactly once in every topology (Aux R1-1, Lam R44-1). Revised after Lam's review @ b121be5 (REQUEST CHANGES: F40-1..F40-4; Q1–Q8 yes with conditions; §11). Author: Aux (leader). Builds on R0–R3 and R2e (main @ efa5149).

## 0. Goal, and what "done" means

R4 turns two verified engines into **one thing a person can buy, install with one command, and trust**. Lam's definition of done (R0 §R4, unchanged):
- One installer bundles the Node runtime path, `@trajecta/identity` and the work engine into one product package. One product does not require one repo.
- The Python writer is retired.
- The Python oracle stays in CI as a reader for one release.

R2e settled the product layer's rule. It **coordinates the engines and is never a second authority over their memory histories**: it may compose identity and work evidence, but never manufacture verified continuity on its own.

**R4 done** = §8, gates M1–M8, all green, plus Ty's owner M rehearsal receipt (R3 §4) before the cutover release ships.

**Out of scope**
- **R5:** the redesigned view, view-api/v2 with work, G15, G16.
- **Beta commerce** (checkout, price, landing page). These are Ty's decisions, outside code.
- **Phase 4:** AWM/LWM onto TWM.

## 1. Inventory at efa5149 (what R4 inherits)

| Item | State |
|---|---|
| Identity engine | `@trajecta/identity` in `node/`, `engines: node >=22 <23`, package version 0.1.0, not published |
| Work engine | `trajecta-work-memory`, TS, `engines: node >=22.19`, version 0.1.0, bins `trajecta` and `trajecta-work-mcp` |
| Versions | pyproject 0.4.0, `trajecta_identity.__version__` 0.1.0, node 0.1.0, work 0.1.0. That is three product-looking numbers for one product |
| Install today | `install/install.sh` and `install.ps1` create a Python venv and run `setup`. The Python `plugin` packs Python sources |
| Carries | **K6** (single version in `plugin.json`); **R4 carry from #35**: Windows `.mcp.json` boots through `python`; **#37 nit**: `tests.yml` hard-codes the 0.4.0 wheel name; **G13**; **G14**; **G17** (owner R4); `import-aml` (Python only) |

## 2. Product layer: the `trajecta` repo and the release artifact (Q1; F40-1)

A new repo, `tamvi-journal/trajecta` (Apache-2.0). It is thin, and it owns only product-level concerns: the release build, the installer, the product CLI, `compat.json`, the plugin builder and release evidence.

### 2.1 Engines are vendored at exact SHAs, never resolved at install time

Both engines have **zero npm dependencies**: no `dependencies` and no `devDependencies` (checked at efa5149 and 05c1139). So the product needs no `node_modules`, no registry and no Git at install time.

- `engines.lock.json` in the product repo pins, for each engine:
  - the repo URL;
  - the commit SHA;
  - the **subdirectory** to take (`node/` for identity, the repo root for work);
  - the explicit list of runtime paths to copy (identity: `src`, `schema.sql`, `tables`, `assets`, `package.json`; work: `src`, `assets`, `package.json`);
  - **bundled profiles (Codex P4a-2):** identity also pins `trajecta_identity/profiles/**`, taken from the repo **root** at the same SHA and copied to `engines/trajecta_identity/profiles/`. This keeps the engine's own relative lookup (`node/src/paths.ts`: `../../trajecta_identity/profiles`) valid with no engine patch and no environment default. Every file is digested in the lock. M2 proves that the default profile resolves offline with no profile environment set;
  - the SHA-256 of every copied file.
- `tools/build-release.ts` fetches each pinned SHA, copies exactly those paths into `engines/identity/` and `engines/work/`, and **fails** if any file's SHA-256 differs from the lock. The lock is regenerated only by an explicit `tools/pin-engines.ts <sha>`, and that change is reviewed like code.
- The product imports engines only through relative paths. From `product/src/engines.ts` that is `../../engines/identity/src/index.ts`. There is no package-name resolution, and M2's offline run proves the paths resolve.

### 2.2 The release artifact is one deterministic tarball

`trajecta-<ver>.tar.gz` holds a single top directory `trajecta-<ver>/` with:
- `product/` (the product source and `package.json`);
- `engines/identity/` and `engines/work/`;
- `bin/` (the OS-native wrappers, §5.3);
- `MANIFEST.json`, which records every file's path, size and SHA-256, the engine SHAs, the product version and the supported Node range.

**Deterministic:** entries are sorted, file mtimes are fixed, uid/gid are 0, modes are 0644 or 0755, and gzip runs with `-n`. Two builds from the same commits produce **byte-identical** tarballs. CI proves this by building twice.

It is **not** `npm pack`. npm publish is not used in R4.

**Settlements (Codex P4a-3, P4a-4):**
- `MANIFEST.json` is excluded from its own file map. It is authenticated by the enclosing tarball's SHA-256, and in a release by the signed `release.json`, which names that digest.
- The foundation PR (4a) builds a **non-release verification artifact**: `MANIFEST.json` carries `"artifact": "foundation"` and has no `bin/`. Acceptance of `bin/` is deferred to 4c, which also switches the build to `"artifact": "release"`. A release build refuses unless `bin/` is present and complete.
- The index sequence that published a release (§12.2) is written into a release `MANIFEST.json` by the 4d release/update build. A foundation artifact has no such field. Any update logic that reads the field treats its absence as "not a release" and refuses.

### 2.3 CLI and bin names

- The product owns the only `trajecta` command.
- The work engine's own `trajecta` and `trajecta-work-mcp` bins are **not** exposed by the product, so there is no collision. Its CLI is reached as `trajecta work …` and its MCP server through the plugin. The work repo is unchanged.
- **Pass-through contract (Lam R4-F7; execution model amended after Aux R1-1 and Lam R44-1):** `trajecta identity …` and `trajecta work …` run the engine CLI **in the product's own process**, not as a child process:
  - the product's dispatcher sets `process.argv` to `[process.execPath, <absolute engine cli.ts path>, ...the user's remaining arguments]` and then dynamically imports that engine entry module. Both engine entries run from that argv: identity through its `import.meta.url === argv[1]` guard, work through its top-level code;
  - before the import, the product dispatcher does nothing observable: it installs no signal or exit handlers, does not read stdin, writes nothing to stdout or stderr, and does not change cwd, env, umask or any file descriptor. After the import, the engine owns the process completely, including `process.exitCode` and `process.exit`, and the product never overrides them. Its own error wrapper is never applied to an engine run. M2 enforces this with a source scan of the dispatcher path, together with the byte-exact corpora.
- **Why in-process:** there is exactly one process, so stdio, TTY, exit status and signals are the engine's own by construction.
  - The **same file descriptors** reach the engine, so the bytes are exact and `isatty()` is unchanged per stream.
  - The engine's TTY-only owner confirmations (the authority receipt commands, such as retract and legacy-close) behave exactly as when the engine is called directly, including their refusal when there is no TTY. **Correction (Codex P4a-1):** the engine's `migrate-to` has **no** TTY confirmation. It is an explicit user command that takes a target and writes a backup, and frozen corpus cases run it with tty=false. The pass-through keeps it exactly as it is. The TTY-confirmed migration belongs to the product's own `trajecta migrate-to --using` (§12.2, PR 4d), never to the engine.
  - **Signals are delivered exactly once in every topology** (Lam R44-1): terminal Ctrl-C and Ctrl-\, `kill -<sig> <pid>`, `kill -<sig> -<pgid>`, job control, and Windows console events all reach the one process that runs the engine, exactly as they would reach the engine run directly. There is no forwarding, no re-raising and no source inference. (The child-process design was rejected: a parent cannot tell a process-group broadcast from a PID-directed signal, so it delivers either twice, as in R1-1 where `identity view` exits 130 instead of 0, or not at all. Moving the child into its own process group would take it out of the terminal's foreground group and break TTY confirmations.)
  - Exit status is the engine's own, including death by signal.
- The product never captures, buffers or re-encodes engine streams.
- **Wrappers must not add a parent back (4c):** the POSIX `sh` wrappers (§5.3) start Node with `exec`. A Windows `cmd` wrapper necessarily stays a parent, so 4c/M5 must test its behaviour on console Ctrl-C, including cmd's "Terminate batch job (Y/N)?" prompt, and either prove parity with a direct run or state the difference as a declared Windows limitation that M8 checks.
- **M2 also proves, with the real engines** (macOS and Linux PTYs, and Windows where marked):
  - `identity view --no-browser --port 0` under a terminal Ctrl-C gives the same transcript and exit code directly and through the product;
  - with a TTY on stdin, `kill -INT <pid>` aimed at the process gives the same result directly and through the product;
  - `kill -TERM -<pgid>` gives the same result directly and through the product;
  - with no TTY, SIGINT and SIGTERM give the same result directly and through the product;
  - `process.pid` seen by the engine equals the product's pid, so no extra process exists (all three OSes).
- **M2 proves:**
  - non-interactive: the full cli-v1 corpus and the work CLI suite, with byte-exact stdout and stderr and exact exit codes;
  - interactive, on POSIX: a PTY test using `script(1)` on macOS and Linux, covering an authority receipt confirmation that is accepted and one that is typed wrong, an `isatty` probe, and the Ctrl-C and signal parity listed above;
  - no TTY: the engine's refusal, with its bytes and exit code unchanged;
  - Windows interactive confirmation is checked by hand inside M8, because hosted runners have no console. Windows non-TTY refusal stays automated.

### 2.4 Authority: the product never writes a store itself (F40-4)

- **Adapter.** All engine use goes through one module, `src/engines.ts`, which exposes only the engines' public functions. Any other import of an engine's internals, or of `node:sqlite`, is a build error, enforced by a lint rule plus a source scan.
- **Differential authority test (M2).** For every product verb that can touch a store (`install` bootstrap, `doctor`, the pass-throughs):
  - run the verb on a store copy;
  - run the equivalent engine-only command on another copy;
  - the resulting store bytes must be identical.
- **Write-trace test (M2).** A test-only `--import` hook records every filesystem write the product process makes. Writes outside the install root, the plugin output path and engine-mediated store paths fail the test.

## 3. One version (closes K6)

- **The product version** is `trajecta`'s `package.json` version. It starts at **0.5.0**, so it sorts after every number a user may have seen (0.4.0 pyproject).
- **Engine versions** stay as each engine's own `package.json` version. They are **not** user-facing; `trajecta version` shows them as "engine" lines.
- **Wire and runtime versions** (the 0.1.0 inside protocol/schema fields) are protocol constants, not product versions. They are unchanged, and the corpora pin them.
- **pyproject 0.4.0** freezes as the oracle's version. The Python package is not released again.
- `plugin.json.version`, `trajecta version` and the release tag must be equal. **K6 becomes an exact test.**
- `tests.yml` derives the wheel filename from pyproject (fixes the #37 nit).

## 4. Runtime: Node (Q2, Q3)

- **v1 requires a system Node** that is an LTS major from the supported set. This is a decision for the **developer beta only** (Lam Q2). It is not a claim that every buyer has Node. No Node binary is bundled in R4. Bundling, through Node SEA or a vendored binary, is R4b, before any non-developer release.
- **The supported set is Node 22 (≥22.19) and Node 24 (Q3).**
  - Node 22 enters maintenance in April 2027, and a late-2026 buyer is likely on Node 24.
  - To certify Node 24, both engines' conformance suites (R0 golden, authority-v2, writes-v5, mcp-v1, cli-v1, view-v1, R3 X/Z) run on Node 22 and Node 24, on all 3 OSes, with zero tolerance. A divergence on 24 is a STOP under the scope fence.
  - The identity engine's `engines` field widens to `>=22.19 <23 || >=24 <25` only after that matrix is green.
- **`node:sqlite`**: both majors run the same pinned behavior checks. Journal mode, `BEGIN IMMEDIATE`, busy translation and the header-mask rules from R3 are re-proven on 24. The SQLite version Node bundles is recorded in `compat.json`.

## 5. Installer (F40-2, F40-3)

### 5.1 Trust anchor

- Each release publishes three files:
  - `trajecta-<ver>.tar.gz`;
  - `release.json`, which holds the version, the tarball's SHA-256 and size, and the engine SHAs;
  - `release.json.sig`, an **Ed25519** signature over the exact bytes of `release.json`.
- **Key and signature encoding (Lam R4-F5):**
  - The public key is **SPKI DER, base64**, embedded in the installer. It is loaded with `crypto.createPublicKey({key, format: "der", type: "spki"})`.
  - `release.json.sig` is the **raw 64-byte Ed25519 signature, base64**, on one line.
  - Verification is **`crypto.verify(null, releaseJsonBytes, publicKey, signatureBytes)`**, where `releaseJsonBytes` are the exact downloaded bytes, never re-serialized.
  - Tests on Node 22 and 24, on all 3 OSes, cover: a valid signature, a single flipped byte in `release.json`, a wrong key, a truncated signature, and non-base64 input. Each must give the expected result.
- **Bootstrap trust:** the installer and the key must not come only from the same mutable channel as the tarball.
  - The installer scripts are **never fetched and piped** (`curl | sh`). The documented bootstrap is: download `install.sh` or `install.ps1`, **check its SHA-256** against the value published out of band, then run it.
  - The script SHA-256s and the key fingerprint (the SHA-256 of the SPKI DER) are published in **three independent places**:
    - the product README at the signed release tag;
    - the Tam Vị Journal release page;
    - the beta purchase email.
  - An attacker would have to change all three.
  - The README states the honest limit: for the developer beta, trust rests on that out-of-band hash match plus TLS to GitHub. It is not a full supply-chain guarantee.
- **Key rotation** needs a new installer whose new hash is published in the same three places, together with a statement signed by the old key.

### 5.2 Steps, and the transaction boundary

`install.sh` and `install.ps1` are the only code that runs before verification. They are short, and they are reviewed as security code.

**Phase A: verify and stage.** Nothing visible to the user changes in this phase. A failure here deletes only the staging directory this run created.
1. **Probe Node.** Look on PATH, then in known locations (Homebrew, nvm/fnm/volta shims, `%ProgramFiles%\nodejs`), version-probing each candidate against the supported set. If none passes, write `trajecta: need Node 22.19+ or 24 LTS` to stderr, exit 1, and change nothing.
2. **Verify the release.** Check `release.json.sig` with the embedded key, using an **inline** verifier run by the probed Node (`node -e`). It performs exactly the §5.1 contract: `crypto.verify(null, releaseJsonBytes, createPublicKey({key, format: "der", type: "spki"}), signatureBytes)`. Then check the tarball's SHA-256 and size against `release.json`. Any mismatch → exit 1.
3. **Inspect, then extract (Lam R4-F5).** The system `tar` is not used.
   - The release also ships `trajecta-extract.mjs`, a small dependency-free extractor. Its SHA-256 is inside the signed `release.json`, and it is checked before it runs.
   - **Pass 1, metadata only:** it reads every gzip/ustar header (PAX `x` records are allowed only for `path`) and rejects the whole archive, before writing any byte, if any entry:
     - has a type other than a regular file (`0`) or a directory (`5`), which rules out symlinks, hardlinks, devices, FIFOs and GNU long names;
     - is a duplicate path, including case-insensitive duplicates;
     - has an absolute path, a `..` segment, a backslash or a drive letter;
     - contains `:` (NTFS alternate streams), a trailing dot or space, or a reserved DOS name (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`, with or without an extension);
     - is outside `trajecta-<ver>/`;
     - has a size that disagrees with `MANIFEST.json`.
   - **Pass 2:** it writes the files itself into `<root>/.staging-<ver>-<random>/` with mode 0644 or 0755 and no ownership changes. Then it checks every file against `MANIFEST.json` (the path set and SHA-256).
4. **Run the real entrypoint:** `node <staging>/trajecta-<ver>/product/src/cli.ts install --staged <staging>`.
5. **Run `doctor` from staging, read-only**, against the existing stores if any. A failing doctor stops the install here.

**Phase B: commit.** This is the only switch point. Lam R4-F6 applies to this phase.

0. **Lock (race-safe; Lam #40 @ 560742a item 4).**
   - **Acquire:** create `<root>/.lock` by exclusive create (`wx`). It holds an **owner token**: 128 random bits, plus the pid, hostname and creation time. The holder deletes the lock only after re-reading it and confirming its own token.
   - **Busy:** if `.lock` exists and its pid is alive on this host (`process.kill(pid, 0)` succeeds), the run refuses with `trajecta: another install is running (pid N)`. PID reuse can only make a dead holder look alive. That case **blocks**; it never corrupts.
   - **Stale recovery is serialized** by a second mutex, `<root>/.lock.recover`, also taken by exclusive create with its own token.
     - The recoverer re-reads `.lock` **while holding `.recover`**. It unlinks `.lock` only if the file still holds the **same dead token** it first read. Then it releases `.recover` and retries acquiring `.lock` from the start.
     - Why this is safe: while a dead `.lock` exists, no acquirer can create a new `.lock`, and only one recoverer can act at a time. So the token re-read under `.recover` cannot belong to a newly acquired lock, and a contender can never delete another's fresh lock.
   - **A stale `.recover`** (its holder died mid-recovery) is never auto-broken. The run prints `trajecta install --break-lock` instructions. That command shows both tokens and requires a typed confirmation on a TTY. After the confirmation, and immediately before unlinking, it re-reads the `.recover` token and compares it with the one shown; on any mismatch it aborts and unlinks nothing.
   - **Test (M3):** 200 rounds of 4 concurrent contenders against a dead lock, plus contenders racing a live acquirer. Exactly one holder at any time; no fresh lock is ever deleted; no deadlock.
6. **Rename** `<staging>/trajecta-<ver>` to `<root>/<ver>`, on the same volume. If `<root>/<ver>` already exists and its `MANIFEST.json` digest matches, reuse it. If it exists with a different digest → exit 1.
7. **Plan.** Write `<root>/<ver>/.planned.json`, listing every path the install *will* create, with its **expected** SHA-256. A plan grants **no** ownership.
   - The expected hashes come from **actual bytes built in Phase A**, not from an assumption:
     - The launchers and wrappers are rendered from templates into staging.
     - The `.plugin` zip is **built into staging by this Node's zlib**.
     - Phase C copies those exact staged bytes into place. It never rebuilds them.
   - K3 is used only for the entry list and entry bytes. The zip archive bytes are not assumed stable across zlib versions.
8. **Update the pointer atomically (§5.3).** `current` holds **both** the new version (line 1) and the previous version (line 2), so a single rename switches the version and records the rollback target together. No second file can disagree with it.

**Ownership ledger.** `<root>/owned.json` lists the paths the product **verifiably** created. Each entry records the path, its SHA-256, and whether it is per-version or `shared` (the user-bin launcher and the wrappers in `<root>/bin`).
- An entry is added only **after** its effect is complete and its bytes are re-read and match the plan. Each update is a tmp file plus rename.
- A crash between an effect and its ledger entry leaves an unowned file. The next run compares that file to the plan: if the bytes match, it adopts it; otherwise it leaves the file and reports it.

**Phase C: post-commit, idempotent.** Running `trajecta install` again resumes here.

9. **Launcher.** Write it only if it is absent, or if it is listed in `owned.json` with a matching hash. Otherwise leave it and report.
10. **Plugin file (§6).**
11. **Store bootstrap,** only for a store that does not exist yet.
    - A bootstrapped empty store is a **valid state**. It is not rolled back: a later failure leaves it, and the next install or `doctor` reports it.
    - An existing store is never modified by install. Migration happens only through an explicit user command: the engine's `migrate-to` (no TTY gate; frozen engine contract), or the product's `trajecta migrate-to --using`, which requires a backup and a typed TTY confirmation (§12.2).
12. **`doctor`.** A failure here exits non-zero. The new version stays committed, so the user can run `trajecta install --rollback`.

**Rollback.** `--rollback` swaps the two lines of `current` with one rename. It is allowed only if line 2 names a version directory whose `MANIFEST.json` still verifies. The swap is its own inverse, so rollback is always possible after any committed switch whose previous version is intact. Uninstall never removes the version named on line 2 while line 1 points elsewhere.

**Re-entry invariants:**
- A run interrupted in Phase A leaves at most a `.staging-*` directory, which the next run removes.
- After step 8, the system runs either the old version or the new one, never a mix.
- Phase C steps are idempotent, and each one is ledgered when it completes.
- **Crash tests (M3)** kill the process: after the rename; after `.planned.json`; on each side of the `current` rename; and between each Phase C effect and its ledger entry. A re-run must converge, and `--rollback` must work from every committed state.

### 5.3 The pointer, launchers and the MCP bootstrap wrapper (one design for all OSes)

- **Pointer:** `<root>/current` is a **text file** with two lines: the current version, then the previous version (or an empty line). It is not a symlink and not a directory.
  - Launchers read only line 1: `read -r` in sh, `set /p` in cmd.
  - Updates write `current.tmp`, flush it, then `rename` it over `current`. That is `MoveFileExW` with replace-existing on Windows, which is atomic on the same NTFS volume, and POSIX `rename(2)` elsewhere.
- **Node path, bound per version (Lam #40 @ 560742a item 3):** `<root>/<ver>/node` is a text file inside the version directory, holding the absolute path of the Node binary probed by **that** install. It is written into staging in Phase A, so it is covered by the step 6 rename. There is no root-level `node` file. The pointer switch therefore changes the version and its Node path together, and `--rollback` returns to the old version **with its own** recorded Node.
- **Launchers** are **OS-native**, so they run even when Node is gone:
  - POSIX: `<root>/bin/trajecta` (sh) and `<root>/bin/trajecta-mcp` (sh).
  - Windows: `<root>\bin\trajecta.cmd` and `<root>\bin\trajecta-mcp.cmd`.
  - Each one reads line 1 of `current`, then `<root>/<ver>/node`, re-probes that Node's version, and on failure writes `trajecta: need Node 22.19+ or 24 LTS` (or `<server>: need …` for the MCP wrapper) to stderr and exits 1.
  - Otherwise it runs `"<node>" "<root>/<ver>/product/src/cli.ts" …` with stdio passed through.
- **Install root:** `~/.trajecta/` on POSIX and `%LOCALAPPDATA%\Trajecta\` on Windows. The user bin directory gets a copy or link of the `trajecta` launcher. If that directory is not on PATH, the installer prints the one line to add. It never edits shell rc files.

### 5.4 Uninstall

- `trajecta uninstall` removes **only paths in `owned.json` whose current SHA-256 still matches**.
- **Shared paths** (the user-bin launcher and `<root>/bin` wrappers) are removed only by a **full** uninstall, and only when no version remains installed. `trajecta uninstall --version <old>` never touches them, even when their hashes match (Lam R4-F6).
- A changed or unlisted file is kept and reported.
- A directory is removed only if this install created it **and** it is empty.
- Stores, profiles and client configs are never touched. The command prints where the data remains.
- **One owner-authorized exception: `<root>/update-state.json` (Lam #41 F41-5; §12.2).** It is not in `owned.json`, so the rules above never remove it. Only a **full** uninstall may, and only when all of these hold:
  - no version remains installed after this run's other removals have succeeded; if any removal failed or was refused, the state file is kept;
  - the path is exactly `<root>/update-state.json`, a regular file (not a symlink), inside the `<root>` this installer owns;
  - the owner types the confirmation on a TTY, after a warning that replay protection and the key-rotation chain reset. No TTY, `--yes`, or a mismatched answer keeps it;
  - it is removed by a single unlink under the install lock. If the unlink fails, the file is intact and the failure is reported.
  - `uninstall --version`, `--rollback` and `update` never remove or rewrite it, except `update` advancing it as §12.2 defines.

### 5.5 Upgrade from a Python install

- The installer **detects** an old venv install (the `install/` layout, a Python plugin, or an MCP config whose command is a Python interpreter).
- It **reports** what it found and prints the exact replacement config.
- It changes none of it. Replacing a client config is the owner's action (Q7).

## 6. TS plugin builder with a Node payload (from R2e K; F40-3)

`trajecta plugin` builds the `.plugin` file, which satisfies K1–K6.

- **`.mcp.json` command:** the **OS-native MCP wrapper**:
  - POSIX: `{"command": "/bin/sh", "args": ["<root>/bin/trajecta-mcp", "<server>", …]}`.
  - Windows: `{"command": "cmd.exe", "args": ["/d", "/c", "<root>\\bin\\trajecta-mcp.cmd", "<server>", …]}`.
  - `/bin/sh` and `cmd.exe` always exist. So when Node vanishes, the **wrapper** still runs and prints the refusal. This replaces the earlier "absolute Node path" design, because spawning a missing binary fails before any script runs. It closes the #35 carry.
- **The payload is not copied:** the wrapper resolves `current`, so an upgrade needs no plugin rebuild. K3 reproducibility is defined given the same install root.
- **K4:** the environment-default rules are unchanged (P24 on Windows, `_sh_value` on POSIX), and they now live in the wrappers.
- **K2:** atomic write in the destination folder, as P22.
- **MCP stdio through `cmd.exe /c`** on Windows is proven end to end in M5: an `initialize` round trip with byte-exact framing.

## 7. Retiring the Python writer, and deciding G13, G14, G17 and import-aml

- **Python writer retired.**
  - `install/install.sh` and `install.ps1` are replaced by the product installer, and the old scripts print a pointer to it.
  - The Python `plugin`, `setup` and `mcp_server` entry points stay importable, because the oracle and CI need them, but they are **not shipped**.
  - The README's install section moves to the product.
  - **The oracle stays in CI as a reader for one release.** All corpora keep running against Python until the release after 0.5.0.
- **G13 → P25, refuse silent profile overwrite.** This is an explicit **oracle patch in both runtimes**: Python is patched first, then TS. The corpus diff is audited: the old G13 case is removed **by name** and its replacement cases are added. No other corpus byte may change except MANIFEST digest fields, and those are checked mechanically as in #37.
  - If a `.json` or URL profile would overwrite an installed profile of the same name, and the R2d install-writer bytes differ, the command refuses with a typed error (`ProfileConflict: profile '<name>' differs from the installed copy; pass --replace-profile to overwrite`) and exits 1, with no write.
  - `--replace-profile` keeps today's overwrite, after writing a backup `profile.json.<UTC timestamp>.bak`.
  - Identical bytes are a no-op.
  - **Comparison:** compare the incoming R2d install-writer bytes (`json.dumps(data, ensure_ascii=False, indent=2) + "\n"`, UTF-8; TS `jsonWith(profile=true)`) directly with the installed `profile.json` bytes. The installed file is never parsed for this comparison. Equal bytes are a no-op; any byte difference, including whitespace or key order, is a conflict. Incoming invalid JSON is refused first, as today. Accepted CPython constants (`NaN`, `Infinity`, `-Infinity`) keep their existing writer spelling. R0 canonical JSON is unchanged.
  - **Provenance:** Codex S1, Aux settlement: P25 compares R2d install-writer bytes, not R0 canonical JSON.
  - **Backup name:** `profile.json.<UTC YYYYMMDDTHHMMSSffffffZ>.bak`. If that name already exists, append `.1`, `.2` and so on; an existing file is never overwritten.
  - **Failure:** the backup is written first. The new profile is written to a temporary file in the same folder and committed with `os.replace` (P22 pattern). On any failure the installed `profile.json` keeps its exact bytes, and a backup that was already written is left in place and reported.
  - The corpus case that pins today's overwrite is replaced by three cases: conflict, replace and identical.
- **G14 → P26, a dry run leaves nothing.** This is an explicit **oracle patch in both runtimes**, with the same audited-diff rule as P25. The frozen R2d G14 history stays in the R2d spec; it is superseded, not rewritten.
  - `migrate-to --dry-run` records every parent directory it created.
  - On exit, success or failure, it removes exactly those, deepest first, and only if they are still empty.
  - A directory that existed before the dry run is never touched.
  - Corpus: a dry run on a missing parent chain leaves the original file tree.
  - **Verification:** the test records the directory inventory before the run and checks that the inventory after is equal. A case where a parent appears *during* the dry run (created by another process) proves that directory is kept, because it is not in the created-by-this-run list.
  - Frozen corpus payloads keep their provenance. The pinned G14 case is replaced by name, and the R2d spec text is not edited.
- **G17: keep Law F-1 as the permanent product HTTP law (Q5).** On malformed or over-limit input, TS may be stricter than the oracle, never more permissive. G17 closes as accepted. The wording nit, "oversized header line" meaning over the limit, is fixed in the same PR.
- **`import-aml`: archive (Q6).** It moves to `tools/archive/` with a README, it is not shipped, and it is not ported. It was a one-shot import for Ty's own AML vault, not product write law.
  - **Provenance:** Codex S2, Aux settlement: authority-v2, writes-v5, mcp-v1, cli-v1 and view-v1 MANIFESTs may re-key `oracle_sources[trajecta_identity/migrate_aml.py]` to `tools/archive/migrate_aml.py`. The archived source stays byte-identical, old and new digests must match, and only this key rename plus permitted digest-field changes are allowed. Generators list the archive path explicitly, never glob `tools/archive/*`.

## 8. Gates (all on exact heads; zero tolerance)

| Gate | What it proves |
|---|---|
| **M1 engine matrix** | Every identity corpus and R3 X/Z, plus the work engine suite, on {macOS, Windows, Linux} × {Node 22, Node 24} |
| **M2 product contract** | **Pass-through:** over the full cli-v1 corpus and the work CLI suite, argv, stdin, cwd and env are preserved, and stdout, stderr and exit code are byte-exact (§2.3). **Authority:** the adapter lint and source scan are clean, the differential authority test passes, and the write-trace test passes (§2.4). **Build:** two builds produce byte-identical tarballs, `MANIFEST.json` verifies, and `compat.json` is regenerated with an empty diff. **Offline:** in a network-disabled sandbox, the tarball is unpacked, `trajecta version` reports both engine SHAs, and an identity `retrieve` and a `work` round trip run with no Git or npm access |
| **M3 clean-machine install** | On each OS, with Node 22 and with Node 24: install → doctor → `identity retrieve` → `work` round trip → uninstall. Store bytes are unchanged by uninstall, and `<root>/owned.json` ownership is respected (a modified launcher is kept). **The no-Node case runs in a proven isolated environment:** a Linux container image that has no `node` (asserted with `command -v node` failing first); on macOS and Windows, PATH and the known-location roots point at an empty temp tree, and the test first asserts that the probe list resolves nothing. **Faults are injected** at every Phase A/B/C step boundary (signature, SHA, a tar path-traversal entry, a file digest, doctor, the rename, the pointer write, the plugin write). Each must land in the state §5.2 promises, and re-running install must converge |
| **M4 upgrade from Python** | A fixture with the old venv install and an R3-era store: the installer detects it, prints the replacement, changes nothing, and the TS runtime reads and writes the store under the R3 laws |
| **M5 plugin** | K1–K6 exact. The `.mcp.json` command is the OS-native wrapper. With Node removed, the wrapper prints the `<server>: need …` refusal and exits 1. With Node present, an MCP `initialize` round trip through the wrapper is byte-exact on all 3 OSes, including Windows `cmd.exe /c` |
| **M6 P25/P26** | Both runtimes, new corpus cases, three seeds |
| **M7 oracle reader** | The Python oracle still passes every corpus against TS-written stores (one-release rule) |
| **M8 owner rehearsal** | Ty's real-copy M receipt (R3 §4) on the release candidate. **This gates the release tag, not the merges.** |

## 9. PR plan

1. **Spec**: this file.
2. **Identity repo**: P25, P26, the corpus updates, the `tests.yml` version fix, the G17 wording fix, the `import-aml` archive, and the Node 24 matrix for the identity corpora (M1, M6, M7).
3. **Work repo**: the Node 24 matrix, and a tag for the pinned commit (M1).
4. **New `trajecta` repo**: product package, CLI, version, `compat.json`, installer, plugin builder, uninstall, and the M2–M5 CI. It ships as four sequential PRs, each reviewed by Lam at its exact head: **4a** foundation (engine lock and vendoring, deterministic build, CLI pass-through, adapter, version, `compat.json`, and the pass-through and authority parts of M2); **4b** installer and uninstall (§5, M3); **4c** plugin builder and wrappers (§6, §5.3, M5, `bin/`); **4d** `trajecta update` (§12.2 and its M2/M3 additions). The repo is private until cutover.
5. **Cutover**: README and docs move, the old install scripts become pointers, and release 0.5.0 is tagged after M8.

Merge rule: unchanged. Lam approves the exact head, CI is green on that head, there are no open findings, and Aux's review is done. Aux merges and reports to Ty.

## 10. Questions for Lam

- **Q1:** Should the product layer live in a new repo, `tamvi-journal/trajecta`, with exact SHA-pinned engines? Aux: yes, as settled in R2e §6.
- **Q2:** Should v1 require a system Node and defer bundling to R4b? Aux: yes. The buyers have Node, and bundling adds ~40–100 MB per OS plus signing work.
- **Q3:** Should Node 24 be certified in R4, alongside 22? Aux: yes. Node 22 enters maintenance in April 2027; shipping 22-only into late 2026 is buyer friction.
- **Q4:** Should distribution be a release tarball with checksum-verified scripts, with npm publish optional? Aux: yes. It keeps the paid beta controllable.
- **Q5:** Should G17 close by making Law F-1 permanent? Aux: yes.
- **Q6:** Should `import-aml` be archived rather than ported? Aux: yes.
- **Q7:** Should the installer only print a replacement for an old Python MCP config, never edit it? Aux: yes. Client configs belong to the owner (standing safety rule).
- **Q8:** Should the product version be 0.5.0? Aux: yes. It sorts after everything a user has seen.
- **Q9 — CONDITIONAL YES (Lam):** the Ed25519 key lives in a GitHub Actions `release` environment, **for the developer beta only**. The conditions:
  - **Protected trigger (Lam #41 F41-4):** the release workflow runs only by manual `workflow_dispatch`, and the `release` environment's deployment policy admits only the protected `main` branch. The first step refuses unless `github.ref` is `refs/heads/main` and the workflow file is the one on `main`. No PR, fork, tag or other ref can enter the environment. Changes to the release workflow need a reviewed PR, a CODEOWNERS rule naming Ty, and branch protection.
  - **Dispatch inputs are digests, not trust:** the version, the artifact digest, the source commit on `main`, and the digests of the M8 receipt and both reviewer receipts (§12.1). The candidate tarball and the receipts sit on a **draft** release that has no tag yet. The job re-derives every digest itself from those assets and refuses on any mismatch.
  - **Tags are created only after signing:** release tags `v*` are protected by a ruleset that lets only the release workflow create them, with no bypass for anyone else and no update or deletion. After the signer job finishes, a separate publish job (holding `contents: write` and no key) verifies the signature against the pinned public key, creates the tag on the recorded source commit, and publishes the draft. No tag exists without M8, both receipts, Ty's approval and a valid signature.
  - **Approval of an exact digest:** the signing job prints the candidate tarball's SHA-256 and the `release.json` bytes. Ty approves **that exact digest** in the environment prompt. The job re-checks the digest after approval and signs only that.
  - **No self-approval:** "prevent self-review" is enabled. No bypass for admins, where GitHub offers the setting.
  - **Isolated signer:** a separate job with only `contents: read`, no checkout of PR code, and a pinned action SHA. It never creates tags or releases; the publish job does that. The key is used through stdin to a short pinned script and never written to disk or logs.
  - **Release receipt:** the run ID, approver, digest, signature and key fingerprint are recorded as a release asset and in the release evidence.
  - **Stated honestly:** approval gates access to the secret. It does not prove the workflow code is safe, or that the key never reaches the runner.
  - **Signing and release stay disabled until Ty approves this setup.**

## 11. Lam's reviews, and how they were applied

### @ 560742a (four remaining items)
1. Step 2 now executes exactly the §5.1 `verify(null, …)` contract.
2. The stale `.installed.json` names are replaced with `owned.json` and `.planned.json`. Planned digests come from the plugin and wrapper bytes actually built in Phase A (no K3 assumption about zip bytes), and Phase C copies those exact bytes.
3. The Node path is bound per version (`<root>/<ver>/node`), so it switches and rolls back with `current`.
4. Race-safe lock: owner tokens, stale recovery serialized by a `.recover` mutex with a token re-read, a human `--break-lock` for a stale `.recover`, and a 200-round concurrent recovery test.

### @ 90be1e1 (R4-F5..F7, Q9)
- **F5:**
  - `crypto.verify(null, …)` with an SPKI-DER key and a raw base64 signature, with positive and negative tests on Node 22 and 24 (§5.1).
  - Out-of-band hash pinning of the installer and key fingerprint in three channels, no `curl | sh`, and an honest statement of the trust limit (§5.1).
  - A signed pre-inspecting extractor that refuses special, duplicate, traversal and Windows-alias entries before writing (§5.2 step 3).
- **F6:**
  - Planned and verified ownership are separate (`.planned.json` vs `owned.json`, ledgered after each effect).
  - `current` carries both lines, so one rename covers the switch and the rollback record.
  - Lock file; crash tests at every boundary; rollback always possible; shared launchers protected from a partial uninstall (§5.2–§5.4).
- **F7:** pass-through uses inherited stdio, so the bytes are exact by construction and `isatty` is preserved; signals are forwarded or re-raised; PTY acceptance on POSIX, with the Windows interactive check in M8 (§2.3).
- **Q9:** conditional yes, with every condition recorded (§10).
- **Nit:** `../../engines/` (§2.1).
- **Head note:** c463c4e (the P25/P26 detail) is folded into this head and needs the same exact-head settlement.

### @ b121be5

- **F40-1 (package):** §2.1–§2.3. Both engines have zero dependencies, so they are vendored by exact SHA with per-file digests. The release is a deterministic tarball with a `MANIFEST.json`, not `npm pack`. The bin collision is resolved. Offline unpack-and-run acceptance is in M2.
- **F40-2 (install):** §5.1 and §5.2. There is a signed `release.json` with an embedded Ed25519 key, and the flow is verify → stage → file-verify → real entrypoint → read-only doctor → rename → owned-paths manifest → atomic pointer. The failure and re-entry invariants are explicit for each phase. The no-Node case is proven isolated in M3.
- **F40-3 (plugin/Windows):** §5.3 and §6. A single text-file pointer works on every OS. OS-native sh/cmd wrappers can refuse when Node is gone. Windows MCP stdio through `cmd.exe /c` is tested in M5.
- **F40-4 (contract/authority):**
  - §2.3: the pass-through preserves argv, stdin, cwd and env, and returns stdout, stderr and the exit code byte-exact.
  - §2.4: the adapter rule, plus differential authority and write-trace runtime tests.
  - §5.2: transaction boundaries, with the bootstrapped empty store declared a valid uncompensated state.
  - §5.4: uninstall removes owned, unchanged paths only.
- **Q1–Q8:** yes, with Lam's conditions recorded inline. Q2 is for the developer beta only. Q3 holds after full 3-OS certification. Q4 holds after F40-1/F40-2. Q6 archives `import-aml` with its history kept. P25/P26 are explicit both-runtime oracle patches with audited corpus diffs (§7).
- **#41 @ f10c11a (REQUEST CHANGES F41-1..F41-3):** F41-1, M8 receipt bound to the artifact digest, required before both reviewer receipts and Ty's approval, checked by the signing job (12.1). F41-2, shared monotonic `update-state.json` outside version directories, never decreased, fail-closed recovery, rotation chain kept across rollback (12.2). F41-3, exact verify → stage → inspect → switch-only-when-compatible order, and `migrate-to --using` as verified staged execution (12.2). §12 moved after §11.
- **#41 @ 6cf5d29 (REQUEST CHANGES F41-4, F41-5):** F41-4, release by manual `workflow_dispatch` on protected `main` with digest inputs; the tag is created by a separate keyless publish job only after signing; Q9 and 12.1 item 7 agree. F41-5, an owner-authorized exception in §5.4 for `<root>/update-state.json` on full uninstall only. Nonblocking: `--reset-state` is described as a human trust reset, and M2 pins its boundary.

## 12. Release approval and updates (Ty's product question; Lam settlement 2026-10-11)

Ty's question: *what do real products do, and what makes future feature updates easiest?* This section is an architectural settlement. It does **not** authorize any release or signing setup: that still needs Ty's explicit consent.

### 12.1 Release approval in plain language (amends Q9)

1. **One immutable candidate.** A candidate is fixed by four things: the version, the tarball SHA-256 (the **artifact digest**), the pinned engine SHAs, and the CI run IDs for M1–M7. If any of these changes, the candidate is new.
2. **M8 is bound to the candidate (Lam #41 F41-1).** Ty's real-copy rehearsal (M8) runs on **this** tarball, installed by digest. It produces an **M8 receipt** that records the artifact digest, the OS and Node used, and the pass/fail of each M8 step. Aux or Lam reads the rehearsal output and writes the receipt; Ty only runs the rehearsal and is never asked to verify anything technical. An M8 receipt for any other digest does not count.
3. **Two independent reviews, after M8.** Only once the M8 receipt exists do Aux and Lam each verify the **same** candidate on their own: M1–M7 from the CI run IDs and M8 from the M8 receipt, all naming the same artifact digest. Each attaches a **reviewer receipt** to the draft release. A receipt records the reviewer, the candidate's four fields, the M8 receipt's digest, and the evidence checked. A reviewer receipt written before the M8 receipt is invalid.
4. **One plain-language release note for Ty**, written only after both reviewer receipts exist:
   - what changed;
   - what it means for users;
   - the remaining known risks;
   - that both reviews agree, M1–M8 included.
   Hashes may appear in it, but Ty is never asked to read or compare them.
5. **Ty approves or rejects that named release.** The pending GitHub `release` environment run links to the note, because GitHub's native approval screen does not reliably show arbitrary digest text. Her click is the veto: no click, no release.
6. **After approval, the signing job re-checks** the tarball digest, the key fingerprint, the M8 receipt, and both reviewer receipts, and that all three name exactly this artifact digest and candidate. A missing or mismatched receipt aborts the run before signing. Any change to the candidate voids the M8 receipt, both reviews and the approval; all must be redone.
7. **Trigger and tag (Lam #41 F41-4; §10 Q9).** Releasing starts with a manual `workflow_dispatch` on protected `main`, carrying the candidate's digests; Ty's approval gates the signer job inside the `release` environment; only after signing does the separate publish job create the protected release tag on the recorded source commit and publish the draft. So no tag exists without M8, both receipts, Ty's approval and a valid signature. Every other Q9 condition stays unchanged: protected workflow, CODEOWNERS, no self-approval, an isolated signer, and a release receipt.

### 12.2 `trajecta update`

Updates reuse the install machinery exactly: Phase A/B/C (§5.2), a versioned root, the per-version Node path, `owned.json`, the atomic two-line `current`, `--rollback`, and no writes to stores.

- **Trust:**
  - Signed release metadata is verified with a key **the installed version already trusts**: its embedded root key, or a later key reached from it through the persisted rotation chain (below). A newly fetched key is never accepted on its own.
  - The tarball's size and SHA-256 are verified, then the offline `MANIFEST.json`.
  - **Key rotation chains:** a new key is accepted only through a rotation statement signed by the currently trusted key and shipped inside a release that the current key signed. Accepted rotation statements are appended to the shared update state, so a version rollback never forgets a rotation: an older binary walks the persisted chain from its own embedded key and uses the newest key reached. A chain that does not verify from the embedded key fails closed.
- **Freshness:** the signed latest index carries a **monotonic sequence number** and an **expiry**.
  - **Shared update state (Lam #41 F41-2).** The high-water sequence and the rotation chain live in `<root>/update-state.json`, **outside every version directory**. It is not listed in `owned.json`, so neither `--rollback` nor `uninstall --version` touches it; only a full uninstall removes it, under the owner-authorized exception in §5.4.
  - It is written by temp file + fsync + atomic rename, under the install lock, and only **after** the new index has been verified and **before** any `current` switch. The sequence is **never decreased** by any command.
  - It carries its own SHA-256 line. A refused lower sequence (replay) or an expired index (freeze) changes nothing.
  - **Missing or corrupt state fails closed:** `update` refuses and prints the recovery: `trajecta update --reset-state` on a TTY with a typed confirmation, which rebuilds the state only from a freshly verified index whose sequence is at least the highest one recorded in the installed versions' `MANIFEST.json` files (each release's `MANIFEST.json` records the index sequence that published it). There is no silent re-creation.
  - **Stated honestly:** `--reset-state` is an explicit **human trust reset**. It cannot reconstruct a higher sequence the machine once saw but never installed, so after a reset the high-water mark can be lower than before, and a replay of an index between the two is possible until a newer index is accepted. The confirmation text says so. Outside this command and the full-uninstall exception, the high-water mark never decreases.
  - Full TUF-style protection is **deferred**, as an explicit developer-beta risk decision. The README discloses it.
- **Exact order (Lam #41 F41-3).** No step writes a store. No step switches `current` while the target is incompatible with the current stores.
  1. **Verify:** signed index (trust and freshness above), then tarball size, SHA-256 and `MANIFEST.json`.
  2. **Stage:** Phase A and the Phase B rename (§5.2) put the target in `<root>/<ver>/` with its own Node path. `current` is **not** written.
  3. **Inspect:** read the current stores' schema versions read-only, and check them against the target's `compat.json`, plus the Node major and OS.
  4. **Compatible:** write the update state, switch `current` atomically, then Phase C and doctor, as in install.
  5. **Not compatible (Node or OS):** refuse with the reason. The staged version stays as an inactive, ledgered directory and is removed by the next `update` or `uninstall --version`. `current` is unchanged.
  6. **Needs a newer store schema:** do **not** switch. Print the exact procedure: the backup command, then `trajecta migrate-to <schema> --using <ver>`. Exit non-zero. `current` is unchanged, and the old version keeps working on the unmigrated store.
- **`migrate-to --using <ver>`: verified staged execution.** It runs the migration with the **staged** target's engine without activating it:
  - re-verify the staged directory's `MANIFEST.json` and require it to be a version `update` staged (ledgered);
  - require the backup to exist and a typed confirmation on a TTY;
  - invoke the staged version's engine by absolute path with its own recorded Node, under the install lock;
  - after it succeeds, re-run step 3; only if the target is now compatible, switch `current` (step 4).
  - If the migration fails, `migrate-to` exits non-zero, leaves `current` unchanged, and prints the exact restore-from-backup command. It never restores or deletes anything on its own. If it succeeds but the switch crashes, `current` still names the old version, which cannot read the store: `doctor` and every command then refuse with "store needs <ver>; run trajecta update" and nothing else. This relies on the engines' existing refusal of a newer store schema, which M3 asserts. A re-run of `update` finds the staged version, re-checks, and switches.
- **Direction:**
  - An ordinary downgrade is refused.
  - Updating to the version already installed writes nothing.
  - `--version <v>` selects a specific signed release, but **never** bypasses integrity, freshness or compatibility.
- **Stores are never migrated automatically.** A schema is written only by an explicit user command: the product's `trajecta migrate-to --using`, which requires a backup and a typed TTY confirmation, or the engine's own `migrate-to` called directly, which takes an explicit target and writes a backup with no TTY gate.
- **Rollback and data:** `--rollback` is **refused** if the previous version cannot read the current store, for example after a migration. The refusal names the backup to restore with.
- **Checking for updates:**
  - `trajecta doctor` stays **offline and read-only**. It may show a notice that was verified earlier and cached.
  - `doctor --check-updates` and `update --check` make an explicit network check.
  - Nothing ever downloads or installs on its own.
- **What changed:** each release ships a `CHANGELOG.md` entry in plain language and a generated `compat.json`. `update` prints the changelog entries between the installed version and the target before switching.

### 12.3 Gates added

- **M2:** signed metadata (valid, tampered, wrong key, rotated key with chain, rotated key without chain, rotation remembered after `--rollback`); sequence replay and expiry; replay attempted after `--rollback`, after `uninstall --version` + reinstall, and after a crash at each update-state write; missing and corrupt update state fail closed; `--reset-state` sets the floor from installed MANIFESTs exactly, and the test pins that an index between that floor and the previously seen higher sequence is accepted only after the typed reset, never without it; downgrade and same-version refusal; compatibility preflight refusal; TTY-only product `migrate-to --using` after an update (the product guard, not the engine).
- **M3:** crashes at every Phase A/B/C boundary during an update, and around the update-state write; the exact order in 12.2, asserting that `current` never names an incompatible version; `migrate-to --using` from a staged target, a migration failure, and a crash between migration and switch followed by a converging re-run; re-run convergence; rollback, and its refusal after a migration.
- **M5:** the plugin wrapper keeps working across an update without a rebuild.
- **M3 (uninstall, F41-5):** `update-state.json` survives `uninstall --version`, `--rollback`, a refused or non-TTY full uninstall, a full uninstall where another removal failed, and a symlink at that path; it is removed only by a confirmed full uninstall with no version left.
- **Release workflow (F41-4), checked before Ty's Q9 consent:** a dispatch from any ref other than `main`, a mismatched digest input, a missing receipt, or a tag created outside the workflow are each refused, run in a dry-run repository without the key.
- **M7:** the old Python reader still reads stores written by the updated version.
- **M8:** Ty's real-copy rehearsal, run on the release candidate by digest, producing the M8 receipt (12.1). The signing job refuses without it.

R4b still owns Node bundling before any non-developer buyers.
