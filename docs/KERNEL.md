# Kernel: `memory_core`

The provenance kernel underneath Trajecta Identity Memory. It is generic: it knows nothing about any agent. The identity layer (`trajecta_identity`) is built on it; you can also use it directly.

## Architecture

<div align="center">
  <img src="assets/architecture.svg" width="100%" alt="Agent Memory Core semantic memory architecture" />
</div>

The package is deliberately split into a small set of mechanical layers:

| Layer | Responsibility |
|---|---|
| `MemoryStore` | Immutable semantic revisions, append-only lifecycle, canonical evidence identity, and separate cognition telemetry |
| `ValidatedIntake` | Materialize, hold or reject evidence-bearing semantic proposals |
| `CueDrivenRetriever` | Activate current revisions from cues, lexical overlap, bootstrap anchors and graph relations |
| `PacketRenderer` | Compress selected current/history views into a bounded context packet |
| `MemoryProfile` | Supply consumer-owned anchors, aliases, sections and instructions |

> [!IMPORTANT]
> Retrieval is explicit about side effects. `track_access=False` is a
> read-only path; tracked retrieval may update telemetry, never semantic
> content, evidence or lifecycle state.

Host-controlled dreaming or consolidation may call
`MemoryStore.apply_maintenance()` to regulate salience, stability and
accessibility. Each batch is transactional, idempotent and recorded in the
operation ledger; the method rejects semantic fields and verifies that content
hashes remain unchanged.

## Update law

```text
current evidence
      │
      ▼
validated semantic operation
      │
      ├── weak / conflicting evidence ──▶ held, fail closed
      │
      └── accepted evidence ────────────▶ new immutable revision
                                             │
                                             ├── current view
                                             └── inspectable history
```

The kernel follows four rules:

1. Current evidence may revise the current model.
2. Revision creates history; it does not overwrite history.
3. Lifecycle transitions append events; they never rewrite revision rows.
4. Retrieval may change telemetry, not semantic content or evidence.
5. Protected weakening requires authority supplied by the host application.

## Storage contract in `0.3`

- Semantic revision and evidence rows are physically immutable.
- Lifecycle truth is an append-only event stream.
- Salience, stability, accessibility and access counts live in a separate
  mutable telemetry table.
- Evidence identity is deterministic and versioned with normalized
  `source_family` and `independence_group`.
- Ordinary reads perform no DDL and no hidden writes.
- Initialization and migration are explicit and fail closed through SQLite
  `application_id` plus `user_version`.
- `MemoryStore.migrate_to()` copies first and migrates only the copy.
- `PacketRenderer` owns the complete packet budget, including framing and
  execution instructions, using `deterministic-utf8-quarter/v1`.
- Relations are an append-only event stream (schema v4): asserting, reweighting
  and retracting append events with optional evidence; history stays readable.
- Retrieval text uses `text-norm/v2`, which keeps letters such as Vietnamese
  `đ`. Evidence identity keeps its frozen normalizer, so identities do not move.
- Dormancy is opt-in: `min_accessibility` hides low-accessibility revisions from
  lexical and ordinary graph recall; a direct cue or a declared relation type
  wakes them. Bootstrap records never go dormant.

See [the 0.2 memory law](docs/MEMORY-LAW-0.2.md) for the invariant and migration
boundary.

## Install

```bash
git clone https://github.com/tamvi-journal/trajecta-identity-memory.git
cd trajecta-identity-memory
python3 -m pip install -e .
```

## Minimal use

```python
from memory_core import MemoryStore, ValidatedIntake

store = MemoryStore("memory.sqlite3")
store.initialize()
writer = ValidatedIntake(store, surface="local")

result = writer.submit(
    operation_type="create",
    record_id="project-decision",
    record_class="belief",
    domain="project",
    actor="agent",
    reason="A verified decision should become current context.",
    logic="The implementation and test outcome agree.",
    truth_basis="The source artifact and verification report are linked.",
    evidence=[{
        "source_ref": "report:verified",
        "content_summary": "The consuming path passed.",
        "confidence": 0.95,
    }],
    idempotency_key="decision:verified:v1",
    changes={
        "title": "Verified project decision",
        "summary": "Use the tested path as the current implementation.",
    },
)
```

Use `MemoryProfile`, `CueDrivenRetriever`, and `PacketRenderer` to supply the
consumer-specific bootstrap anchors, aliases, sections and instructions.
`MemoryRuntime` provides a consumer-neutral façade over those components
without owning seeds or final authority. `ConsumerBundle` validates that
bootstrap records have seeds and that axis seeds carry an explicit falsifier
plus at least two distinct evidence sources. `ConsumerMemory` then provides an
idempotent bootstrap and a neutral candidate-context envelope that always
declares `memory_decides_truth=false`. See
[the consumer adapter contract](docs/CONSUMER-ADAPTER.md).

Consumers may adopt the open
[Vector-Human Ontology](docs/VECTOR-HUMAN-ONTOLOGY.md) through
`vho_open_seed()`. It provides shared language for stacked entityhood and
condition continuity while each consumer keeps its own identity, evidence and
database. See the [VHO consumer anchor](docs/VHO-CONSUMER-ANCHOR.md).

## What belongs outside the core

This repository deliberately contains **no particular agent identity,
relationship history, private memory, provider prompt or product-specific
transport**. The optional open VHO reference is shared ontology vocabulary,
not a consumer identity or runtime authority.

| The core owns | The consuming application owns |
|---|---|
| Revision mechanics | Identity and personality |
| Evidence and provenance | Relationship history |
| Cue and graph retrieval | Private seeds and source data |
| Generic policy hooks | Product routing and lifecycle integration |
| Access telemetry | Final authority and permission boundaries |

It does not implement automatic transcript dumping, hidden-state access,
automatic authority over protected constraints or cross-product transport.
The included VHO reference is explicitly open and consumer-adopted; the memory
kernel does not silently impose an ontology or decide any consumer's stance.

## Verify

```bash
python3 -W error::ResourceWarning -m pytest -q
python3 -m pip wheel . --no-deps
```

CI runs the same checks on Linux, macOS and Windows with Python 3.10 and 3.13
(`.github/workflows/tests.yml`). The kernel uses only the standard library and
SQLite; database paths are supplied by the host.

The test suite includes an explicit boundary check that prevents consumer
identity or private seeds from entering the reusable kernel.

## Project status

The kernel is an alpha research-engineering extraction. The storage,
revision, evidence and retrieval boundaries are tested; the public API may
still evolve before `1.0`.

