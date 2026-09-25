# Memory law 0.2

Agent Memory Core separates four kinds of state that must not be collapsed.

## 1. Semantic truth

A revision contains the claim: title, summary, content, impact, confidence and
authority status. Once inserted, the row cannot be updated or deleted.

A changed claim creates a child revision. The old claim remains historical
truth: what the system held at that time and from which evidence.

## 2. Evidence identity

Evidence has a versioned canonical identity:

```text
identity_version
source_family
independence_group
source_sha256
```

The canonical hash is deterministic. `source_family` prevents cosmetic source
labels from pretending to be different families. `independence_group` lets a
host state whether two observations are genuinely independent.

Evidence rows and revision-evidence links are immutable.

## 3. Lifecycle truth

`current`, `superseded`, `invalidated`, `deprecated` and `archived` are events,
not mutable columns on a revision. Lifecycle events append in per-record
sequence order.

A semantic revision transaction inserts the new immutable revision and both
required lifecycle transitions. The current view is derived from the event
stream.

## 4. Cognition telemetry

Salience, stability, accessibility, access count and last-access time may
change as an agent uses memory. They live in a separate telemetry table and
are excluded from the semantic and evidence hashes.

Retrieval has two explicit modes:

- `track_access=False`: read-only retrieval;
- `track_access=True`: retrieval plus audited telemetry.

Neither mode can revise meaning.

## Read boundary

Constructing `MemoryStore`, reading current/history/evidence, and read-only
retrieval perform no DDL, migration or hidden write. A missing store reads as
empty. A legacy, foreign or future store fails before interpretation.

Initialization and migration are explicit:

```python
store.initialize()
migrated = legacy_store.migrate_to("memory-v3.sqlite3")
```

SQLite `application_id` identifies Agent Memory Core and `user_version`
identifies the schema. Since 0.3 the current schema is v4; a v3 store fails
closed on read and migrates in place through an explicit `initialize()` (or on
a copy through `migrate_to()`).

## Packet boundary

Retrieval ranking does not own the final context limit. `PacketRenderer` owns
the complete hard budget, including header, provenance framing, memory blocks
and execution instructions.

Version `0.2` uses `deterministic-utf8-quarter/v1`: four UTF-8 bytes are one
deterministic budget unit. This is a stable approximation, not a claim about a
provider tokenizer. A provider-exact tokenizer may replace it later only
behind a versioned estimator contract.

## Consumer boundary

The kernel does not own an agent's identity, relationship, private seeds,
permission policy, truth authority, dream schedule, transport or product
cutover. Consumers reuse the mechanism and keep separate profiles, evidence,
databases and action gates.

## Addendum 0.3

### Relations remember

Relations were the one mutable part of the semantic graph: `add_relation`
upserted weight and status in place and carried no evidence. Schema v4 makes
them an append-only event stream (`memory_relation_events_v4`):

- `assert` and `retract` events, sequenced per relation, protected by
  update/delete triggers;
- optional evidence per event, captured through the same canonical evidence
  identity as revisions;
- re-asserting an unchanged relation is a no-op; a new weight or source appends
  an event; `relation_history()` returns every event;
- the current graph is the view `memory_relation_current_v4`.

Migration carries every v3 relation row into the stream once (an inactive row
becomes `assert` + `retract`, actor `memory-core-migration`). The v3 table is
kept as migration evidence and is no longer written or read.

### Text normalization

Retrieval uses `text-norm/v2`, which transliterates letters NFKD cannot
decompose (`đ`, `ð`, `ł`, `ø`, `æ`, `œ`, `þ`, ...) instead of dropping them.
`"Đuôi"` was `"uoi"`; it is now `"duoi"`. Cue norms are recomputed from the
raw cue at query time, so older rows keep matching.

Evidence identity (`evidence-v2`) keeps the original normalizer frozen as
`normalize_identity_v1`. Changing identity normalization requires a new
evidence identity version, never an in-place change.

### Dormancy

Accessibility remains telemetry. The retriever can now use it for selection
only:

- `min_accessibility`: below it a revision is dormant and skipped by lexical
  overlap and ordinary graph spread;
- `wake_on_direct_cue` (default true): a direct cue still reaches it;
- `wake_relation_types`: graph edges of these types may reach it;
- bootstrap records never go dormant;
- `access_gain` sets how much tracked retrieval adds (default 0.01).

The default (`min_accessibility=None`) keeps 0.2 behavior. Decay schedules and
wake-up boosts are consumer policy, applied through `apply_maintenance()`.
