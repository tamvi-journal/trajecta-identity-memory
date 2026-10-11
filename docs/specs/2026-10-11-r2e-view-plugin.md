# R2e: TypeScript view, plugin contract, and the product surface

Status: draft for Lam's review. Author: Aux (leader). Builds on R0, R2c, R2d and R3 (main @ 1fd960d).

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

## 2. Oracle patch (both runtimes)

### 2.1 P21: the view answers only its own origin

Every request is checked before routing, in this order:

1. **Host.** The `Host` header must equal one of the names below, compared case-insensitively. Otherwise the response is 403, `text/plain; charset=utf-8`, with the body `forbidden host`.
   - `127.0.0.1:<port>`
   - `localhost:<port>`
   - `[::1]:<port>`, accepted only when the server is bound to `::1`.
2. **Origin.** If an `Origin` header is present, it must equal `http://` followed by an accepted Host value. Otherwise the response is 403 with the body `forbidden origin`. A missing `Origin` is allowed: direct navigation and same-origin GET requests often send none.
3. **Framing.** Every response, including the 403 and 404 responses, also carries `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`.

The checks are identical in both runtimes, including the 403 bodies. The page fetches relative URLs (`api/snapshot`), so P21 changes nothing for a legitimate viewer.

Tests (both runtimes), each against a running server:
- `Host: evil.example:<port>` → 403 `forbidden host`.
- `Host: 127.0.0.1:<other port>` → 403.
- `Origin: http://evil.example` with a valid Host → 403 `forbidden origin`.
- No Origin with a valid Host → 200.
- After the rejected requests, the store file bytes and `mtime` are unchanged.

### 2.2 A: one page, served by both runtimes

- `PAGE` moves, byte for byte, to `assets/view/index.html`. `view.py` reads it once at import (Python package data). `node/src/view.ts` reads the same file once at start.
- Neither runtime embeds a copy of the page. A test proves that the bytes served at `/` equal the file's bytes in both runtimes.
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
  - one cue that recalls something, and one that recalls nothing.
- **Read purity:** after every request, the store file's bytes are identical to before. A read must not even refresh the header bytes that §3.5b of R3 allows writers to change.
- **Cross-runtime:** the Python view serves a store written by TS, and the TS view serves a store written by Python, through the R3 X harness. The responses equal those on a single-runtime store.
- **OS matrix:** the same three OSes as R3.

## 4. Frozen gaps

| Gap | What it is | Decided in |
|---|---|---|
| G15 | `snapshot()` bootstraps an `uninitialized` store (V6). The branch is only reachable if the store disappears while serving. Both runtimes keep it. A corpus case pins it | R5: a read surface should show an empty state, not write |
| G16 | A non-GET method gets a 4xx/5xx response whose body and status are not a contract. Both runtimes must answer with a status of 400 or above and write nothing. A test proves no store change | R5 |

## 5. K: the plugin contract now, the builder at R4 (Q2)

Today `plugin` packs the **Python** sources into the `.plugin` file, together with a launcher that looks for Python 3.10+. After the R4 cutover, the payload must be the Node runtime. Porting a builder that packs Python sources into TS would produce work that R4 throws away. R2e therefore freezes only what any builder must keep, as tests that the R4 builder must pass:

- **K1 layout:** `.claude-plugin/plugin.json`, `.mcp.json`, launchers in `scripts/`, the skill in `skills/identity-continuity/`. There is never a top-level `bin/` (uploads reject it).
- **K2 atomic:** the zip is written to a temporary file and moved into place. A failed build leaves no partial `.plugin` file, and leaves an existing good one untouched.
- **K3 reproducible:** with the same inputs, two builds produce the same entry list, the same entry bytes, a fixed timestamp, and modes 0755 for launchers and 0644 otherwise. The archive bytes themselves are not a contract, because they depend on the zlib version.
- **K4 env defaults:** an environment value the user already set wins over the plugin's default. `~/` and `$HOME/` in a default stay expandable.
- **K5 launcher failure:** when no suitable runtime is found, the launcher prints `<server>: need …` to stderr and exits 1. It never starts a half-working server.
- **K6 version honesty:** `plugin.json` carries the single product version. Today it reads pyproject's 0.4.0. **R4 decides** the single source, and K6 becomes an exact test then.

Python's existing `test_plugin.py` is extended to cover K1–K5, so the contract is checked against the oracle from today.

## 6. R5 (proposed, not settled here): the view as the product screen

This section only records direction, so that R2e's API freeze (§3.1) does not block it. It opens as its own spec after R4.

- **What a buyer should see first:** who this agent is (core and its revisions), what changed since the last session, the open loops, and what the next session will receive (the packet that `retrieve` produces for "who are you" and for the current work).
- **Identity and work on one screen:** batons, checkpoints and decisions from trajecta-work-memory, next to the identity timeline. This needs a view-api/v2 and is decided in R5.
- **Owner:** Ty designs the page against the frozen API. Aux and Codex make sure both runtimes serve it.
- G15 and G16 are resolved there.

## 7. Scope fence (anti-drift; proposed to Ty, applied to R2e if she agrees)

A new STOP reopens this spec only for data loss or corruption, a leak of memory contents, or an untyped error that a real client hits in normal use. Anything else becomes a frozen gap (G17+) with an owner phase. Purely visual or wording issues on the page are R5.

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
