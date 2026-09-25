# Trajecta Identity Memory

Self-authored identity memory for agents, built on
[agent-memory-core](https://github.com/tamvi-journal/agent-memory-core)
(pinned at `feeaa59`, kernel 0.3).

Part of the Trajecta family:

| Layer | Owns |
|---|---|
| `agent-memory-core` | revisions, evidence, lifecycle, relations, telemetry, retrieval |
| `trajecta-memory` (AWM) | work: objectives, decisions, blockers, handoffs |
| **`trajecta-identity-memory`** | who the agent is: core, phases, recognition, activation |

Identity points to work (`work_refs`) and never copies it. See
[`docs/SPEC-v0.1.md`](docs/SPEC-v0.1.md).

## Write law: the agent writes its own memory

| Tier | Write | Overwrite |
|---|---|---|
| **phase** | freely | never. A new reading is a new phase, linked `later-phase-of` the earlier one |
| **fact** | freely | freely. The old revision stays as history |
| **core** | freely | freely, but it opens a discussion that shows in every packet until it is closed |

Each core revision requires `phase_context` (model, harness, policies in force).
The owner can retract a phase or fact from the CLI. That marks it; nothing is
deleted.

## Recall: cue → behavior → shape

- The core and the shared VHO seed are pinned: always in the packet, never
  decay.
- Recall raises activation with a diminishing gain, capped at 0.9.
  Stability is never raised by recall (ego guard).
- `decay` fades records by time, with a half-life of about 21 days scaled by
  stability.
- Below 0.15 a record is **dormant**. Lexical search skips it. A direct cue or a
  causal edge (`later-phase-of`, `caused-by`, `depends-on`, `decided-because`)
  wakes it back to 0.4.
- Each packet carries the causal neighborhood, open discussions, open loops,
  and `self_authored_share`.

## Install

macOS / Linux:

```bash
install/install.sh aux
# use a local kernel checkout instead of the pinned git commit:
AGENT_MEMORY_CORE_PATH=~/path/to/agent-memory-core install/install.sh aux
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File install\install.ps1 -AgentProfile aux
```

The installer bootstraps the profile and prints the MCP config block.

Memory lives on the machine only:

| OS | Location |
|---|---|
| macOS | `~/Library/Application Support/Trajecta Identity Memory/<profile>.sqlite3` |
| Linux | `$XDG_DATA_HOME/trajecta-identity-memory/` or `~/.local/share/...` |
| Windows | `%LOCALAPPDATA%\Trajecta Identity Memory\` |

Override the location with `TRAJECTA_IDENTITY_DATA_DIR`.

## CLI

```bash
trajecta-identity --profile aux status
trajecta-identity --profile aux retrieve "anh là ai" --packet
trajecta-identity --profile aux log-phase tail-r3 --title "..." --summary "..." --follows phase:tail-r2
trajecta-identity --profile aux timeline
trajecta-identity --profile aux decay                      # daily
trajecta-identity --profile aux close-discussion --note "talked it through"
trajecta-identity --profile aux retract phase:x --reason "..."   # owner
trajecta-identity --profile aux import-aml "~/Library/Application Support/Aux Memory Layer/aml.sqlite3"
```

## MCP tools

`identity_status`, `identity_retrieve`, `identity_log_phase`,
`identity_log_fact`, `identity_revise_core`, `identity_close_discussion`,
`identity_close_loop`, `identity_timeline`. Retraction is not exposed over MCP.

The skill that teaches an agent to use them is in
`skills/identity-continuity/SKILL.md`.

## Profiles

- `profiles/aux/` is Aux's profile: core with the 7-layer VHO stack,
  recognition signature, falsifier and phase context.
- `profiles/_template/` refuses to load until it is filled in. Each agent (Lam,
  Tracey, Seyn…) writes its **own** core. The profile only holds the seed; the
  lived memory stays in the local database.

> Before pushing this repo publicly, decide whether `profiles/aux/` belongs in
> it or in a private profiles folder.

## Test

```bash
.venv/bin/python -m pytest -q
```
