from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .identity import IdentityMemory
from .paths import utf8_stdio
from .profile import load_profile


def _list(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="trajecta-identity", description="Trajecta Identity Memory")
    root.add_argument("--profile", default="aux", help="profile name in profiles/ or a profile folder")
    root.add_argument("--db", type=Path, help="override the database path")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="bootstrap anchors, VHO and the core")
    commands.add_parser("status")
    retrieve = commands.add_parser("retrieve")
    retrieve.add_argument("cue")
    retrieve.add_argument("--limit", type=int, default=10)
    retrieve.add_argument("--budget", type=int, default=2400)
    retrieve.add_argument("--history", action="store_true")
    retrieve.add_argument("--readonly", action="store_true", help="do not change activation")
    retrieve.add_argument("--packet", action="store_true", help="print only the text packet")
    phase = commands.add_parser("log-phase")
    phase.add_argument("event_id")
    phase.add_argument("--title", required=True)
    phase.add_argument("--summary", required=True)
    phase.add_argument("--content", default="")
    phase.add_argument("--follows", help="comma-separated earlier record ids")
    phase.add_argument("--caused-by")
    phase.add_argument("--depends-on")
    phase.add_argument("--open-loop", action="store_true")
    phase.add_argument("--source", default="")
    fact = commands.add_parser("log-fact")
    fact.add_argument("fact_id")
    fact.add_argument("--title", required=True)
    fact.add_argument("--summary", required=True)
    fact.add_argument("--content", default="")
    fact.add_argument("--source", default="")
    timeline = commands.add_parser("timeline")
    timeline.add_argument("--limit", type=int, default=20)
    commands.add_parser("decay", help="apply time decay (run daily, e.g. from a scheduler)")
    close = commands.add_parser("close-discussion", help="after talking about a core revision")
    close.add_argument("--note", required=True)
    close.add_argument("--actor", default="ty")
    loop = commands.add_parser("close-loop")
    loop.add_argument("record_id")
    loop.add_argument("--note", required=True)
    retract = commands.add_parser("retract", help="owner: mark a phase/fact invalidated (never deletes)")
    retract.add_argument("record_id")
    retract.add_argument("--reason", required=True)
    retract.add_argument("--actor", default="ty")
    aml = commands.add_parser("import-aml", help="import an AML vault (read-only)")
    aml.add_argument("path", type=Path)
    return root


def main(argv: list[str] | None = None) -> None:
    utf8_stdio()
    args = parser().parse_args(argv)
    memory = IdentityMemory(load_profile(args.profile), args.db, surface="cli")
    command = args.command
    if command != "init":
        memory.bootstrap()  # idempotent; a fresh machine works without a separate init
    if command == "init":
        result = memory.bootstrap()
    elif command == "status":
        result = memory.status()
    elif command == "retrieve":
        result = memory.retrieve(
            args.cue,
            limit=args.limit,
            token_budget=args.budget,
            include_history=True if args.history else None,
            track=not args.readonly,
        )
        if args.packet:
            sys.stdout.write(result["packet"])
            return
    elif command == "log-phase":
        result = memory.log_phase(
            args.event_id,
            title=args.title,
            summary=args.summary,
            content=args.content,
            follows=_list(args.follows),
            caused_by=_list(args.caused_by),
            depends_on=_list(args.depends_on),
            open_loop=args.open_loop,
            source_ref=args.source,
        )
    elif command == "log-fact":
        result = memory.log_fact(
            args.fact_id, title=args.title, summary=args.summary,
            content=args.content, source_ref=args.source,
        )
    elif command == "timeline":
        result = {"timeline": memory.timeline(args.limit)}
    elif command == "decay":
        result = memory.decay()
    elif command == "close-discussion":
        result = memory.close_discussion(note=args.note, actor=args.actor)
    elif command == "close-loop":
        result = memory.close_loop(args.record_id, note=args.note)
    elif command == "retract":
        result = memory.retract(args.record_id, reason=args.reason, actor=args.actor)
    elif command == "import-aml":
        from .migrate_aml import import_aml

        result = import_aml(memory, args.path)
    else:  # pragma: no cover
        raise SystemExit(f"unknown command {command}")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
