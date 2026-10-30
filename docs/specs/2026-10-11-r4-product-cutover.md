# R4: the Trajecta product layer, installer, and cutover

Status: approved by Lam @ 8dae7e3; §12 added after Ty's product question (Lam settlement 2026-10-11), revised after Lam #41 @ f10c11a (F41-1..F41-3) and @ 6cf5d29 (F41-4, F41-5); PR 4a preflight settlements (Codex P4a-1..4) added; §2.3 pass-through moved in-process so signals are delivered exactly once in every topology (Aux R1-1, Lam R44-1); PR 4b preflight settlements (Codex P4b-1..4), full uninstall made a durable resumable transaction with signed-release-bound recovery (MANIFEST digest now in signed release.json) and ledgered controls/dirs (Lam R45-1..7); lock removal by per-identity exclusive claim, replacing `.lock.recover` (Codex break-race STOP), with required claim cleanup (Lam R45-8); terminal `.uninstall/` cleanup in a fixed crash-convergent order, with signed files carried in the recovery copy (Codex STOP @08644c1, Lam R46-1); writer-lifetime law, every writer under the lock is the lock owner's process (Codex STOP @88f19af). Revised after Lam's review @ b121be5 (REQUEST CHANGES: F40-1..F40-4; Q1–Q8 yes with conditions; §11). Author: Aux (leader). Builds on R0–R3 and R2e (main @ efa5149).

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
  - `release.json`, which holds the version, the tarball's SHA-256 and size, the engine SHAs, and the **SHA-256 of the tarball's `MANIFEST.json`** (added after Lam R45-6, so that a retained MANIFEST can be authenticated without keeping the tarball). The release build computes that digest from the exact `MANIFEST.json` bytes it packs. Install refuses a release whose `release.json` digest does not match the extracted `MANIFEST.json`;
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
- **Before a production key exists (Codex P4b-1).** Until Ty gives Q9 consent and a reviewed key is embedded, the installer's trust-anchor constant is **empty**. With an empty anchor, production install fails closed with `trajecta: no trusted release key configured` and changes nothing.
  - Production install also refuses any artifact whose `MANIFEST.json` says `"artifact": "foundation"`.
  - 4b tests exercise the real verify, stage, commit and doctor paths on a **non-release foundation fixture**, signed with an ephemeral key generated in test-process memory and never written anywhere. A test-only `--import` hook substitutes both the anchor and the foundation allowance, using the same seam pattern as the 4a test seams. There is **no** environment variable, flag or config file that changes trust in production code, and a source scan enforces this.
  - The wrapper and plugin effects in `.planned.json` arrive with 4c. In 4b the planned set holds the version directory, its Node path and the ledger, and it is extensible.

### 5.2 Steps, and the transaction boundary

`install.sh` and `install.ps1` are the only code that runs before verification. They are short, and they are reviewed as security code.

**Store bootstrap (Codex P4b-2).** Install bootstraps identity through its public `init` and nothing else. Install **never writes work state**. A missing work store is the work engine's valid lazy-empty state: `TrajectaStore.list()` treats missing state as an empty `trajecta.state/v1` store. Install fabricates no work or capability event, and doctor checks work read-only through its public API. An existing identity store at legacy v4 makes doctor refuse, which is the engine's own behaviour, and install never migrates.

**Phase A: verify and stage.** Nothing visible to the user changes in this phase. A failure here deletes only the staging directory this run created. **The whole install (Phases A, B and C) runs under the single install lock (Codex P4b-3).** The lock is taken right after the Node probe, so no two runs ever stage concurrently.
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
4. **Run the real entrypoint in the lock owner's own process (amended after Codex's reproduced writer-lifetime STOP).** The verified staged product entry is **imported in-process** through a narrowly scoped adapter call (`runStagedInstall(staging)`), not spawned as a child. The verified extractor (step 3) is imported the same way.
   - **Writer-lifetime law:** every write under `<root>` or to a store made while the install lock is held comes from **the lock owner's process**, whose pid is the one recorded in the lock. No child process writes, so killing the lock owner kills every writer with it, and stale recovery (§5.2 lock) can never let an orphan keep writing under a new holder's lock.
   - **Node handoff happens before the lock:** if the probe in step 1 selects a different supported Node than the one running, the bootstrap re-executes under that Node (POSIX `exec`; on Windows, the PowerShell bootstrap starts it and waits, and the bootstrap itself writes nothing), and only then is the lock acquired.
   - **Reads may still use child processes**, such as a version probe, but a child never writes under `<root>` or to a store.
   - **M3 regression:** Codex's real-path schedule. The staged step pauses at bootstrap-before-effect, the owner is killed, and a new holder acquires the lock. The test must show that no orphan writer exists: identity is not bootstrapped and `owned.json` is not written by the dead run, the new holder's token is unchanged, and a later run converges.
5. **Run `doctor` from staging, read-only**, against the existing stores if any. A failing doctor stops the install here.

**Phase B: commit.** This is the only switch point. Lam R4-F6 applies to this phase.

0. **Lock (race-safe; Lam #40 @ 560742a item 4).**
   - **Acquire (publication primitive amended, Codex P4b-3):** the run writes its complete owner record to `<root>/.lock.<token>.tmp` and fsyncs it. The record holds the **owner token** (128 random bits) plus the pid, hostname and creation time. It then publishes with `link(tmp, <root>/.lock)`: an atomic exclusive create that fails with EEXIST and never exposes partial content. Finally it unlinks the tmp file. The same primitive publishes the claim files below. The holder deletes the lock only after re-reading it and confirming its own token.
   - **Removing a lock that is not your own: one claim per lock identity (amended after Codex's reproduced break race on d27abfd).** A compare-then-unlink is two filesystem calls. If two removers both confirm the same dead lock, one unlinks it, a new installer publishes a fresh lock, and the other then unlinks that fresh lock. So **no remover ever unlinks `.lock` without first winning an exclusive claim on that lock's identity**:
     - **Identity:** for a readable lock, its owner token. For an unreadable lock (empty, truncated or unparseable), the SHA-256 of its exact bytes. A fresh lock is always readable, because of the link primitive, and carries a new random token, so its identity never equals a dead lock's.
     - **Claim:** the remover publishes `<root>/.lock.claim.<identity>.<n>` with the link primitive (exclusive, starting at n = 1). The claim records the remover's pid, hostname and token. **Only the winner of the claim may unlink `.lock`**, and only after re-reading it and seeing the same identity. Losers abort and unlink nothing.
     - **Why this is safe:** while the claimed lock exists, no acquirer can publish `.lock`. Its owner is dead, so it never releases it. Every other remover needs the same claim name and loses. So between the winner's re-read and its unlink, `.lock` can only be the claimed dead lock, and a fresh lock can appear only after the winner has removed it. A remover that confirmed earlier and resumes late then fails to claim, or finds a new identity, and aborts.
     - **Automatic recovery** (readable lock, pid dead on this host) and the **human `--break-lock`** (an unreadable lock, or a lock whose owner is on another host) use this one protocol. The human path additionally requires a TTY, shows the bytes (hex where unprintable), size, mtime and identity, and takes a typed confirmation before claiming. For an owner on another host, that confirmation is the owner's assertion that the remote process is not running. This is the one case this protocol cannot prove, and the prompt says so. There is no separate `.lock.recover` mutex any more.
     - **A dead claim:** if the winner of claim n dies between claiming and unlinking, the lock and claim n remain. A later remover may take claim n+1 only if claim n's recorded pid is dead on this host. This is the same pid rule as automatic recovery, and PID reuse can only make a dead claimant look alive, which blocks and never corrupts. A claim from another host needs the human path, with the same TTY confirmation. Claims are therefore recoverable without any further mutex.
     - **Cleanup (required, Lam R45-8):** right after a run acquires `.lock`, and again before any release, the holder removes every `<root>/.lock.claim.<identity>.<n>` whose identity differs from its own token. Each must be a regular file matching that exact name pattern; there is no recursion and no other names.
       - This is safe because those identities belong to locks that no longer exist: every claim identity refers to the `.lock` that existed when the claim was made, and the holder's fresh lock has a new token.
       - A claimant that is still running and loses its file this way then finds `.lock` with a different identity on its re-read, so it aborts without unlinking.
       - The holder's own identity can never have a claim, because nobody claims a live, readable lock whose pid is alive on this host.
       - Each unlink is idempotent by name, so a crash during cleanup converges on the next acquisition.
   - **Test (M3):** 200 rounds of 4 concurrent contenders against a dead lock; contenders racing a live acquirer; Codex's reproduced schedule (breaker A delayed after its re-read, breaker B removes, live installer C acquires, A resumes), where A must fail to claim and C's lock survives; two human breakers; a breaker against automatic recovery; a claimant killed between claim and unlink, followed by recovery through claim n+1; and stale recovery → install → full uninstall leaving an empty root, including a crash at each claim-cleanup unlink, which converges and never removes the file of a claimant whose identity matches the live `.lock`. Exactly one holder at any time, no fresh lock is ever deleted, and no deadlock.
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
- A run interrupted in Phase A leaves at most a `.staging-*` directory and possibly an orphan `.lock.<token>.tmp` from lock publication. The next run removes both **only while holding the install lock**. Every run stages under the lock, so a `.staging-*` that exists while the lock is held cannot belong to a live run, and that fact is the proof of abandonment. A `.lock.<token>.tmp` whose token is not the holder's may belong to a contender between writing and `link()`. Removing it is still safe, because a contender whose `link()` fails with ENOENT or EEXIST treats the lock as busy and retries or refuses; it never proceeds. M3 covers orphan-tmp cleanup and adversarial concurrent `--break-lock` attempts, including two breakers and a breaker racing a live acquirer.
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
- **Full uninstall: a durable, resumable transaction (Codex P4b-4; amended after Lam R45-1..R45-3).** It runs under the install lock. Every step is idempotent, and a crash at any boundary converges on re-run. M3 injects a kill at every boundary listed here.
  0. **Converge the ledger.** For each version, any path listed in that version's `<root>/<ver>/.planned.json` that is missing from `owned.json` is ledgered only if its actual SHA-256 equals the planned hash. This is the same convergence a re-run of install performs; a plan alone still grants no ownership. A path whose hash does not match is not owned and is never removed.
  1. **Recovery copy, bound to the signed release (Lam R45-4).** Each version directory keeps its signed `release.json` and `release.json.sig`, which install ledgers.
     - **Before copying**, the run verifies: the stored signature with the running product's embedded anchor (§5.1); the version's retained `MANIFEST.json` bytes against the MANIFEST SHA-256 inside that signed `release.json` (§5.1). Neither a local MANIFEST nor the editable `owned.json` is ever a trust root; and each engine-free `product/` file against that MANIFEST. **The `node` path file is locally generated data, not release payload (Codex STOP on 4f3318d):** it is checked against its own ledger receipt and never against the signed MANIFEST, which cannot know a machine-specific path.
     - It then copies exactly those files to `<root>/.uninstall/` and re-hashes the product copies against the **MANIFEST values, not against a list it wrote itself**. It writes a digest list that covers the product files and the `node` file bytes, and computes that list's SHA-256 in memory. The `node` file is therefore authenticated only by the externally printed anchor.
     - **The resume command printed to the terminal carries that SHA-256 inline,** and it starts with the absolute path of the Node binary running the uninstall (`process.execPath`), written literally into the command. Resume never reads `.uninstall/node` to pick an interpreter. It is a short `node -e` verifier, the same pattern as the install bootstrap verifier (§5.2 step 2). Before it imports anything, it hashes the digest list, compares the result with the embedded value, checks every listed file and refuses on any mismatch. Code on disk therefore never authenticates itself.
     - If the printed command is lost, the fallback is the hash-checked installer bootstrap (§5.1) with `--resume-uninstall`. That re-fetches the version's signed `release.json`, verifies it, and authenticates the recovery product files against its MANIFEST before running them. It probes a supported Node itself (§5.2 step 1) and **never executes a path supplied by `.uninstall/node`**.
     - **M3 mutations:** alter one recovery file and recompute the digest list to match: resume must refuse through both the printed command and the bootstrap fallback. Alter the installed `MANIFEST.json` and `owned.json` together so they agree with each other: step 1 must refuse, because the signed `release.json` digest no longer matches.
  2. **Durable intent.** Atomically replace `current` with the single line `uninstalling`. `owned.json` stays authoritative until finalization. While the sentinel is present, every memory command refuses (identity, work, the MCP and plugin launchers, and the 4c wrappers) with `trajecta is being uninstalled; resume with: <resume command>`. **The only commands allowed under the sentinel are `uninstall --resume` and `uninstall --status`**. Install, update and rollback all refuse. Rollback protection ends at this step, by design: a full uninstall removes every version. **Where the refusal lives:** in the launchers and wrappers, which already read `current` to pick a version (4c). The installed product's own commands check it in their install, update and rollback code paths. The in-process engine dispatcher (§2.3) stays free of side effects and is never asked to read the sentinel. Until 4c lands, 4b tests the sentinel through the product's installer commands and through a test launcher that reads `current`.
  3. **Versions (Lam R45-2, R45-5).** Delete the current version last. Install ledgers every path it creates inside a version directory, each with its expected SHA-256, and that includes the per-version control files `.planned.json`, `MANIFEST.json`, `release.json`, `release.json.sig` and `node`. Install also ledgers **every directory it creates**, as a directory entry.
     - Uninstall removes only ledgered files whose current hash matches. A control file that was altered, or that has no ledger receipt, is **retained and reported**, like any other modified file.
     - It then removes the ledgered directories **deepest first**, each with a single `rmdir` that succeeds only if the directory is empty. The version directory itself is last. There is no recursive deletion, and no directory is removed unless install created it.
     - **A version remains installed if anything is left in its directory.** The run then stops: the sentinel, `owned.json`, the recovery copy and `update-state.json` all stay; the run reports every retained path and the resume command; and the owner moves those files away and resumes.
     - **M3 covers:** an altered `MANIFEST.json` or `.planned.json` (retained), a control file with no ledger receipt (retained), an unowned file inside a nested directory (that directory and every ancestor retained), and empty nested directories (all removed deepest first).
  4. **Shared paths.** Only when no version remains, remove the shared ledgered paths whose hashes match. Any failure stops the run, keeping everything listed in step 3.
  5. **The owner's decision on `update-state.json`** comes **before** any control file is removed, under its exception below. The run asks on a TTY. Confirmed: unlink it. Declined, no TTY, or `--yes`: it is kept, and the uninstall still finalizes. A root that holds only `update-state.json` is a valid "uninstalled, replay state kept" end state. A crash during the prompt re-asks on resume, and the warning is never skipped.
  6. **Finalize, in this fixed order:** any `<root>/.lock.*.tmp` whose token is not the live holder's; every `<root>/.lock.claim.*` file, under the cleanup rule in §5.2; then `owned.json`; then `current`; then `.uninstall/` (by the fixed A–E terminal cleanup order below). Each must be a regular file, never a symlink, and each step is idempotent by name. Then release and unlink `.lock`, and remove `<root>` only if it is empty. A crash after `current` is removed leaves only named leftovers (`.uninstall/` and a dead lock). A later fresh install recovers the dead lock automatically. It removes a leftover `.uninstall/` only after its **product** files are authenticated against a signed release MANIFEST; if that fails, it refuses and reports them.
       - **Terminal cleanup of `.uninstall/`: a fixed order that works after any crash (Codex STOP on 08644c1; Lam R46-1).**
         - **Layout.** At step 1, the recovery copy also holds its version's signed `release.json`, `release.json.sig` and `MANIFEST.json`, at exactly those basenames, so that the copy can be authenticated after every version directory is gone. The digest list has the exact basename `.uninstall/DIGESTS.json`, and the Node path has the exact basename `.uninstall/node`.
         - **Executable vs inert.** Only files under `.uninstall/product/` can ever execute. The five named files (`node`, `DIGESTS.json`, `MANIFEST.json`, `release.json`, `release.json.sig`) are inert data. They are never executed, never used as an interpreter path, and never trusted on their own.
         - **Cleanup order.** The uninstall's own step 6 uses this order, and so does a later bootstrap fallback or fresh install. Every step is idempotent by exact name, works only on regular files (never symlinks), and never recurses.
           - **A. Authenticate what can still execute.** If any file remains under `.uninstall/product/`, verify `release.json.sig` with the trusted key (§5.1, through the §12.2 rotation chain), then `MANIFEST.json` against the signed digest, then **every remaining** product file against its MANIFEST entry. A product file that is missing is acceptable only in this terminal cleanup. A product file that is unknown or modified, or a missing or invalid signed file while product files remain, makes the run **refuse and retain everything**, and it reports the problem.
           - **B.** Unlink `node`, then `DIGESTS.json`.
           - **C.** Unlink each remaining product file, all of them authenticated in A. Then `rmdir` the directories implied by the MANIFEST product paths, deepest first, each only if it is empty.
           - **D.** With no executable file left, unlink `MANIFEST.json`, then `release.json.sig`, then `release.json`. All of these are inert, so no authentication is needed.
           - **E.** `rmdir .uninstall/`, only if it is empty. Any unexpected name keeps it, and the run reports that name.
         - **Why every crash point converges:** a crash during A, B or C leaves the signed files in place, so A can still authenticate whatever product files remain, including the case where zero remain. Once C finishes, nothing executable is left, so D and E need no trust.
         - **M3 crash cases:** a crash after each inert unlink in B and D; after each product-file unlink in C, including the moment when zero product files remain; with the printed anchor lost; and the co-tamper of a product file plus a rewritten `DIGESTS.json`, which must refuse in A and be retained. `.uninstall/node` is never executed in any case. **Terminal boundaries fail closed:** with `owned.json`, `current` or `.uninstall/` partly removed, no command acts as an installed CLI. Each crash point in step 6 has its own M3 case, which asserts the refusal message and a converging resume or reinstall.
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

## 13. PR 4c preflight settlements (Codex S1–S3 @ 74f6475; Aux settlement 2026-10-30)

These settle the three contract gaps Codex reported before writing any 4c code. They amend §2.4, §5.2 step 9–10, §5.3, §5.4 step 2 and §6 only where stated.

### 13.1 S1: install destinations and the one external path

- **Plugin destination.** Install Phase C step 10 builds exactly one plugin, for the profile named by `--profile`, at `<root>/plugins/trajecta-<safe profile>.plugin` (`safe_fs_name` as in R2d). With no `--profile`, step 10 writes nothing and prints `trajecta plugin --profile <name>`. The file is a **root-level `shared`** ledger entry: it survives version switches and is removed only by a full uninstall, when its hash still matches. A file already at that path that is not ledgered with a matching hash is left alone and reported (step 9 rule).
- **`trajecta plugin`** takes `--profile <p>` (required), `--name <label>`, the R2e defaults flags (`--house`, `--data-dir`, `--profiles-dir`, `--work-root`) and `--out <file>`. Without `--out` it writes the same root-level path as above, under the install lock, ledgered `shared`. With `--out` it writes only that file (K2 atomic, temp file in the destination folder). That file is the user's own artifact: it is never ledgered and never removed by uninstall, and the command prints where it went.
- **User-bin (redesigned after Lam R48-1…R48-6).** In automatic user-bin management the product **never deletes, renames over or replaces anything outside `<root>`**, and never creates an outside-root directory. The only other outside-root write is the user's explicit `trajecta plugin --out <file>`. Every outside-root cleanup or replacement the earlier drafts tried had a check-then-act seam, so the external surface is cut down to one no-replace create. Nothing outside the root ever needs cleaning up automatically.
  - **Where.** POSIX default `$HOME/.local/bin`; flags `--user-bin <absolute dir>` and `--no-user-bin`. Windows has **no** external file: `<root>\bin` is the directory to put on PATH, and the installer prints that one line.
    - If the user-bin directory does not exist, or is not a real directory (a symlink is fine only if it resolves to a directory the user owns), the step is skipped. The installer prints the PATH line for `<root>/bin` instead.
  - **What.** A fixed **stub** that never needs updating, because it embeds only the absolute root:
    ```sh
    #!/bin/sh
    R=<_sh_quote(root)>
    [ -f "$R/bin/trajecta" ] || { printf 'trajecta: not installed at %s; run the installer, or remove %s\n' "$R" "$0" >&2; exit 1; }
    exec /bin/sh "$R/bin/trajecta" "$@"
    ```
    - **Injection-safe (Lam R48-7).** The absolute root appears in the source exactly once, as a single `_sh_quote`d word assigned to `R`. Everything else references it as `"$R"`.
    - Diagnostics use a **static** `printf` format, with the root and `$0` passed as separate quoted arguments.
    - No path is ever interpolated into a double-quoted string or a format string. The same rule binds every generated shell source in 4c: the root launchers, `trajecta-mcp` and the stub.
    - The stub contains no other variable data. The `exec` keeps one process, because the root launcher then `exec`s Node.
    - A template change in a later product version changes only `<root>/bin/trajecta`, which lives inside the root. The stub's bytes are the same for every version with that root.
  - **How (the only outside-root write).**
    - The stub is staged **inside the root** as `<root>/bin/.user-stub`, a normal ledgered root file.
    - It is published with `link(<root>/bin/.user-stub, <user-bin>/trajecta)`. `link` is atomic and never replaces anything.
    - **`EEXIST`:** if the existing file's bytes equal the stub, it is a no-op and is reported as present. Otherwise the file is not ours: it is left untouched and reported, together with the PATH line for `<root>/bin`.
    - **`EXDEV`, `EPERM` or `ENOTSUP`** (no hard link possible): the step is skipped, with the same report and PATH line.
    - There is no temp file outside the root, no `mkdir` outside the root, no rename and no journal. A crash at any point leaves either nothing outside the root or a correct stub. Either converges on re-run, because a stub with equal bytes is a no-op.
  - **Shared inode.** The two names are hard links to one file. If anyone edits the external file, `<root>/bin/.user-stub` changes too. Its hash then no longer matches the ledger, so uninstall keeps it and reports it under the normal root rule.
  - **Ledger.** `owned.json` records the external path with `kind: "external-report"` and its `dev`/`ino`. That record is used **only to report**. It grants no authority to delete or modify.
  - **Uninstall** never touches the external file. A full uninstall prints:
    `trajecta: left <user-bin>/trajecta in place; remove it yourself if you no longer want it`.
    - If the stub runs after the root is gone, it prints its own refusal and exits 1.
    - Removing a file outside the root is the owner's action. The product never claims a foreign swap is harmless, because it never acts on that path a second time.
  - **M3:**
    - an absent user-bin directory, which is skipped and nothing is created;
    - a foreign `<user-bin>/trajecta`, before install and created concurrently just before `link`, whose bytes stay unchanged;
    - an equal-bytes stub, which is a no-op;
    - an `EXDEV` user-bin on another filesystem, which is skipped;
    - a kill on each side of the `link`, after which a re-run converges;
    - a full uninstall that leaves the external file and prints the line;
    - the stub after uninstall, which refuses and exits 1;
    - the process tree through the stub, which shows a single Node process;
    - the stub is mode 0755 (the hard link shares the inode mode) and is invoked directly by name from PATH;
    - **custom roots containing** whitespace, `'`, `"`, `$`, `$(…)` and backticks, run both with the root launcher present and after uninstall: the diagnostic and argv are exactly literal, and a canary proves that zero injected code ran.
- **Write-trace allowance (amends §2.4).** The product process may write only to: the install root; the one hard link `<user-bin>/trajecta` created by `link()` (never a write through it, never a removal); the plugin output path of the current command; and engine-mediated store paths. Nothing else.

### 13.2 S2: one product plugin, one shared MCP wrapper, recipe in argv

- **Servers.** One product plugin per profile registers **two** MCP servers: `trajecta-identity-<slug>` (engine `identity`) and `trajecta-work-<slug>` (engine `work`). `--name <label>` overrides the identity label only; the work label is then `<label>-work`.
- **Label slug (Codex review @ 1c1686b).** Server labels are not filesystem names, so they do not use `safe_fs_name` (which keeps non-ASCII letters, such as `hồ-sơ`).
  - If the profile name already matches `[a-z0-9._-]{1,46}`, the slug is the profile name.
  - Otherwise the slug is the profile name mapped as follows: Unicode NFKD, combining marks dropped, `đ`/`Đ` → `d`, lowercased, each run of characters outside `[a-z0-9._-]` → `-`, leading and trailing `-` trimmed, truncated to 37 characters. Then append `-` and the first 8 hex digits of SHA-256 of the profile's UTF-8 bytes. The hash keeps distinct profiles distinct (`hồ-sơ` and `ho-so` differ), and it also covers an empty mapping.
  - The longest default label is therefore `trajecta-identity-` (18) + 46 = 64.
  - `--name` must match `[A-Za-z0-9._-]{1,59}`, so `<label>-work` is still at most 64. Otherwise `trajecta plugin` refuses with a typed error and writes nothing.
  - Both generated labels are validated against the grammar before anything is written. The plugin **file** name keeps `safe_fs_name`.
  - Tests: a Vietnamese profile, a 48-character ASCII profile, a 60-character `--name` (refused), and two profiles whose mapping collides.
- **Recipe grammar.** `.mcp.json` calls the shared wrapper with:
  `<root>/bin/trajecta-mcp <label> --engine identity|work [--default KEY VALUE]... -- <engine args>`
  - `<label>` is the client-facing server name. It is used in the `<label>: need …` refusal and nothing else. Allowed characters are `[A-Za-z0-9._-]`, 1–64 of them; the builder generates labels as in the slug rule above.
  - `KEY` is one of exactly `TRAJECTA_IDENTITY_DATA_DIR`, `TRAJECTA_IDENTITY_PROFILES`, `TRAJECTA_WORK_ROOT` and `TRAJECTA_HOME`. Any other key, a repeated key, or a missing `--` is a usage error (exit 2) before any import.
  - Identity: `<engine args>` is `--profile <p>`. The defaults are rendered from the R2e flags, with `--work-root` producing `TRAJECTA_WORK_ROOT`.
  - Work: `<engine args>` is empty, and `--work-root` produces `TRAJECTA_HOME`.
  - Each key is defaulted independently. A preset value of one key never fills another.
- **Applying defaults (K4).** The OS-native wrapper only routes and refuses (§13.3). It passes every argument unchanged to the product's `mcp` verb in Node.
  - That verb applies each default **before** the in-process engine import. A key whose environment value is non-empty is left alone; an empty or absent key takes the default. This is P24 and `_sh_value` semantics.
  - A value starting `~/` or `$HOME/` is expanded against `os.homedir()`. If that is empty, the verb writes `<label>: cannot resolve home folder for <KEY>` and exits 1. Any other value is used verbatim.
  - Then it sets `process.argv` to the engine's MCP entry plus `<engine args>` and imports it in-process, through `engines.ts`, as in §2.3.
  - `mcp` is not a pass-through verb. Its only observable effect before the import is these environment defaults.
- **Windows argv safety.** `cmd.exe /d /c` re-parses arguments. So for a Windows target, `trajecta plugin` **refuses at build time** any label, default value or engine argument containing `% ! ^ & | < > " ( )`, a control character, or a trailing backslash. It refuses with a typed error naming the field, and writes nothing. POSIX targets accept any value, because `/bin/sh "$@"` forwards argv exactly.
- **K1 (amended).** The product plugin carries `.claude-plugin/plugin.json`, `.mcp.json` and `skills/identity-continuity/`. The skill is copied byte for byte from the identity repo at the pinned engine SHA, never from an installed plugin. The plugin carries no executable: its launcher is the root wrapper, so `scripts/` is absent. A top-level `bin/` is still forbidden.
- **K6 (scoped).** `plugin.json.version` equals the product version that built the plugin, and K6 is tested at build time. After `trajecta update` the plugin keeps working without a rebuild (§12.3 M5). `doctor` reports a built-version versus current-version difference as information, not as an error. 4d rebuilds the ledgered `<root>/plugins/*.plugin` files as part of an update. A `--out` artifact is the user's own and is not rebuilt.
- **M5 additions.**
  - Two plugins for the same root (profiles A and B, defaults `~/a` and `~/b` for the same key) run concurrently, and each sees its own value.
  - A preset non-empty value wins for each of the four keys, independently.
  - A preset empty value takes the default.
  - The Windows build-time refusal is tested for each forbidden character.

### 13.3 S3: wrapper routing and refusal precedence

The wrappers (`bin/trajecta`, `bin/trajecta-mcp` and their `.cmd` twins) decide in this exact order. Every refusal goes to stderr and exits 1. None of these steps runs Node or product code.

1. **`current` missing or unreadable:** `trajecta: not installed at <root>; run the installer`.
   - **`current` present but not a regular file, a symlink or reparse point, or over 256 bytes:** refuse as damaged (the step 3 message).
   - This is checked **before** the sentinel is interpreted (Lam P1 @ 8cd61f4), so a symlinked `current` whose target holds the sentinel bytes can never produce a false `uninstall --status`. Sentinel precedence over every Node check is unchanged.
2. **`current` line 1 is exactly `uninstalling`:** the sentinel takes precedence over every Node check.
   - `trajecta uninstall --status`, with exactly those two arguments: the wrapper answers natively with the fixed text `trajecta: uninstall in progress at <root>` followed by the resume line below. It exits 3, a distinct code, so scripts can tell "in progress" from an error.
   - Every other command, including `uninstall --resume` and every MCP start, refuses with the resume line:
     `trajecta is being uninstalled; resume with the command printed by 'trajecta uninstall', or run the installer bootstrap with --resume-uninstall`.
   - **Amends §5.4 step 2:** "allowed under the sentinel" means only through those two authenticated routes: the printed command with its embedded digest, and the hash-checked bootstrap. No local wrapper ever runs recovery code, and nothing on disk is used to choose an interpreter or to print a command. A resume command stored on disk would authenticate itself, so none is kept.
3. **Pointer and path validation (Lam R48-2).** All of the following refuse with `trajecta: installation at <root> is damaged; run the installer`, and none runs Node or product code:
   - **`current` itself:** it was already checked to be a regular file under 256 bytes in step 1. Outside the sentinel, it must be exactly two LF-terminated lines.
   - **Line 1:** it must match the product `versionName()` grammar `^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$`. It has no `/`, `\`, `:`, drive letter or NUL, and it is not `.` or `..`.
   - **Line 2:** it must be empty or match the same grammar.
   - **Any CR or other control character, or extra bytes,** is malformed.
   - **`<root>/<ver>`** must be a real directory, not a symlink or junction.
   - **`<root>/<ver>/node`** must be a regular file, not a symlink, holding exactly one LF-terminated absolute path with no control characters. The Node binary it names may itself be a symlink, such as Homebrew's: only the record file is checked.
   - **On Windows,** the `.cmd` wrappers apply the same grammar, for example with `findstr /r` anchored patterns plus a length check. If cmd cannot enforce it byte-exactly, Codex stops and reports with a repro, rather than weakening the check.
4. **The recorded Node fails the version probe:** `trajecta: need Node 22.19+ or 24 LTS` (MCP: `<label>: need Node 22.19+ or 24 LTS`).
5. **Otherwise:** POSIX `exec "<node>" "<root>/<ver>/product/src/cli.ts" "$@"` from `bin/trajecta`, and `exec "<node>" "<root>/<ver>/product/src/cli.ts" mcp "$@"` from `bin/trajecta-mcp`. The MCP wrapper always inserts the `mcp` verb (§13.2) before `<label> --engine …`; it never dispatches the label as a CLI verb. M5 asserts the exact argv on both OSes. Windows runs the same command and propagates its exit code.

**M5/M3 add** one case per row, run on both POSIX and cmd. The sentinel case is run with Node absent too, to prove the precedence. Row 3 is covered by: `../x`, an absolute path, a drive-letter path, an empty file, one line, three lines, a CRLF line ending, an oversized file, `current` as a symlink, `<ver>` as a symlink or junction, and `<ver>/node` as a symlink. Each case must refuse as damaged, and a sentinel file proves that nothing outside `<root>` ran.

### 13.4 Unchanged and binding

The extractor gets a fixed decompression cap and a physical-header/entry cap, enforced before any staging write. Also unchanged:
- sh `exec`;
- adapter-only engine imports;
- real Windows Ctrl-C evidence, or a declared limitation **after** observation;
- every exact gate;
- the empty production anchor;
- the #47 writer-lifetime law.

### 13.5 Windows native validation through system PowerShell (Codex STOP @ 85ef90a; Aux settlement 2026-10-31)

**Evidence:** product draft #3, `docs/R4C-WINDOWS-PREFLIGHT.md`, runs 41095661097 and 41096590809. Codex showed that cmd cannot enforce the §13.3 byte grammar:
- `set /p`, `FOR /F` and `FIND` read a trailing LF, a bare CR and a NUL identically;
- `FINDSTR /p` accepts a NUL;
- `FINDSTR /r` with a negated class hangs on a valid pointer.

So the Windows wrappers delegate steps 1–4 of §13.3 to one **read-only** validator run by the system's Windows PowerShell. This amends §13.3 for Windows only. POSIX is unchanged.

- **Which PowerShell (Lam P1-3).**
  - The installer resolves the system PowerShell **once, at install time**, as `<SystemRoot>\System32\WindowsPowerShell\v1.0\powershell.exe`, and writes that absolute path into the `.cmd` as a **literal**. At run time the wrappers never expand `%SystemRoot%`, PATH or `pwsh`.
  - **Install-time checks:** the path is a regular file, not a reparse point; it is ASCII; it has no `% ! ^ & | < > " ( )`; and `SystemRoot` and `windir` agree. Otherwise install refuses with a typed error.
  - **Threat boundary, stated:** the wrappers inherit their caller's environment. An actor who controls that environment can already run code in every Node process through `NODE_OPTIONS`, and in cmd through `COMSPEC`/`PATHEXT`, so a hostile inherited environment is outside what any wrapper can defend. Pinning removes the one pre-validation executable lookup the wrappers themselves would make.
  - **M5 canary:** at run time, `SystemRoot` points at a tree containing a fake `powershell.exe` that writes a marker. The marker must never appear.
- **Invocation.** `<pinned powershell.exe> -NoLogo -NoProfile -NonInteractive -EncodedCommand <base64>`.
  - The script is generated at install and embedded as UTF-16LE base64, so a non-ASCII `<root>` is carried losslessly. There is no `.ps1` file, and execution policy does not apply.
  - `<root>` appears in the script exactly once, as a PowerShell single-quoted literal with `'` doubled.
  - **Inputs.** The validator reads exactly one environment variable, `TRAJECTA_WRAPPER_DIR`, which the wrapper sets on the line before the call with `set "TRAJECTA_WRAPPER_DIR=%~dp0"`, overwriting any inherited value. It never receives user argv. If that directory, normalized with `GetFullPath` and compared ordinal-ignore-case, is not `<root>\bin\`, the result is `DAMAGED`. A moved or copied `.cmd` can never run a different tree's `cli.ts`.
  - **Length limit.** The complete `.cmd` line that carries the encoded command must be at most 8000 characters, under cmd's 8191 limit. This is checked at build time with a typed refusal, never truncated. A long-root fixture (a 240-character non-ASCII root) is in M5.
- **What it does: read-only, in order.** It reads raw bytes with `[IO.File]::ReadAllBytes` and attributes with `[IO.File]::GetAttributes`. A `ReparsePoint` attribute counts as a symlink or junction.
  1. Apply §13.3 step 1 in full: a missing `current` is `NOTINSTALLED`; a non-regular file, a reparse point or more than 256 bytes is `DAMAGED`. This happens before any byte is interpreted.
  2. Recognize the exact sentinel bytes `uninstalling\n` (step 2).
  3. Apply the full step 3 grammar, byte for byte, including the `<ver>\node` file.
  4. **Probe Node (Lam P2 @ 8cd61f4 and @ d35cdad).** Run `<node> --version` once through `System.Diagnostics.Process`:
     - `UseShellExecute = false`, with stdin, stdout and stderr all redirected and stdin closed immediately;
     - both output streams read with `ReadToEndAsync` into tasks the validator owns. Their content is used only to parse the version.
     - **Bounded wait.** `WaitForExit(10000)`. If the probe has not exited, call `Kill()` and treat the result as a timeout.
     - **Bounded drain.** Then wait at most a further 2000 ms for both read tasks (`Task.WaitAll` with a timeout). A descendant of a fake Node can keep an inherited pipe handle open after its parent dies, so the validator never waits on the tasks without that bound.
     - After the drain bound, it disposes the `Process` object, which closes its own ends of the pipes, and abandons any pending task.
     - It writes its single record and calls `[Environment]::Exit(0)`, so threads still pending cannot delay the wrapper.
     - Worst-case wall time for the probe is therefore about 12 seconds.
     - A start failure (`Win32Exception`), a kill failure, a read failure, a timeout, a non-zero exit, an output that does not parse or an out-of-range version is `ERR|NODE`.
     - A descendant that the probed binary spawned is not owned by the validator, and may outlive it. The validator never waits on it and never reads from it again.
     - Nothing the probe writes reaches the wrapper's stdout or stderr (step 4).
  - It writes no file and makes no network call.
- **Protocol: one ASCII stdout record carries both status and data (Lam P1-1).** cmd never relies on `ERRORLEVEL` after `FOR /F`. The validator always exits 0. It writes its whole stdout with a single `[Console]::Out.Write`: exactly one record, framed as `TRJ1|<body>|END` and ending in CRLF. `<body>` is one of:
  - `OK|<ver>|<node>`. `<ver>` is ASCII by grammar. `<node>` is the recorded absolute path if it is printable ASCII without `% ! ^ & | < > " ( )`. Otherwise it is that file's 8.3 short path from `GetShortPathName`, if one exists and passes the same test.
  - `SENTINEL`
  - `ERR|NOTINSTALLED`, `ERR|DAMAGED`, `ERR|NODE` or `ERR|NODEPATH`. `NODEPATH` means the recorded Node path is valid but has no cmd-safe ASCII form on this volume.
  - Output is forced to ASCII with `[Console]::OutputEncoding = [Text.Encoding]::ASCII`, and only these bytes are written. Any other stdout is impossible by construction.
- **cmd side: the parser's exact acceptance contract (Lam P2).**
  - **Trust model (Lam P1 @ d35cdad).** stdout is written only by the pinned system PowerShell running the embedded script under `-NoProfile`, in one `Write` of a fixed-grammar string. It is not an adversarial channel. The checks below are an exact acceptance contract over **observable** lines, a defence in depth against corruption, and they do not claim to detect lines that `FOR /F` cannot observe.
  1. **Records.** A first `FOR /F` with options `usebackq delims=` and `eol=` set to the backtick character reads whole lines, with no token splitting.
     - The `eol` character is the backtick, which the validator never writes. `FOR /F` skips blank lines and lines starting with a backtick. Those are **unobservable**, carry no data, and the validator never writes them.
     - Every other line is counted, including lines starting with `;` or `|`. The count must be exactly 1. The full line is kept in a variable.
  2. **Fields.** A second `FOR /F "tokens=1-5* delims=|"` splits the kept record.
     - Token 1 must be `TRJ1`.
     - The last field must be `END`, the field count must match the status exactly (`OK` has five fields; `SENTINEL` three; `ERR` four), and the remainder `*` must be empty.
     - **Canonical reconstruction (the authoritative check).** `FOR /F` collapses adjacent delimiters, so token counting is not injective (Lam's counterexample: `TRJ1|OK||0.5.0|C:\node.exe|END`). cmd therefore rebuilds the canonical wire for the selected state from the parsed tokens, for example `TRJ1|OK|!v!|!n!|END` or `TRJ1|ERR|!c!|END`. It requires that string to equal the kept full line exactly, using a case-sensitive `if "!line!"=="!canon!"` under local delayed expansion.
     - Every token must also be non-empty and match its grammar: the version grammar, the `ERR` category list, and the Node path rule.
     - So an extra, doubled, leading or trailing `|` is rejected, as are a missing or extra field, an unknown status and a missing `END`.
     - Delayed expansion is enabled only around this comparison, and the values never contain `!`, because the Node path rule excludes it.
  3. **Fail closed.** Any rejection, zero records, two or more records, PowerShell missing, or PowerShell blocked (Constrained Language Mode, AppLocker, policy) means `<prefix>: cannot validate the installation (Windows PowerShell unavailable or blocked)` and exit 1. There is never a fallback to a weaker cmd check.
  - **The wrapper formats every message itself (Lam P1-2).** `<prefix>` is `trajecta` for `trajecta.cmd` and `%~1` (the server label) for `trajecta-mcp.cmd`. The messages are the exact §13.3 texts: not installed, damaged, need Node, and the resume line. `NODEPATH` prints `<prefix>: the recorded Node path has no usable short form on this system; reinstall with Node at an ASCII path`. Every refusal exits 1.
  - **Argv safety on Windows.** The MCP wrapper's arguments come from the plugin recipe, whose labels, defaults and engine arguments are refused at build time if they contain any cmd-special character (§13.2). A manual invocation is the invoking user's own command line. The validator never sees argv.
  - **`SENTINEL`:** `trajecta.cmd` prints the native status text and exits 3 only when `%1` is exactly `uninstall`, `%2` is exactly `--status` and there is no `%3`. This holds even with Node missing, because the sentinel precedes the probe. Everything else prints the resume line and exits 1. The MCP wrapper always prints the resume line.
  - **`OK`:** `"<node>" "%~dp0..\<ver>\product\src\cli.ts" %*` from `trajecta.cmd`, or `… cli.ts mcp %*` from `trajecta-mcp.cmd`. The exit code is propagated. The root path comes from `%~dp0`, which cmd holds as UTF-16, so a non-ASCII root works. The validator has already proven that `%~dp0` is `<root>\bin\`.
- **Unchanged.** No product or engine code runs before `OK`. The only earlier Node process is the one `--version` probe on the validated path. PowerShell exits before the engine starts, so it is never the engine's parent. Ctrl-C evidence is still observed through the `.cmd`.
- **M5/M3 (Windows):**
  - Codex's LF / CR / NUL fixtures and every §13.3 row are each refused or accepted exactly, through both wrappers;
  - the outcomes `OK`, `SENTINEL` and each `ERR`, including status exit 3 with Node missing;
  - a reparse-point `current` whose target holds the exact sentinel gives `ERR|DAMAGED`, with no Node and no status exit 3 (POSIX: a symlinked `current`, the same result);
  - framing faults fed through a test-only validator stub are each refused: an extra `;` line, an extra `|junk` line (now counted), two records, a fourth field, a missing field, a missing `END`, a wrong magic, and Lam's exact `TRJ1|OK||0.5.0|C:\node.exe|END` (refused by reconstruction);
  - an extra backtick-leading line is documented as unobservable, and the test asserts that this is the only skipped form;
  - a fake Node that spawns a descendant holding the redirected pipes open, then hangs or is killed: the wrapper returns the `need Node` refusal within the bound (about 12 seconds) with no leaked bytes;
  - a fake `node` that writes to stderr and exits non-zero, and one that hangs: exactly the wrapper's refusal appears, with none of the fake's bytes and no hang beyond the timeout;
  - MCP labels appear in the refusals of two concurrently configured servers;
  - a reparse-point `current`, a `<ver>` junction and a symlinked `node` file are each refused;
  - a moved `.cmd` is refused as `DAMAGED`;
  - the fake-`powershell.exe` canary never runs;
  - a `ConstrainedLanguage` session and an AppLocker-blocked PowerShell each fail closed;
  - a non-ASCII root and a non-ASCII Node path (short-path success, and `NODEPATH` with 8.3 disabled) give exact argv bytes;
  - exactly one success record is read, and no `--version` text leaks;
  - the 240-character-root length fixture, plus a build-time refusal above 8000 characters;
  - the process tree at engine start contains no PowerShell;
  - latency is recorded, and is not a gate.

### 13.6 PR 4c preflight S4 and S5 (Codex STOP @ b0d822b; Aux settlement 2026-10-31)

**S4: what the release archive's `bin/` holds.** A release cannot contain rendered wrappers, because their bytes depend on `<root>` and, on Windows, on the pinned PowerShell path. Neither is known at build time (Codex rendered roots A and B and got different SHA-256s). So the archive carries **templates**, and install renders them, as §5.2 step 7 already says: "rendered from templates into staging". This amends §2.2.

- **Archive layout.** `bin/templates/` holds exactly six files:
  - `trajecta.sh.tmpl`
  - `trajecta-mcp.sh.tmpl`
  - `user-stub.sh.tmpl`
  - `trajecta.cmd.tmpl`
  - `trajecta-mcp.cmd.tmpl`
  - `validator.ps1.tmpl`

  They are listed in `MANIFEST.json` like every other file. They are root-independent and byte-deterministic, so two builds give identical tarballs. They are mode 0644: templates never execute.
- **Release completeness (replaces "bin/ present and complete").** A build with `"artifact": "release"` refuses unless the six templates are present, and each contains exactly its documented placeholder set (below). A foundation artifact still has no `bin/`.
- **Placeholders.** These are the only tokens. Each template declares the exact count of each token it contains, and the renderer checks those counts.
  - `@@ROOT_SH@@` = `_sh_quote(<root>)` (POSIX templates).
  - `@@ROOT_PS@@` = `<root>` as a PowerShell single-quoted literal, with `'` doubled (validator).
  - `@@POWERSHELL@@` = the install-pinned absolute PowerShell path (§13.5), which is already validated as ASCII with no cmd-special characters (`.cmd` templates).
  - `@@ENCODED_VALIDATOR@@` = the base64 UTF-16LE of the rendered `validator.ps1` (`.cmd` templates).
- **Renderer.** It is a pure function in `product/src`.
  - **Single pass, positional.** It splits the template on the token literals and joins the pieces with the values. A value is never scanned again, so a root that itself contains `@@ROOT_SH@@` cannot inject.
  - **It refuses** with a typed error if any token count differs from the declaration, if any template literal segment contains `@@`, or if a value fails its rule.
    - All of these are checked on the **template**, before any value is inserted (Codex review). The template is split on the four token literals; every literal segment between them must be free of `@@`, so an unknown or malformed token is caught in the template itself.
    - The rendered output is **never** scanned for `@@`. A legitimate root such as `/tmp/@@ROOT_SH@@` therefore renders, and stays inert inside its quoted value. The rules: the §13.5 checks for the PowerShell path, and for `<root>` the 8000-character limit on the `.cmd` line.
  - **Output.** The rendered bytes go to staging in Phase A. Their SHA-256s go into `.planned.json`, and Phase C copies those exact bytes (§5.2 step 7). Rendered wrappers are ledgered root files at `<root>/bin/`.
- **Tests (M2/M3/M5).**
  - Two release builds are byte-identical.
  - Rendering roots A and B gives different bytes, and each matches the expected output exactly (golden files with the placeholders filled).
  - A root containing a token literal, `'`, `"`, `$`, `` ` `` or whitespace renders safely.
  - A missing template, an extra token, or an unknown `@@…@@` in a template literal segment each make the build or the install refuse. A root containing `@@ROOT_SH@@` renders, and its golden output matches exactly.
  - The release completeness refusal is exercised.

**S5: a custom `--db` must reach the MCP recipe.** `install --profile example --db <temp>/identity/custom.sqlite3` bootstraps that file. A profile-only recipe would then open the engine's default `<data dir>/example.sqlite3`, so the plugin would show a different, uninitialized store. The frozen identity MCP entry already accepts `--db` (`node/src/mcp.ts`, `argumentsFrom`), so no engine change is needed.

- **Recipe (amends §13.2).** The identity `<engine args>` are `--profile <p>`, followed by `--db <absolute path>` when a database path was given. Work args are unchanged.
- **Where the path comes from.**
  - Install step 10 uses the install's `--db`, resolved to an absolute path, when one was given.
  - `trajecta plugin` gains `--db <path>`, also resolved to an absolute path.
  - Without `--db`, the recipe stays profile-only, and the engine's own default resolution applies at run time, honoring `TRAJECTA_IDENTITY_DATA_DIR`.
- **Precedence is the engine's.** An explicit `--db` in the recipe wins over `TRAJECTA_IDENTITY_DATA_DIR`. That is the frozen engine behavior, unchanged. The `--data-dir` default still applies to everything else the engine reads from it.
- **Safety.** For a Windows target, the `--db` value goes through the same build-time refusal as every other recipe argument (§13.2). On POSIX it is forwarded exactly.
- **M5 additions.**
  - The install `--db custom` case: the plugin's MCP `initialize` plus `identity_status` show the custom store, initialized, with the same path the CLI reports.
  - A profile-only plugin with `TRAJECTA_IDENTITY_DATA_DIR` set resolves the default name under that directory.
  - A Windows `--db` containing a cmd-special character is refused at build time.
