"""Import an AML (Aux Memory Layer) vault into an identity profile.

AML stays untouched (read-only open). Every node becomes a phase or a fact
with provenance back to AML. Only phase edges are carried; AML's
"everything connects to core" backbone and tag chains are deliberately left
behind (SPEC §4).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .identity import IdentityMemory

PHASE_KINDS = {"identity", "axis", "relationship", "boundary", "episodic"}
FACT_KINDS = {"semantic", "procedural", "project"}
CARRIED_EDGES = {"later-phase-of": "later-phase-of", "supersedes": "later-phase-of"}


def _event_id(node_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._:@-]+", "-", node_id).strip("-")
    return ("aml:" + slug)[:120]


def import_aml(memory: IdentityMemory, aml_db: str | Path) -> dict[str, Any]:
    path = Path(aml_db).expanduser()
    if not path.exists():
        raise FileNotFoundError(path)
    source_sha = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        nodes = conn.execute(
            "SELECT * FROM memory_nodes WHERE status IN ('active','superseded') "
            "ORDER BY COALESCE(occurred_at, created_at), id"
        ).fetchall()
        edges = conn.execute("SELECT src_id, dst_id, relation FROM memory_edges").fetchall()
    finally:
        conn.close()

    memory.bootstrap()
    mapping: dict[str, str] = {}
    counts = {"phase": 0, "fact": 0, "exists": 0, "skipped": 0, "linked": 0}
    for node in nodes:
        kind = str(node["kind"]).casefold()
        tags = json.loads(node["tags_json"] or "[]")
        provenance = {
            "evidence_type": "aml_import",
            "source_ref": f"aml:{source_sha}:{node['id']}",
            "content_summary": f"Imported from AML node {node['id']} ({node['source_ref']})",
            "confidence": float(node["confidence"]),
            "actor": "aml-import",
            "privacy_class": "private",
        }
        note = f"AML {kind} node {node['id']}, status {node['status']}, revision {node['revision_class']}."
        content = (node["content"] or "").strip() + "\n\n" + note
        summary = (node["summary"] or node["title"])[:600]
        if kind in PHASE_KINDS:
            result = memory.log_phase(
                _event_id(node["id"]),
                title=node["title"][:200],
                summary=summary,
                content=content,
                cues=tags[:12],
                source_ref=node["source_ref"] or f"aml:{node['id']}",
                confidence=float(node["confidence"]),
                occurred_at=node["occurred_at"] or node["created_at"],
                evidence=[provenance],
            )
            counts["exists" if result["status"] == "exists" else "phase"] += 1
        elif kind in FACT_KINDS:
            result = memory.log_fact(
                _event_id(node["id"]),
                title=node["title"][:200],
                summary=summary,
                content=content,
                cues=tags[:12],
                source_ref=node["source_ref"] or f"aml:{node['id']}",
                confidence=float(node["confidence"]),
                evidence=[provenance],
            )
            counts["exists" if result["status"] == "no_op" else "fact"] += 1
        else:
            counts["skipped"] += 1
            continue
        mapping[node["id"]] = result["record_id"]
        if node["load_mode"] == "autoload" and result["status"] not in {"exists", "no_op"}:
            memory.store.apply_maintenance(
                run_id=f"aml-autoload:{node['id']}",
                adjustments=[{"record_id": result["record_id"], "field": "accessibility", "new_value": 0.85}],
                actor="aml-import",
                reason="AML autoload node starts highly accessible",
            )

    for edge in edges:
        relation = CARRIED_EDGES.get(edge["relation"])
        if not relation or edge["src_id"] not in mapping or edge["dst_id"] not in mapping:
            continue
        memory._relate(
            mapping[edge["src_id"]], mapping[edge["dst_id"]], relation,
            reason=f"carried from AML edge {edge['relation']}",
        )
        counts["linked"] += 1
    return {"source": str(path), "source_sha256_16": source_sha, **counts}
