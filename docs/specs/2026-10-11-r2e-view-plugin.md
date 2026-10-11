# R2e: TypeScript view, plugin contract, and the product surface

Status: architecture approved by Lam @ 566b8a3 (Q1–Q5 yes, with amendments F1–F8 applied; §10). Author: Aux (leader). Builds on R0, R2c, R2d and R3 (main @ 1fd960d).

## 0. Goal, scope, and why this phase matters for the product

R2e closes the last two CLI surfaces that R2d split off: `view` and `plugin`.

Most of R0–R3 is invisible to a buyer: they get byte-exact laws, crash boundaries and busy handling, and never see them. `view` is different, because it is the **only screen the product has**. A person who buys Trajecta judges it by what that page shows: who the agent is, what it remembers, what it decided, and what the next session will know. `plugin` is the **install path**: a buyer installs one file and memory starts with Claude.

So R2e has two goals, and the order between them is fixed:

1. **Port the view with parity, and make it safe to ship.** This is the oracle discipline, unchanged.
2. **Decouple the page from both runtimes**, so the page can be redesigned later as one design task instead of a two-runtime port.

R2e does **not** redesign the page. The redesign is proposed as R5 (§6) and is fenced out of this phase.

**In scope**
- **V:** `view` in TS: an HTTP server bound to localhost, the same routes, the same JSON, and the same page bytes.
- **A:** the page moves out of `view.py` into one shared asset that both runtimes serve (a refactor; the bytes are unchanged).
- **P21:** the view refuses requests that do not come from its own origin (DNS-rebinding guard; oracle patch, both runtimes).
- **K:** the plugin **contract** is frozen as tests. The TS plugin **builder** is deferred to R4 (Q2).

**Out of scope**
- **R4:** the installer, cutover, the plugin builder with a Node payload, the single version source (0.4.0 vs 0.1.0), G13, G14, and `import-aml`.
- **R5 (proposed, §6):** the redesigned view as a product surface, and showing work memory next to identity.
- G1–G14 stay frozen.

## 1. Oracle audit (Python `view` at main 1fd960d)

| # | Python behavior today | Effect |
|---|---|---|
| V1 | `serve()` refuses any host other than `127.0.0.1`, `localhost` or `::1` (`ValueError("the memory view only binds to localhost")`). The default port is 8767, and `--port 0` picks a free port | — |
| V2 | The **Host header is never checked**. With the view running, any website the owner visits can rebind its own DNS name to 127.0.0.1 and read `/api/snapshot`, which is the whole identity core, every node, and the timeline | **a privacy leak of the full memory; fixed by P21** |
| V3 | `GET /` and `GET /index.html` return `PAGE` as `text/html; charset=utf-8`. `GET /api/snapshot` returns `snapshot(memory)`. `GET /api/retrieve?cue=…` returns `{"packet","items"}`, or `{"packet":""}` for an empty cue. Any other path returns 404 with the body `not found` and the type `text/plain` (no charset) | — |
| V4 | The cue is `(parse_qs(query).get("cue") or [""])[0].strip()[:2000]`. That is Python `str.strip()` (Unicode whitespace) and a cut at 2000 **code points** | TS must use `pyStrip` and cut by code point, not UTF-16 unit |
| V5 | Recall from the page runs `memory.retrieve(cue, track=False)`: it does not change activation | the page is a pure read |
| V6 | `snapshot()` calls `bootstrap()` when the store is `uninitialized`. The CLI already bootstraps before `serve`, so this branch is only reachable if the store disappears while the view is running | a write on a read surface; frozen as G15 (§4) |
| V7 | JSON is `json.dumps(value, ensure_ascii=False, default=str)`: Python's default separators `", "` and `": "`, no indent, no trailing newline. `accessibility` is `round(float, 3)` and printed with Python `repr` | TS reuses the R2c JSON writer and `pyFloatRepr` |
| V8 | Every response carries `Content-Type`, `Content-Length`, `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`. `Server` and `Date` are also present | the four named headers and the body bytes are the contract; `Server` and `Date` are not |
| V9 | An exception in a handler returns 500 with `str(error)` as `text/plain`. Methods other than GET get `BaseHTTPRequestHandler`'s 501 HTML page | see G16 (§4) |
| V10 | `serve()` prints `Identity memory view for <agent>: <url>  (Ctrl+C to stop)` to stdout, then opens the browser unless `--no-browser`. Ctrl+C closes the server and exits 0 | — |
| V11 | The server is `ThreadingHTTPServer`, and the store opens a connection per operation | concurrent page requests are safe as reads |
| V12 | `::1` passes the V1 check, but `ThreadingHTTPServer` is IPv4-only, so the bind fails with `socket.gaierror` (verified at 1fd960d). The printed URL would also lack brackets | `::1` is accepted on paper and broken in practice; fixed by P21 step 0 |

## 2. Oracle patch (both runtimes)

### 2.1 P21: the view answers only its own origin

**Step 0, bind (fixes V12; F4).** Binding to `::1` uses an IPv6 socket in both runtimes. The printed and opened URL is `http://[::1]:<port>/`. `<port>` everywhere below is the **actually bound** port, so `--port 0` works.

Every request, of **every method**, is then checked before routing, in this order. Every check fails closed.

1. **Host.** There must be exactly one `Host` header, and its value must equal one of the names below, compared ASCII-case-insensitively. A missing Host, a duplicate Host, a malformed authority, or a wrong port gets 403, `text/plain; charset=utf-8`, with the body `forbidden host`.
   - `127.0.0.1:<port>` and `localhost:<port>`, when bound to `127.0.0.1` or `localhost`;
   - `[::1]:<port>` and `localhost:<port>`, when bound to `::1`.
2. **Origin (F1, F2).** A missing `Origin` is allowed: direct navigation and same-origin GET requests often send none, and step 1 already blocks rebinding. If Origin is present, there must be exactly one, and it must equal `http://` followed by **this request's own validated Host value**, compared ASCII-case-insensitively. Anything else gets 403 with the body `forbidden origin`, including a duplicate Origin, `Origin: null`, the `https` scheme, another accepted host name, or another port.
3. **Response policy (F3).** Every response, including 403, 404, 500 and any non-GET response (G16), goes through one common header path. That path adds `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer` to the V8 headers. No route or method may bypass it.

The checks are identical in both runtimes, including the 403 bodies. The page fetches relative URLs (`api/snapshot`), so P21 changes nothing for a legitimate viewer.

**What P21 is and is not (Lam).** P21 closes the browser-based DNS-rebinding exposure. It is **not** authentication against other processes on the same machine. Those can still read the store file directly, and that is outside this spec.

Tests (both runtimes), each against a server on an ephemeral port (`--port 0`), using the bound port:
- `Host: evil.example:<port>` → 403 `forbidden host`.
- `Host: 127.0.0.1:<other port>` → 403.
- No Host, a duplicate Host, and a malformed Host (`127.0.0.1:`, `127.0.0.1:abc`, `[::1`) → 403.
- `Origin: http://evil.example`, `Origin: null`, `Origin: https://127.0.0.1:<port>`, `Origin: http://127.0.0.1:<other port>`, a duplicate Origin, and an Origin for `localhost` when the request's Host is `127.0.0.1` → 403 `forbidden origin`.
- No Origin with a valid Host → 200. A matching Origin → 200.
- `POST` and `DELETE` to `/api/snapshot` with a bad Host → 403. With a good Host, they still carry the step 3 headers and get status ≥ 400.
- An IPv6 run bound to `::1` → 200 at `http://[::1]:<port>/`. The printed URL has brackets. This test is skipped only on a runner without IPv6 loopback, and the skip is reported.
- After every rejected request, the store file bytes and `mtime` are unchanged.

### 2.2 A: one page, served by both runtimes

- `PAGE` moves, byte for byte, to `trajecta_identity/assets/view.html`. That is the one canonical file. It is added to `[tool.setuptools.package-data]`, and `view.py` reads it once at import through `importlib.resources`.
- Node gets `node/assets/view.html`, a byte-identical copy, added to the `files` list in `node/package.json`. `node/src/view.ts` resolves it relative to its own module URL, never the working directory. This follows the existing `schema.sql` precedent: a conformance test fails if the two files' bytes or SHA-256 differ.
- Neither runtime embeds the page in code. A test proves that the bytes served at `/` equal the canonical file's bytes in both runtimes.
- **Installed-distribution test (F5).** Development tests are not enough.
  - Python: CI builds a wheel, installs it into a fresh venv, and runs `view` from a working directory outside the checkout.
  - Node: CI runs `npm pack`, unpacks the tarball into a temporary directory, and runs `view` from outside the checkout.
  - In both cases, `GET /` must return the canonical bytes.
- **Why this matters for the product:** after A, redesigning the screen means editing one HTML file against a frozen JSON API (§3.1). That is a design task Ty can own, and it needs no port and no conformance cycle in two runtimes.

## 3. V: the TypeScript view

### 3.1 The API is the contract

`/api/snapshot` and `/api/retrieve` are frozen as **view-api/v1**: the key order, the types and the null rules exactly as Python emits them in V3–V7. Any later page, including the R5 redesign, may only use these two endpoints. A new field is a new API version, decided in its own spec.

### 3.2 Server

- `node:http`, no dependencies. The bind rule is V1, with the same `ValueError` text. The printed line is V10.
- Opening the browser uses `open` on macOS, `xdg-open` on Linux, and `cmd /c start "" <url>` on Windows. A failure to open the browser is ignored, as Python's `webbrowser.open` ignores it.
- CLI wiring: `view [--port N] [--no-browser]` in `node/src/cli.ts`, with the same bootstrap rule as the Python CLI (bootstrap only an `uninitialized` store; a `legacy-v4` store is served as is).
- Unexpected errors in a handler return 500 `text/plain`. The body is **not** a contract (it is shown only to the local viewer). This is the same treatment as R2d A13.

### 3.3 Conformance corpus view-v1

Python generates the corpus. TS must match it byte for byte.
- **Fixtures:** the R0 golden stores and the `test_view.py` fixture (a core revision, an open proposal, an open loop and two phases), plus one `legacy-v4` store.
- **Per fixture, recorded:** the bytes of `GET /`, `/index.html` and `/api/snapshot`; `/api/retrieve` for a cue list; one 404; the four contract headers (V8) plus the two P21 headers; and the P21 rejections.
- **The cue list covers:**
  - the empty cue, and a cue of only whitespace (including `\x1c` and U+3000);
  - a 2001-code-point cue made of astral characters;
  - a percent-encoded cue, and a cue with `+`;
  - a cue that appears twice (`?cue=a&cue=b` takes the first);
  - one cue that recalls something, and one that recalls nothing;
  - **(F7)** malformed percent encoding (`%`, `%G1`, `%E2%82`) and percent-encoded invalid UTF-8 (`%FF`, `%C0%AF`, `%ED%A0%80`). Python's `parse_qs` decodes with `errors="replace"`. TS must produce the same decoded cue, with the same U+FFFD replacements, and must not use a URL parser that throws or decodes differently.
- **Read purity (F6):** on an initialized store (`ready` or `legacy-v4`), every request leaves the store file's bytes identical to before. A read must not even refresh the header bytes that R3 §3.5b allows writers to change. The **only** exception is G15, which is a documented legacy path with its own separate test (§4). Read purity never covers it.
- **Cross-runtime:** the Python view serves a store written by TS, and the TS view serves a store written by Python, through the R3 X harness. The responses equal those on a single-runtime store.
- **OS matrix:** the same three OSes as R3.

### 3.4 HTTP framing outside view-api/v1 (Aux review of PR #38 @ 08e9ccf)

Aux ran a differential fuzz: the Python worker and the TS worker on copies of the view-fixture store, sent the same raw socket bytes, whole and in 3-byte chunks.
- **Valid requests:** a 1,500-case random percent-encoded cue fuzz and every valid edge case match exactly. The edge cases covered pipelining, `Expect`, LF framing, unknown methods, absolute-form, `//`, `;params`, dot segments, a percent-encoded path, HEAD, `OPTIONS *`, chunked transfer encoding, and Origin and Host case variants.
- **Requests that are not valid HTTP/1.1** produce six differences. In each, Python is the more permissive side, and P21 still holds in both runtimes:

| Input | Python | TS |
|---|---|---|
| a header block of more than 100 physical lines (see below) | 431 | **200 (serves)** |
| raw non-ASCII bytes in the request-target (RFC 3986 forbids them; browsers percent-encode) | 200, with the cue decoded as Latin-1 mojibake | 400 |
| whitespace between the header name and the colon (`Host : …`) | 403 | 400 |
| an obs-fold continuation of Host | 403 | 400 |
| an HTTP/0.9 request line, or non-HTTP bytes | a status-less 0.9 reply | 400 or 403 |
| an oversized header line | 431 | 400 |

**Law F-1. The TS view may be stricter than the oracle on invalid HTTP framing, never more permissive.**
- For any request that Python refuses with a status of 400 or above, TS must also refuse with a status of 400 or above, through the common header path, writing nothing.
- For any request that is valid HTTP/1.1 (RFC 9112, with a request-target allowed by RFC 3986), TS must match the oracle exactly. That is view-v1 plus the fuzz above.
- The header-count case breaks F-1. TS must reproduce the oracle's limit exactly (Codex STOP @ 08e9ccf; Aux checked it against `http.client._read_headers`). The law:
  - Python appends **every physical header line** to its list before testing `len > 100`. That includes continuation (obs-fold) lines **and the terminating blank line**, and the test runs before the end of the headers is checked.
  - So a request is refused with **431**, with the body exactly `Too many headers`, through the common header path and with no write, when its header block has more than 100 physical lines counting that blank line. In other words, 99 ordinary fields are served and 100 are refused.
  - This check is part of request parsing, so it runs **before** the P21 guard, as in Python. With 100 fields and an evil Host, the answer is 431, not 403.
- **Regression tests** (TS, and the same requests against the Python oracle):
  - 99 fields: 200.
  - 100 fields: 431.
  - 101 fields: 431.
  - 98 fields plus one folded continuation line: 200.
  - 99 fields plus one folded continuation line: 431.
  - 100 fields with an evil Host: 431.
  - Every count includes Host. No implicit headers are added.
  - Store bytes, mtime and inventory stay unchanged.
- The other five rows are allowed under F-1 and are frozen as **G17**.

## 4. Frozen gaps

| Gap | What it is | Decided in |
|---|---|---|
| G15 | `snapshot()` bootstraps an `uninitialized` store (V6). The branch is only reachable if the store disappears while serving. Both runtimes keep it. It is an **explicit exception to read purity** (§3.3), pinned by its own corpus case: delete the store while serving, request `/api/snapshot`, and compare the resulting store with a Python bootstrap | R5: a read surface should show an empty state, not write |
| G16 | A non-GET method gets a response whose body and exact status are not a contract. Both runtimes must answer with a status of 400 or above, pass the P21 guard and response policy first (§2.1), and write nothing. A test proves no store change | R5 |
| G17 | On requests that are not valid HTTP/1.1 (raw non-ASCII bytes in the target, whitespace before a colon, obs-fold, HTTP/0.9 or non-HTTP bytes, oversized header lines), TS refuses with a status of 400 or above where the oracle answers 0.9-style, with 403/431, or with 200 on mojibake. Law F-1 (§3.4) forbids the opposite direction | R4: one HTTP framing law for the product view, or a decision to keep F-1 |

## 5. K: the plugin contract now, the builder at R4 (Q2)

Today `plugin` packs the **Python** sources into the `.plugin` file, together with a launcher that looks for Python 3.10+. After the R4 cutover, the payload must be the Node runtime. Porting a builder that packs Python sources into TS would produce work that R4 throws away. R2e therefore freezes only what any builder must keep, as tests that the R4 builder must pass:

- **K1 layout:** `.claude-plugin/plugin.json`, `.mcp.json`, launchers in `scripts/`, the skill in `skills/identity-continuity/`. There is never a top-level `bin/` (uploads reject it).
- **K2 atomic:** the zip is written to a temporary file and moved into place. A failed build leaves no partial `.plugin` file, and leaves an existing good one untouched.
- **K3 reproducible:** with the same inputs, two builds produce the same entry list, the same entry bytes, a fixed timestamp, and modes 0755 for launchers and 0644 otherwise. The archive bytes themselves are not a contract, because they depend on the zlib version.
- **K4 env defaults:** an environment value the user already set wins over the plugin's default. `~/` and `$HOME/` in a default stay expandable.
- **K5 launcher failure:** when no suitable runtime is found, the launcher prints `<server>: need …` to stderr and exits 1. It never starts a half-working server.
- **K6 version honesty:** `plugin.json` carries the single product version. Today it reads pyproject's 0.4.0. **R4 decides** the single source.

K1–K5 are **executable now**: Python's `test_plugin.py` is extended to cover them, so the contract is checked against the oracle from today. K6 is **declared now and accepted at R4 (F8)**. R2e ships no test for it, because the value it would pin is not settled yet.

### 5.1 P22 and P23: the oracle violates K2 and K5 (Codex STOP @ 13ba744)

Codex wrote the K-tests before any production edit. Three of them fail against today's Python, and Aux confirmed the cause of each in `trajecta_identity/plugin.py`:

- **K2 broken:**
  - `build_plugin` writes the zip to a temporary file in the **system** temp directory. If `os.replace` fails, it falls back to `shutil.copyfile(tmp, out)`.
  - If the copy fails partway, a partial `.plugin` is left behind, and an existing good file is overwritten. Cleanup removes only `tmp`.
- **K5 broken:**
  - The Windows `launch.py` keeps `sys.executable` even when it is older than 3.10 and no other candidate is found.
  - The candidates it does find are never version-checked.
  - So it starts the server on an unsupported Python instead of refusing.

Under §7, an accepted invariant cannot become a deferred gap. Both are fixed in PR 2 as narrow oracle patches. They change only what the plugin builder writes, never memory semantics.

**P22 — atomic plugin write.**
1. The temporary file is created **in the destination folder**, as `tempfile.mkstemp(dir=<out's folder>, prefix=".build-", suffix=".plugin")`. It is therefore on the same volume as the destination.
2. After the zip is fully written and closed, the only commit step is `os.replace(tmp, out)`. There is **no copy fallback**.
3. On any failure, before or during the replace:
   - `tmp` is removed if it exists;
   - an existing `out` keeps its exact bytes;
   - no new `out` appears;
   - the original exception propagates unchanged.
4. If the destination folder does not allow creating the temporary file, the build fails at step 1, with no partial output.

**P23 — the Windows launcher validates its runtime.**
- The candidates, in order, are:
  1. `sys.executable`;
  2. `py -3`, if `py` is found;
  3. `python3`;
  4. `python`.
- Each candidate is probed with `-c "import sys; sys.exit(sys.version_info < (3, 10))"`. The first one that exits 0 is used.
- If no candidate passes, the launcher writes `<server>: need Python 3.10+` and a newline to stderr, exits 1, and starts no server. This is the same text as the POSIX launcher (K5).
- The server name is rendered into `launch.py` at build time, as it already is for `identity.sh`.

**Tests (PR 2):**
- K2 is tested in two cases, each with a forced `os.replace` failure (`EXDEV`) and a failure in the middle of the write: no existing output, and an existing good output whose bytes must be unchanged.
- K5 is tested with a launcher seam: an old interpreter and no valid candidate gives the refusal text and exit 1, and no server process starts. A valid second candidate is the one used.
- These seams exercise the launcher's logic. They are not a claim of a real Windows run on Python 3.9.
- K3 still holds: two builds with the same inputs produce the same entries and bytes.

Both patches belong to the Python plugin payload, which R4 replaces with a Node payload. The R4 builder must still pass K2 and K5 (§5).

### 5.2 P24: the Windows launcher breaks K4 (Codex STOP @ e319112)

Codex's K4 test fails against today's Windows `launch.py`. It applies defaults with `env.setdefault(key, os.path.expanduser(value))`:
- **`$HOME/…` is not expanded.** `expanduser` only handles `~`, so a default of `$HOME/data` reaches the server as the literal text `$HOME/data`.
- **An empty value counts as set.** `setdefault` keeps an existing empty string. The POSIX launcher (`[ -n "$KEY" ] || KEY=…`) treats an empty value as unset and applies the default. The two launchers disagree.

Aux re-audited K1–K5 against `plugin.py` at e319112. Apart from P22/P23 (§5.1), these two points are the only remaining K4/K5 divergences. The POSIX launcher already meets K4.

**P24 — Windows launcher env defaults (narrow oracle patch, PR 2).** For each default `KEY=value` rendered into `launch.py`:
1. If `os.environ.get(KEY)` is a **non-empty** string, it is used unchanged, byte for byte. There is no expansion and no normalization. An empty string counts as unset, the same as `[ -n ]` on POSIX.
2. Otherwise, if `value` starts with exactly `~/` or `$HOME/`, the launcher computes `home = os.path.expanduser("~")`. That is Python's own Windows rule: `USERPROFILE`, else `HOMEDRIVE`+`HOMEPATH`. **`HOME` is not consulted on Windows.** The default becomes `home` followed by the rest after the prefix, with the forward slashes kept as written.
3. If the home folder cannot be resolved (`expanduser("~")` returns `"~"`), the launcher writes `<server>: cannot resolve home folder for <KEY>` and a newline to stderr, exits 1, and starts no server.
4. Any other `value` is used verbatim. There is no `expandvars` and no `~user` handling, which matches the POSIX `_sh_value` quoting.

The POSIX launcher does not change.

**Tests (PR 2), using the launcher seam with isolated `USERPROFILE`, `HOMEDRIVE`, `HOMEPATH` and `HOME`:**
- `~/x` and `$HOME/x` both resolve to `<USERPROFILE>/x`.
- A preset non-empty value wins byte for byte, even when it contains `~` or `$HOME`.
- A preset empty value gets the default.
- With `USERPROFILE` unset, `HOMEDRIVE`+`HOMEPATH` is used.
- With no home source at all, the refusal and exit 1 apply, and no server starts.
- A plain value such as `D:/data` passes verbatim.
- K3 still holds.
- As with P23, the seam is not a claim of a real Windows run.

**Codex process note.** Before the next report, run all of K1–K5 and P21–P24, and report every remaining violation in one STOP, not one at a time.

## 6. R5 (proposed, not settled here): the view as the product screen

This section only records direction, so that R2e's API freeze (§3.1) does not block it. It opens as its own spec after R4.

- **What a buyer should see first:** who this agent is (core and its revisions), what changed since the last session, the open loops, and what the next session will receive (the packet that `retrieve` produces for "who are you" and for the current work).
- **Identity and work on one screen:** batons, checkpoints and decisions from trajecta-work-memory, next to the identity timeline. This needs a view-api/v2 and is decided in R5.
- **Owner:** Ty designs the page against the frozen API. Aux and Codex make sure both runtimes serve it.
- G15 and G16 are resolved there.
- **Product layer (Lam's settlement, recorded for R4).** Identity memory and work memory stay separate repos, each independently verified. At R4, Trajecta becomes a thin product composition layer over them. It owns the installer, dependency pinning, plugin distribution, the product version, licensing, release evidence and the compatibility matrix. There is no monorepo merge. The layer **coordinates the engines and is never a second authority over their memory histories**. It may compose identity and work evidence, but it must not manufacture verified continuity just because both engines returned data.

## 7. Scope fence (anti-drift; Lam's wording, replacing Aux's draft)

New evidence reopens R2e only when it shows one of these:
- data loss or corruption;
- unauthorized information exposure;
- a security-boundary failure;
- a violation of an accepted invariant or a frozen API contract;
- a cross-runtime conformance failure;
- an operational defect that stops the supported product path from working.

Non-contractual UX improvements, cosmetic issues, wording changes and feature requests become versioned deferred gaps (G17+), each with an owner phase. Purely visual issues on the page belong to R5.

An accepted invariant cannot be reclassified as a deferred gap just to keep the phase on schedule.

## 8. CI and deliverables

- PR 1 (spec, this file): Lam's review.
- PR 2 (Codex): P21 and A in Python, the view-v1 generator and corpus, and `test_plugin.py` extended to K1–K5. CI stays green on Python alone.
- PR 3 (Codex): `node/src/view.ts`, the CLI `view` command, view-v1 conformance in TS, the P21 tests, and cross-runtime view runs added to the R3 X job on the three OSes.
- Merge rule: unchanged. Lam approves the exact head, CI is green on that head, there are no open findings, and Aux's adversarial review is done.

## 9. Questions for Lam

- **Q1:** Should P21 land in Python now (oracle patch), rather than waiting for the TS view? Aux: yes. It is a privacy leak of the full identity memory on today's product.
- **Q2:** Should the TS plugin builder move to R4, with R2e freezing K1–K6 only? Aux: yes. The payload changes at cutover.
- **Q3:** Should the page move to a shared asset (A) in R2e, even though it changes no behavior? Aux: yes. It is what makes R5 a design task instead of a port.
- **Q4:** Should a missing `Origin` be accepted (§2.1 step 2)? Aux: yes, because browsers omit it on navigation and on many same-origin GETs, and Host already blocks rebinding.
- **Q5:** Should G15 and G16 be frozen rather than fixed now? Aux: yes, under the scope fence. Neither loses or leaks data.

## 10. Settlement (Lam, 2026-10-11, review @ 566b8a3)

- **Architecture:** approved. Q1–Q5 yes.
- **Q1 — P21 in Python first:** yes, and treated as a security correction, not parity work.
- **Q2 — plugin builder at R4:** yes. K1–K5 are tested now; K6 is specified now and accepted at R4.
- **Q3 — shared page asset:** yes, and it must work from installed distributions.
- **Q4 — missing Origin allowed:** yes, with strict Host validation.
- **Q5 — freeze G15/G16:** yes, with G15 declared an explicit exception to read purity.
- **Repo:** separate engines, a thin R4 product layer, a unified R5 experience, and no early monorepo merge (§6).

Amendments applied in this revision:
- P22 and P23 (§5.1), added after Codex's STOP on PR 2. Lam approved them at c39dded.
- P24 (§5.2), added after Codex's second STOP. Lam approved it at 0969423.
- §3.4 Law F-1 and G17, from Aux's differential fuzz of PR #38; awaiting Lam.
- F1: Origin must match the request's own Host.
- F2: fail-closed header handling and negative tests.
- F3: the security headers apply to every method and every status.
- F4: `::1` really binds, the URL has brackets, and ephemeral ports are tested.
- F5: installed-distribution tests for both runtimes.
- F6: read purity scoped to initialized stores, with G15 as its exception.
- F7: malformed percent encoding and invalid UTF-8 added to the cues.
- F8: K6 is declared now and accepted at R4.
- §7: replaced by Lam's scope fence.
