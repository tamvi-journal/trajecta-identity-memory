# R4: the Trajecta product layer, installer, and cutover

Status: draft for Lam's review. Author: Aux (leader). Builds on R0–R3 and R2e (main @ efa5149).

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

## 2. Product layer: the `trajecta` repo (Q1)

A new repo, `tamvi-journal/trajecta` (Apache-2.0). It is thin, and it owns only product-level concerns:

- **`package.json`**:
  - `name: trajecta`, with the single product version (§3);
  - the engines as **exact pinned dependencies**: git URL + commit SHA, plus a lockfile with integrity hashes;
  - `bin: trajecta`.
- **`src/cli.ts`**, the product CLI. It dispatches to the engines and adds only product verbs: `install`, `doctor`, `plugin`, `version`, `uninstall`. `trajecta identity …` and `trajecta work …` pass straight through to the engine CLIs, so their output is byte for byte the engine's.
- **`compat.json`**: the compatibility matrix. Product version → engine SHAs → supported Node majors and OSes → the store schema versions it reads and writes. CI generates it and checks it. It is never hand-edited.
- **Release evidence**: each release attaches the CI run IDs and the M-gate receipts (§8).

The layer **must not** write to either store except through an engine API. A test scans the product source and rejects any direct SQLite or work-store file write.

## 3. One version (closes K6)

- **The product version** is `trajecta`'s `package.json` version. It starts at **0.5.0**, so it sorts after every number a user may have seen (0.4.0 pyproject).
- **Engine versions** stay as each engine's own `package.json` version. They are **not** user-facing; `trajecta version` shows them as "engine" lines.
- **Wire and runtime versions** (the 0.1.0 inside protocol/schema fields) are protocol constants, not product versions. They are unchanged, and the corpora pin them.
- **pyproject 0.4.0** freezes as the oracle's version. The Python package is not released again.
- `plugin.json.version`, `trajecta version` and the release tag must be equal. **K6 becomes an exact test.**
- `tests.yml` derives the wheel filename from pyproject (fixes the #37 nit).

## 4. Runtime: Node (Q2, Q3)

- **v1 requires a system Node** that is an LTS major from the supported set. No Node binary is bundled in R4. The buyers are agent builders, who already run Node. Bundling, through Node SEA or a vendored binary, becomes R4b only if beta feedback asks for it.
- **The supported set is Node 22 (≥22.19) and Node 24 (Q3).**
  - Node 22 enters maintenance in April 2027, and a late-2026 buyer is likely on Node 24.
  - To certify Node 24, both engines' conformance suites (R0 golden, authority-v2, writes-v5, mcp-v1, cli-v1, view-v1, R3 X/Z) run on Node 22 and Node 24, on all 3 OSes, with zero tolerance. A divergence on 24 is a STOP under the scope fence.
  - The identity engine's `engines` field widens to `>=22.19 <23 || >=24 <25` only after that matrix is green.
- **`node:sqlite`**: both majors run the same pinned behavior checks. Journal mode, `BEGIN IMMEDIATE`, busy translation and the header-mask rules from R3 are re-proven on 24. The SQLite version Node bundles is recorded in `compat.json`.

## 5. Installer (`trajecta install`)

**How it is delivered:**
- a release asset `trajecta-<ver>.tgz` (an `npm pack` of the product with its engines, lockfile-pinned);
- plus `install.sh` and `install.ps1`, which only verify the tarball's SHA-256 against the release manifest and run `node <tarball>/bin install`.

npm publish is optional and not required (Q4).

**Steps.** Each step is idempotent, and each failure leaves the system as it was:
1. **Node check.** Look for a `node` on PATH, then known locations (Homebrew, nvm/fnm/volta shims, `%ProgramFiles%\nodejs`). Probe each candidate's major and minor version against the supported set. If none passes: `trajecta: need Node 22.19+ or 24 LTS` on stderr, exit 1, and no change to anything (same shape as K5).
2. **Install root.**
   - The default is `~/.trajecta/<ver>/` on macOS and Linux, and `%LOCALAPPDATA%\Trajecta\<ver>\` on Windows. It is versioned, so an upgrade never overwrites a running version.
   - A `current` pointer is written last, atomically: a symlink on POSIX, a `current.json` file on Windows.
3. **Launcher.** `trajecta` (or `trajecta.cmd`) goes into a user bin directory already on PATH. If none is on PATH, the installer prints the one line to add. It never edits shell rc files.
4. **Profile and stores.**
   - It resolves the identity profile and work root exactly as the engines do. There is no new resolution law.
   - It bootstraps **only a missing store**.
   - An existing store is opened read-only by `doctor` (P10). Any migration goes through `migrate-to`, with its backup law (R2d A10, R3 §3.6), and only after explicit confirmation on a TTY.
5. **Claude plugin, built locally** (§6) and placed in a folder the installer prints. It **never edits** Claude's or any other client's config files. The user installs the `.plugin` file themselves, or pastes the printed MCP config.
6. **`trajecta doctor`** runs last. The install reports success only if doctor passes.

**`trajecta uninstall`** removes only the install root, the launcher and the built plugin file. It **never** touches stores, profiles or client configs. It prints where the data remains.

**Upgrade from a Python install:**
- The installer **detects** an old venv install (`install/` layout, a Python plugin, an MCP config whose command is a Python interpreter).
- It **reports** what it found and the exact replacement config.
- It changes none of it. Replacing a client config is the owner's action, done with the printed instructions.

## 6. TS plugin builder with a Node payload (from R2e K)

`trajecta plugin` builds the `.plugin` file. It satisfies K1–K6, with these changes for the Node payload:
- **Payload:** the installed product, referenced by absolute path. It is **not copied**: the plugin points at `<install root>/current`, so an upgrade does not require rebuilding the plugin. K3 reproducibility is defined given the same install root path.
- **`.mcp.json` command:** the **absolute path of the Node binary found at install time** (closes the #35 carry). The plugin does not boot through `python` or a bare `node`. The launcher script still re-probes the version (P23 shape), and if the Node binary has since vanished it refuses with `<server>: need Node …`.
- **K4:** environment defaults use the P24 rules on Windows and the `_sh_value` rules on POSIX. Neither changes.
- **K2:** atomic write in the destination folder, as P22.

## 7. Retiring the Python writer, and deciding G13, G14, G17 and import-aml

- **Python writer retired.**
  - `install/install.sh` and `install.ps1` are replaced by the product installer, and the old scripts print a pointer to it.
  - The Python `plugin`, `setup` and `mcp_server` entry points stay importable, because the oracle and CI need them, but they are **not shipped**.
  - The README's install section moves to the product.
  - **The oracle stays in CI as a reader for one release.** All corpora keep running against Python until the release after 0.5.0.
- **G13 → P25, refuse silent profile overwrite (both runtimes).**
  - If a `.json` or URL profile would overwrite an installed profile of the same name, and the canonical JSON bytes differ, the command refuses with a typed error (`ProfileConflict: profile '<name>' differs from the installed copy; pass --replace-profile to overwrite`) and exits 1, with no write.
  - `--replace-profile` keeps today's overwrite, after writing a backup `profile.json.<UTC timestamp>.bak`.
  - Identical bytes are a no-op.
  - The corpus case that pins today's overwrite is replaced by three cases: conflict, replace and identical.
- **G14 → P26, a dry run leaves nothing (both runtimes).**
  - `migrate-to --dry-run` records every parent directory it created.
  - On exit, success or failure, it removes exactly those, deepest first, and only if they are still empty.
  - A directory that existed before the dry run is never touched.
  - Corpus: a dry run on a missing parent chain leaves the original file tree.
- **G17: keep Law F-1 as the permanent product HTTP law (Q5).** On malformed or over-limit input, TS may be stricter than the oracle, never more permissive. G17 closes as accepted. The wording nit, "oversized header line" meaning over the limit, is fixed in the same PR.
- **`import-aml`: archive (Q6).** It moves to `tools/archive/` with a README, it is not shipped, and it is not ported. It was a one-shot import for Ty's own AML vault, not product write law.

## 8. Gates (all on exact heads; zero tolerance)

| Gate | What it proves |
|---|---|
| **M1 engine matrix** | Every identity corpus and R3 X/Z, plus the work engine suite, on {macOS, Windows, Linux} × {Node 22, Node 24} |
| **M2 product contract** | Pass-through CLI output equals the engine bytes. The "no direct store writes" scan is clean. `compat.json` is regenerated and its diff is empty |
| **M3 clean-machine install** | On fresh GitHub runners for each OS, using a runner image without Node and then with Node 22 and with Node 24: a refusal without Node, then install → doctor → `identity retrieve` → `work` round trip → uninstall. Store bytes are unchanged by uninstall |
| **M4 upgrade from Python** | A fixture with the old venv install and an R3-era store: the installer detects it, prints the replacement, changes nothing, and the TS runtime reads and writes the store under the R3 laws |
| **M5 plugin** | K1–K6 exact. The `.mcp.json` command is the absolute Node path. The launcher refuses when that Node is removed |
| **M6 P25/P26** | Both runtimes, new corpus cases, three seeds |
| **M7 oracle reader** | The Python oracle still passes every corpus against TS-written stores (one-release rule) |
| **M8 owner rehearsal** | Ty's real-copy M receipt (R3 §4) on the release candidate. **This gates the release tag, not the merges.** |

## 9. PR plan

1. **Spec**: this file.
2. **Identity repo**: P25, P26, the corpus updates, the `tests.yml` version fix, the G17 wording fix, the `import-aml` archive, and the Node 24 matrix for the identity corpora (M1, M6, M7).
3. **Work repo**: the Node 24 matrix, and a tag for the pinned commit (M1).
4. **New `trajecta` repo**: product package, CLI, version, `compat.json`, installer, plugin builder, uninstall, and the M2–M5 CI.
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
