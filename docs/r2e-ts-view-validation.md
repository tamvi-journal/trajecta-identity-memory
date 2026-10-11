# R2e PR 3: TypeScript view validation

Base: `d42fcb5`. Contract: `2026-10-11-r2e-view-plugin.md`, sections 3 and 8.

## Implementation

- `node/src/view.ts` serves the shared asset relative to the module URL. The public CLI
  delegates through its existing `cli-runtime.ts` dispatcher.
- P21 runs before routing and before unsupported-method handling. One response function
  emits all six contract headers. IPv6 uses `::1`, brackets, and the actual bound port.
- Cue decoding retains Python's first nonblank query value, plus conversion, malformed
  percent handling, UTF-8 replacement, whitespace stripping and 2000-code-point cutoff.
- Stored JSON is parsed losslessly. Output uses the existing Python-compatible writer,
  typed integer counters, typed rounded accessibility, default separators, and no newline.
- Recall uses `track: false`. G15 remains the isolated disappearance/bootstrap exception.
- CLI bootstrap is limited to `uninitialized`; ready and legacy-v4 stores stay unchanged.
  Browser launch failure is ignored; Ctrl+C closes the server.

## Installed acceptance and transport details

The installed test packs and unpacks the npm artifact, supplies an isolated fixture profile,
starts the **unpacked CLI** with a cwd outside the checkout, and compares GET `/` with the
canonical asset bytes. All writable roots remain inside the clone.

This exposed a pre-existing package dependency: the CLI's pinned decimal, alphanumeric and
whitespace tables were loaded from the repository's corpus directory. The package now
contains byte-identical copies under `node/tables/cli-*.json`. Their pinned hashes and
tamper-refusal tests remain enforced; the original corpus files are unchanged.

Node's HTTP parser has a finite method vocabulary and trims header whitespace. The server
preserves original Host/Origin values and handles unsupported valid method tokens, including
fragmented BREW requests and Python-accepted LF framing, through the same P21 path. Node's automatic Expect responses are
also routed through that path. A socket dispatches only its first request, matching Python's
close-after-response behavior even if another request is pipelined in the same network chunk. No comparator exception was added for these boundaries.

## Evidence

- Python comprehensive P21–P24 / K1–K5 / view preflight: **75 tests + 24 subtests passed**.
- Full Python suite: **604 tests + 24 subtests passed**.
- Node suite: **565 passed / 566 total**, one existing Windows-only test skipped on macOS.
  The 64 new tests include corpus, P21, CLI, browser seams and installed npm acceptance.
- view-v1: **667/667 cases**, across all 19 scenarios: 18 initialized/error fixtures with
  37 cases each, plus the separate G15 case. No IPv6 skip locally.
- R3 X view: **192 HTTP cases**, all four writer/reader pairs, eight public writes, and
  **two G15 runs**. Initialized stores retain their full bytes, mtime and inventory.
- G15 output matches the frozen dump and direct local bootstrap bytes. Cross-runtime new
  databases use the existing R3 schema/dump comparator; physical database bytes can carry
  different SQLite library-version header values. HTTP output is exact in both directions.
- Only the existing handler-error and G16 body/status carve-outs are used by corpus replay.
  All other statuses, six headers, body bytes, JSON types and ordering remain exact.

Python production files, schema.sql, all frozen corpora and their manifests are unchanged.
There is no unresolved spec ambiguity, guessed semantic rule, or deferred mismatch.
CI runs npm acceptance and the new R3 X view proof on Ubuntu, macOS and Windows; the PR
records the exact-head CI result separately from these local results.
