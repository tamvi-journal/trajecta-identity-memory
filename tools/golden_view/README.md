# view-v1 Python oracle

Run `python tools/golden_view/generate.py --output <isolated-output>` in the pinned
Python 3.11.15 / SQLite 3.40.1 container used by CI. The complete output, including
MANIFEST, must match under hash seeds 0, 1 and 4294967295.

Each fixture contains `store.sqlite3`, `dump.json`, `fixture.json`, `cases.jsonl`
and response body files. The 16 R0 stores also retain their original bytes in
`input.sqlite3`. The view fixture reproduces `tests/test_view.py` through public
writers and a test-only TTY. The explicit legacy-v4 fixture copies R0 recall.
The relative public database argument is `store.sqlite3`; response bytes need
no path substitution. Header inputs substitute only `{port}` and `{other}` with
the actually bound ephemeral port and a distinct port. All response bodies and
the six named headers are recorded, without Server or Date.

The injected clock resets before each request, at 2026-09-30T00:00:00+00:00,
advancing one second per regular clock call and one microsecond per run-id call.
Fixture construction uses the same clock. Requests execute sequentially over a
real loopback HTTP server. The manifest records the oracle base, patches, source
digests, every corpus file, and every normalization table.

`comparison` is absent for exact status/header/body comparison. Only the spec's
explicit exceptions use a mode: `handler-error` fixes status 500, type and policy
but not its diagnostic body (§3.2); `G16` requires status >=400, type and policy,
but not its exact status/body (§4). For these two modes Content-Length must equal
the actual body length. No successful API response or P21 refusal is relaxed.

Every request against the 18 ordinary fixtures proves identical store bytes,
mtime and directory inventory. The empty file remains `unknown` and refuses,
as the Python oracle does; foreign/future/legacy-v3 API errors remain refusals.
Initialized stores include both v4 and v5. A cue matching the view fixture
recalls First phase; nonmatching cues produce no hits on the raw migrated R0
stores (the other fixtures can still recall pinned core).

`g15-disappear` is separate: remove only the owned copy while the server runs,
request snapshot, retain `result.sqlite3` and its dump, and prove the new file
is byte-identical to a direct Python bootstrap with the same clock and surface.
Replay performs that comparison on the local runtime as well as checking the
frozen snapshot bytes and dump; it does not extend the initialized-store purity
exception to any other request. The original corpus files are never served.

Python replay runs in the existing three-OS matrix. TS replay, npm-pack
acceptance and cross-runtime view plans belong to R2e PR 3.
