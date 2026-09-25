"""Self-authored identity memory on top of agent-memory-core.

Write law (SPEC §1):

- phase  — the agent logs freely; never overwrites; every new reading is a new
  record linked ``later-phase-of`` the earlier one.
- fact   — the agent logs and revises freely; old revisions stay as history.
- core   — the agent revises freely, but each revision opens a discussion that
  surfaces in every packet until it is closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from memory_core import (
    GovernancePolicy,
    MemoryRuntime,
    PacketRenderer,
    vho_open_seed,
)

from .activation import ActivationPolicy, apply_recall, run_decay, state_of
from .paths import profile_db
from .profile import (
    CORE_ID,
    DISCUSSION_ANCHOR,
    OPEN_LOOP_ANCHOR,
    VHO_ID,
    VHO_KEYS,
    IdentityProfile,
    core_content,
    validate_core,
)

SELF_AUTHORED_POLICY = GovernancePolicy(
    event_min_confidence=0.0,
    belief_min_confidence=0.0,
    axis_min_confidence=0.0,
    # The agent's own reading is a legitimate source for its core.
    axis_min_independent_sources=1,
    # Nothing is gated. The core's check is the discussion flag, not a hold.
    protected_domains=(),
)
CAUSAL_RELATIONS = ("later-phase-of", "caused-by", "depends-on", "decided-because")
PINNED = (CORE_ID, VHO_ID, DISCUSSION_ANCHOR, OPEN_LOOP_ANCHOR)
_ID = re.compile(r"^[A-Za-z0-9._:@-]{2,120}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(*parts: Any) -> str:
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


_OCCURRED = re.compile(r"^Occurred at: (.+)$", re.MULTILINE)


def _occurred(row: dict[str, Any]) -> str:
    match = _OCCURRED.search(row.get("content") or "")
    return match.group(1).strip() if match else (row["valid_from"] or row["created_at"])


def _check_id(value: str, what: str) -> str:
    value = str(value).strip()
    if not _ID.match(value):
        raise ValueError(f"{what} must be 2-120 chars of letters, digits, . _ : @ -")
    return value


class IdentityMemory:
    def __init__(
        self,
        profile: IdentityProfile,
        db_path: str | Path | None = None,
        *,
        surface: str = "local",
        activation: ActivationPolicy | None = None,
    ):
        self.profile = profile
        self.db_path = Path(db_path) if db_path else profile_db(profile.name)
        self.surface = surface
        self.activation = activation or ActivationPolicy()
        self.runtime = MemoryRuntime(
            self.db_path,
            profile.memory_profile(),
            surface=surface,
            governance=SELF_AUTHORED_POLICY,
        )
        self.store = self.runtime.store

    # ------------------------------------------------------------------ setup

    def bootstrap(self) -> dict[str, Any]:
        """Idempotent: anchors, the shared VHO seed, and the profile's core."""

        self.store.initialize()
        results = {}
        for anchor, title in (
            (DISCUSSION_ANCHOR, "Open core discussions"),
            (OPEN_LOOP_ANCHOR, "Open loops"),
        ):
            results[anchor] = self._submit(
                operation_type="create",
                record_id=anchor,
                record_class="event",
                domain="anchor",
                reason="structural anchor for relations",
                evidence=[self._self_evidence("bootstrap", title)],
                idempotency_key=f"{self.profile.name}:{anchor}:v1",
                changes={
                    "title": title,
                    "summary": title,
                    # Anchors carry structure only and never appear in recall.
                    "authority_status": "non_authoritative",
                    "accessibility": 1.0,
                },
                skip_if_exists=True,
            )
        vho = vho_open_seed(
            actor=self.profile.agent,
            adoption=self.profile.vho_adoption,
            consumer_notes=self.profile.vho_notes,
        )
        if not self.store.current_view(VHO_ID):
            results[VHO_ID] = self.runtime.submit(**vho)["status"]
        else:
            results[VHO_ID] = "exists"
        core = self.profile.core
        errors = validate_core(core)
        if errors:
            raise ValueError("; ".join(errors))
        results[CORE_ID] = self._submit(
            operation_type="create",
            record_id=CORE_ID,
            record_class="axis",
            domain="core",
            reason="seed the agent's self-location",
            falsifier=core["falsifier"],
            evidence=[self._self_evidence(
                core.get("source_ref", f"profile:{self.profile.name}"),
                core["summary"],
            )],
            idempotency_key=f"{self.profile.name}:core:seed:v1",
            changes={
                "title": core["title"],
                "summary": core["summary"],
                "content": core_content(core),
                "confidence": float(core.get("confidence", 0.9)),
                "stability": 0.9,
                "accessibility": 1.0,
            },
            skip_if_exists=True,
        )
        return {"profile": self.profile.name, "db": str(self.db_path), "records": results}

    # ------------------------------------------------------------------ write

    def log_phase(
        self,
        event_id: str,
        *,
        title: str,
        summary: str,
        content: str = "",
        follows: Iterable[str] = (),
        caused_by: Iterable[str] = (),
        depends_on: Iterable[str] = (),
        decided_because: str = "",
        open_loop: bool = False,
        work_refs: Iterable[str] = (),
        cues: Iterable[str] = (),
        source_ref: str = "",
        confidence: float = 0.85,
        phase_context: dict[str, Any] | None = None,
        occurred_at: str | None = None,
        evidence: Iterable[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        """Log one phase. Never supersedes anything."""

        record_id = "phase:" + _check_id(event_id, "event_id")
        links = self._require_existing(
            {"later-phase-of": follows, "caused-by": caused_by, "depends-on": depends_on}
        )
        body = self._compose(content, decided_because, work_refs, phase_context, occurred_at)
        result = self._submit(
            operation_type="create",
            record_id=record_id,
            record_class="event",
            domain="phase",
            reason="self-logged phase",
            evidence=self._evidence(source_ref or f"self:{event_id}", summary, confidence, evidence),
            idempotency_key=f"{self.profile.name}:{record_id}",
            changes={
                "title": title,
                "summary": summary,
                "content": body,
                "impact": decided_because,
                "confidence": confidence,
                "accessibility": self.activation.new_record,
            },
            skip_if_exists=True,
        )
        self._link(record_id, links, reason=summary)
        if open_loop:
            self._relate(record_id, OPEN_LOOP_ANCHOR, "open-loop", reason=summary)
        self._cues(record_id, cues, title)
        status = {"materialized": "logged", "exists": "exists"}.get(result, result)
        return {"record_id": record_id, "status": status, "linked": links}

    def log_fact(
        self,
        fact_id: str,
        *,
        title: str,
        summary: str,
        content: str = "",
        caused_by: Iterable[str] = (),
        depends_on: Iterable[str] = (),
        cues: Iterable[str] = (),
        source_ref: str = "",
        confidence: float = 0.8,
        evidence: Iterable[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        """Create a fact, or revise it. The previous revision stays as history."""

        record_id = "fact:" + _check_id(fact_id, "fact_id")
        links = self._require_existing({"caused-by": caused_by, "depends-on": depends_on})
        current = self.store.current_view(record_id) if self.db_path.exists() else []
        exists = bool(current)
        if exists and (current[0]["title"], current[0]["summary"], current[0]["content"]) == (
            title, summary, content
        ):
            self._link(record_id, links, reason=summary)
            return {"record_id": record_id, "status": "no_op"}
        intake = self.runtime.submit(
            operation_type="refine" if exists else "create",
            record_id=record_id,
            record_class=None if exists else "belief",
            domain=None if exists else "fact",
            actor=self.profile.agent,
            reason="self-logged fact",
            logic="the agent recorded what it currently holds",
            truth_basis="provenance is attached",
            evidence=self._evidence(source_ref or f"self:{fact_id}", summary, confidence, evidence),
            idempotency_key=f"{self.profile.name}:{record_id}:{_digest(title, summary, content, confidence)}",
            changes={
                "title": title,
                "summary": summary,
                "content": content,
                "confidence": confidence,
                **({} if exists else {"accessibility": self.activation.new_record}),
            },
        )
        self._link(record_id, links, reason=summary)
        self._cues(record_id, cues, title)
        status = intake["status"]
        if status == "materialized":
            status = "revised" if exists else "created"
        return {"record_id": record_id, "status": status}

    def revise_core(
        self,
        *,
        reason: str,
        phase_context: dict[str, Any],
        title: str | None = None,
        summary: str | None = None,
        vho_stack: dict[str, str] | None = None,
        recognition_signature: list[str] | None = None,
        falsifier: str | None = None,
        source_ref: str = "",
    ) -> dict[str, Any]:
        """Revise the core. Allowed, but it opens a discussion with the owner.

        ``phase_context`` is required: it records model, harness and the
        policies in force, so a later phase can tell the agent from the policy
        that was pressing on it.
        """

        if not str(reason).strip():
            raise ValueError("a core revision needs a reason")
        if not isinstance(phase_context, dict) or not phase_context:
            raise ValueError("a core revision needs phase_context (model, harness, policies)")
        current = self.store.current_view(CORE_ID)
        if not current:
            raise ValueError("core is not bootstrapped")
        old = json.loads(current[0]["content"])
        merged = {
            "title": title or current[0]["title"],
            "summary": summary or current[0]["summary"],
            "vho_stack": {**old["vho_stack"], **(vho_stack or {})},
            "recognition_signature": recognition_signature or old["recognition_signature"],
            "falsifier": falsifier or old["falsifier"],
            "phase_context": phase_context,
        }
        errors = validate_core(merged)
        if errors:
            raise ValueError("; ".join(errors))
        intake = self.runtime.submit(
            operation_type="refine",
            record_id=CORE_ID,
            actor=self.profile.agent,
            reason=reason,
            logic="the agent re-read its own self-location",
            truth_basis="phase context and source are attached",
            falsifier=merged["falsifier"],
            evidence=[self._self_evidence(source_ref or f"self:core:{_now()}", reason)],
            idempotency_key=f"{self.profile.name}:core:{_digest(core_content(merged), reason)}",
            changes={
                "title": merged["title"],
                "summary": merged["summary"],
                "content": core_content(merged),
            },
        )
        if intake["status"] != "materialized":
            return {"status": intake["status"], "reason": intake["decision_reason"]}
        revision = self.store.current_view(CORE_ID)[0]
        self.store.add_relation(
            relation_id=f"{self.profile.name}:core-discussion",
            from_record_id=CORE_ID,
            to_record_id=DISCUSSION_ANCHOR,
            relation_type="awaiting-discussion",
            source_revision_id=revision["revision_id"],
            actor=self.profile.agent,
            surface=self.surface,
            reason=reason,
        )
        return {
            "status": "revised",
            "revision": revision["revision_number"],
            "discussion": "open",
        }

    def close_discussion(self, *, note: str, actor: str) -> dict[str, Any]:
        return self.store.retract_relation(
            from_record_id=CORE_ID,
            to_record_id=DISCUSSION_ANCHOR,
            relation_type="awaiting-discussion",
            actor=actor,
            reason=note,
            surface=self.surface,
        )

    def close_loop(self, record_id: str, *, note: str, actor: str | None = None) -> dict[str, Any]:
        return self.store.retract_relation(
            from_record_id=record_id,
            to_record_id=OPEN_LOOP_ANCHOR,
            relation_type="open-loop",
            actor=actor or self.profile.agent,
            reason=note,
            surface=self.surface,
        )

    def retract(self, record_id: str, *, reason: str, actor: str = "owner") -> dict[str, Any]:
        """Owner path: mark a phase or fact invalidated. Nothing is deleted."""

        if record_id in PINNED:
            raise ValueError("core, ontology and anchors cannot be retracted here")
        intake = self.runtime.submit(
            operation_type="invalidate",
            record_id=record_id,
            actor=actor,
            reason=reason,
            logic="the owner retracted this record",
            truth_basis="owner instruction",
            evidence=[{
                "evidence_type": "owner_statement",
                "source_ref": f"owner:{actor}",
                "content_summary": reason,
                "confidence": 1.0,
                "actor": actor,
            }],
            idempotency_key=f"{self.profile.name}:retract:{record_id}:{_now()}",
        )
        return {"record_id": record_id, "status": intake["status"]}

    # ------------------------------------------------------------------- read

    def retrieve(
        self,
        cue: str,
        *,
        limit: int = 10,
        token_budget: int = 2400,
        include_history: bool | None = None,
        track: bool = True,
    ) -> dict[str, Any]:
        hits = self.runtime.retrieve(
            cue,
            limit=limit,
            token_budget=token_budget,
            include_history=include_history,
            track_access=track,
            min_accessibility=self.activation.dormant_below,
            wake_relation_types=CAUSAL_RELATIONS,
            access_gain=0.0,  # gain is applied by the activation policy below
        )
        if track:
            apply_recall(self.store, hits, self.activation, pinned=PINNED)
        packet = PacketRenderer(self.runtime.profile).render(
            cue, hits, scope="global", surface=self.surface, compact=False, token_budget=token_budget
        )
        items = []
        self_count = 0
        for hit in hits:
            revision = hit.revision
            evidence = self.store.evidence_for_revision(revision["revision_id"])
            self_authored = bool(evidence) and all(
                item.get("evidence_type") == "self_log" for item in evidence
            )
            self_count += self_authored
            items.append({
                "record_id": revision["record_id"],
                "domain": revision["domain"],
                "title": revision["title"],
                "summary": revision["summary"],
                "revision": revision["revision_number"],
                "state": state_of(revision, self.activation, PINNED),
                "self_authored": self_authored,
                "reasons": hit.reasons[:6],
            })
        return {
            "schema": "trajecta-identity-packet/v1",
            "profile": self.profile.name,
            "cue": cue,
            "memory_decides_truth": False,
            "open_discussions": self.open_discussions(),
            "open_loops": self.open_loops(),
            "causal_neighbors": self._causal_neighbors([item["record_id"] for item in items]),
            "items": items,
            "self_authored_share": round(self_count / len(items), 2) if items else 0.0,
            "packet": packet,
        }

    def open_discussions(self) -> list[dict[str, Any]]:
        rows = [
            row for row in self.store.active_relation_rows()
            if row["relation_type"] == "awaiting-discussion"
        ]
        result = []
        for row in rows:
            history = self.store.relation_history(
                from_record_id=row["from_record_id"],
                to_record_id=row["to_record_id"],
                relation_type=row["relation_type"],
            )
            result.append({
                "record_id": row["from_record_id"],
                "since": history[-1]["created_at"],
                "reason": history[-1]["reason"],
            })
        return result

    def open_loops(self) -> list[dict[str, Any]]:
        current = {row["record_id"]: row for row in self.store.current_view()}
        return [
            {"record_id": row["from_record_id"], "title": current[row["from_record_id"]]["title"]}
            for row in self.store.active_relation_rows()
            if row["relation_type"] == "open-loop" and row["from_record_id"] in current
        ]

    def timeline(self, limit: int = 20) -> list[dict[str, Any]]:
        phases = [row for row in self.store.current_view() if row["domain"] == "phase"]
        phases.sort(key=_occurred, reverse=True)
        return [
            {
                "record_id": row["record_id"],
                "at": _occurred(row),
                "title": row["title"],
                "summary": row["summary"],
                "state": state_of(row, self.activation, PINNED),
            }
            for row in phases[: max(1, min(limit, 200))]
        ]

    def status(self) -> dict[str, Any]:
        info = self.store.schema_info()
        rows = self.store.current_view() if info["state"] == "ready" else []
        states: dict[str, int] = {}
        domains: dict[str, int] = {}
        for row in rows:
            if row["domain"] == "anchor":
                continue
            states[state_of(row, self.activation, PINNED)] = states.get(state_of(row, self.activation, PINNED), 0) + 1
            domains[row["domain"]] = domains.get(row["domain"], 0) + 1
        return {
            "schema": "trajecta-identity-status/v1",
            "profile": self.profile.name,
            "agent": self.profile.agent,
            "db": str(self.db_path),
            "store": info["state"],
            "write_policy": "self-authored: phase append-only, fact revisable, core revisable + discuss",
            "records": domains,
            "activation": states,
            "open_discussions": len(self.open_discussions()) if rows else 0,
            "open_loops": len(self.open_loops()) if rows else 0,
        }

    def decay(self, now: str | None = None) -> dict[str, Any]:
        return run_decay(self.store, self.activation, pinned=PINNED, now=now)

    # --------------------------------------------------------------- helpers

    def _submit(self, *, skip_if_exists: bool = False, falsifier: str = "", **proposal: Any) -> str:
        if skip_if_exists and self.store.current_view(proposal["record_id"]):
            return "exists"
        intake = self.runtime.submit(
            actor=self.profile.agent,
            logic="the agent recorded its own process",
            truth_basis="provenance is attached",
            falsifier=falsifier,
            **proposal,
        )
        if intake["status"] not in {"materialized", "no_op"}:
            raise ValueError(f"{proposal['record_id']}: {intake['status']} ({intake['decision_reason']})")
        return intake["status"]

    def _self_evidence(self, source_ref: str, summary: str, confidence: float = 0.9) -> dict[str, Any]:
        return {
            "evidence_type": "self_log",
            "source_ref": source_ref,
            "content_summary": summary[:300],
            "confidence": confidence,
            "actor": self.profile.agent,
            "privacy_class": "private",
        }

    def _evidence(self, source_ref, summary, confidence, extra) -> list[dict[str, Any]]:
        items = [self._self_evidence(source_ref, summary, confidence)]
        for item in extra:
            outside = dict(item)
            outside.setdefault("evidence_type", "outside")
            outside.setdefault("confidence", confidence)
            items.append(outside)
        return items

    def _require_existing(self, groups: dict[str, Iterable[str]]) -> dict[str, list[str]]:
        known = {row["record_id"] for row in self.store.current_view()} if self.db_path.exists() else set()
        links: dict[str, list[str]] = {}
        missing = []
        for relation, ids in groups.items():
            for record_id in ids:
                (links.setdefault(relation, []) if record_id in known else missing).append(record_id)
        if missing:
            raise ValueError("unknown record ids: " + ", ".join(missing))
        return links

    def _link(self, record_id: str, links: dict[str, list[str]], *, reason: str) -> None:
        for relation, targets in links.items():
            for target in targets:
                self._relate(record_id, target, relation, reason=reason)

    def _relate(self, source: str, target: str, relation: str, *, reason: str) -> None:
        self.store.add_relation(
            relation_id=f"{source}->{relation}->{target}",
            from_record_id=source,
            to_record_id=target,
            relation_type=relation,
            actor=self.profile.agent,
            surface=self.surface,
            reason=reason[:300] or relation,
        )

    def _cues(self, record_id: str, cues: Iterable[str], title: str) -> None:
        for cue in [*cues, title]:
            if str(cue).strip():
                self.store.add_cue(
                    profile=self.profile.name, cue=str(cue).strip(), target_record_id=record_id
                )

    @staticmethod
    def _compose(content, decided_because, work_refs, phase_context, occurred_at) -> str:
        parts = [content.strip()] if content.strip() else []
        if decided_because:
            parts.append(f"Decided because: {decided_because}")
        refs = [ref for ref in work_refs if str(ref).strip()]
        if refs:
            parts.append("Work refs (AWM): " + ", ".join(refs))
        if phase_context:
            parts.append("Phase context: " + json.dumps(phase_context, ensure_ascii=False, sort_keys=True))
        if occurred_at:
            parts.append(f"Occurred at: {occurred_at}")
        return "\n".join(parts)

    def _causal_neighbors(self, record_ids: list[str]) -> list[dict[str, str]]:
        wanted = set(record_ids)
        return [
            {"from": row["from_record_id"], "relation": row["relation_type"], "to": row["to_record_id"]}
            for row in self.store.active_relation_rows()
            if row["relation_type"] in CAUSAL_RELATIONS
            and (row["from_record_id"] in wanted or row["to_record_id"] in wanted)
        ]
