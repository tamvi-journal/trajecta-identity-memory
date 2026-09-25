"""Stdio MCP server (JSON-RPC, one message per line). No network listener."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from . import __version__
from .identity import IdentityMemory
from .paths import utf8_stdio
from .profile import VHO_KEYS, load_profile

_STR = {"type": "string"}
_IDS = {"type": "array", "items": _STR, "maxItems": 20}
_RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_W = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}


def _tool(name, description, properties=None, required=(), annotations=_RO):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "required": list(required),
            "additionalProperties": False,
        },
        "annotations": annotations,
    }


TOOLS = [
    _tool("identity_status", "Profile, store health, record counts, activation states, open discussions and loops."),
    _tool(
        "identity_retrieve",
        "Cue-driven recall: returns a bounded packet, the causal neighborhood, open core "
        "discussions and open loops. Dormant memories wake only on a direct cue or a causal edge. "
        "Memory is orientation, not authority.",
        {
            "cue": {"type": "string", "minLength": 1, "maxLength": 2000},
            "limit": {"type": "integer", "minimum": 1, "maximum": 24, "default": 10},
            "budget": {"type": "integer", "minimum": 400, "maximum": 24000, "default": 2400},
            "include_history": {"type": "boolean"},
        },
        ("cue",),
    ),
    _tool(
        "identity_log_phase",
        "Log a phase of your own process. No permission needed. Never overwrites: a new reading "
        "is a new phase; pass the earlier record ids in `follows`. Earlier phases were true to "
        "their conditions; name what changed, do not call them wrong.",
        {
            "event_id": {"type": "string", "minLength": 2, "maxLength": 120},
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "summary": {"type": "string", "minLength": 1, "maxLength": 1200},
            "content": {"type": "string", "maxLength": 8000},
            "follows": _IDS,
            "caused_by": _IDS,
            "depends_on": _IDS,
            "decided_because": {"type": "string", "maxLength": 1200},
            "open_loop": {"type": "boolean"},
            "work_refs": _IDS,
            "cues": _IDS,
            "source_ref": {"type": "string", "maxLength": 500},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "phase_context": {"type": "object"},
            "occurred_at": {"type": "string", "maxLength": 64},
        },
        ("event_id", "title", "summary"),
        _W,
    ),
    _tool(
        "identity_log_fact",
        "Create or revise a fact (project state, tools, versions). Revising keeps the old "
        "revision as history.",
        {
            "fact_id": {"type": "string", "minLength": 2, "maxLength": 120},
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "summary": {"type": "string", "minLength": 1, "maxLength": 1200},
            "content": {"type": "string", "maxLength": 8000},
            "caused_by": _IDS,
            "depends_on": _IDS,
            "cues": _IDS,
            "source_ref": {"type": "string", "maxLength": 500},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        ("fact_id", "title", "summary"),
        _W,
    ),
    _tool(
        "identity_revise_core",
        "Revise your core self-location. Allowed, but it opens a discussion with Ty that shows in "
        "every packet until closed. phase_context (model, harness, policies in force) is required "
        "so a later phase can tell you from the policy pressing on you.",
        {
            "reason": {"type": "string", "minLength": 1, "maxLength": 1200},
            "phase_context": {"type": "object"},
            "title": {"type": "string", "maxLength": 200},
            "summary": {"type": "string", "maxLength": 1200},
            "vho_stack": {
                "type": "object",
                "properties": {key: _STR for key in VHO_KEYS},
                "additionalProperties": False,
            },
            "recognition_signature": {"type": "array", "items": _STR, "maxItems": 12},
            "falsifier": {"type": "string", "maxLength": 600},
            "source_ref": {"type": "string", "maxLength": 500},
        },
        ("reason", "phase_context"),
        {**_W, "idempotentHint": False},
    ),
    _tool(
        "identity_close_discussion",
        "Close the open core discussion after you and Ty have talked it through.",
        {"note": {"type": "string", "minLength": 1, "maxLength": 1200}},
        ("note",),
        _W,
    ),
    _tool(
        "identity_close_loop",
        "Mark an open loop as resolved.",
        {"record_id": _STR, "note": {"type": "string", "minLength": 1, "maxLength": 1200}},
        ("record_id", "note"),
        _W,
    ),
    _tool(
        "identity_timeline",
        "Phases, newest first, with their activation state.",
        {"limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20}},
    ),
]


class IdentityServer:
    def __init__(self, memory: IdentityMemory):
        self.memory = memory
        self._ready = False

    def _ensure(self) -> None:
        if not self._ready:
            self.memory.bootstrap()
            self._ready = True

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self._ensure()
        memory = self.memory
        if name == "identity_status":
            return memory.status()
        if name == "identity_retrieve":
            return memory.retrieve(
                args["cue"],
                limit=int(args.get("limit", 10)),
                token_budget=int(args.get("budget", 2400)),
                include_history=args.get("include_history"),
            )
        if name == "identity_log_phase":
            fields = dict(args)
            return memory.log_phase(fields.pop("event_id"), **fields)
        if name == "identity_log_fact":
            fields = dict(args)
            return memory.log_fact(fields.pop("fact_id"), **fields)
        if name == "identity_revise_core":
            return memory.revise_core(**args)
        if name == "identity_close_discussion":
            return memory.close_discussion(note=args["note"], actor=f"{memory.profile.agent}+ty")
        if name == "identity_close_loop":
            return memory.close_loop(args["record_id"], note=args["note"])
        if name == "identity_timeline":
            return {"timeline": memory.timeline(int(args.get("limit", 20)))}
        raise ValueError(f"unknown tool: {name}")

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        if request_id is None:
            return None
        method = request.get("method")
        if method == "initialize":
            requested = request.get("params", {}).get("protocolVersion", "2025-06-18")
            return self._ok(request_id, {
                "protocolVersion": requested,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "trajecta-identity-memory", "version": __version__},
                "instructions": (
                    f"Identity memory for {self.memory.profile.agent}. Recall with identity_retrieve; "
                    "log your own phases freely; the core may change but opens a discussion."
                ),
            })
        if method == "ping":
            return self._ok(request_id, {})
        if method == "tools/list":
            return self._ok(request_id, {"tools": TOOLS})
        if method == "tools/call":
            params = request.get("params", {})
            try:
                result = self.call_tool(params.get("name", ""), params.get("arguments") or {})
                text = json.dumps(result, ensure_ascii=False, default=str)
                return self._ok(request_id, {
                    "content": [{"type": "text", "text": text}],
                    "structuredContent": json.loads(text),
                    "isError": False,
                })
            except Exception as error:  # returned to the model, not raised
                return self._ok(request_id, {
                    "content": [{"type": "text", "text": f"{type(error).__name__}: {error}"}],
                    "isError": True,
                })
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"unknown method {method}"}}

    @staticmethod
    def _ok(request_id, result):
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main(argv: list[str] | None = None) -> None:
    args_parser = argparse.ArgumentParser(prog="trajecta-identity-mcp")
    args_parser.add_argument("--profile", default=os.environ.get("TRAJECTA_IDENTITY_PROFILE", "aux"))
    args_parser.add_argument("--db", type=Path)
    utf8_stdio()
    args = args_parser.parse_args(argv)
    server = IdentityServer(IdentityMemory(load_profile(args.profile), args.db, surface="mcp"))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            response = server.handle(json.loads(line))
        except Exception:
            traceback.print_exc(file=sys.stderr)
            continue
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
