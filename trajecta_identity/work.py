"""Read-only bridge to a trajecta-work-memory store.

Identity points to work; it never writes to it. This module reads the files a
trajecta-work-memory store keeps (``state.json``, schema
``trajecta.state/v1``, and ``deltas.jsonl``) so that identity can:

- check that ``work_refs`` name real work items or deltas;
- show the referenced work (topic, status, next action, revision) next to
  the identity memories that point to it.

The work store is found through ``$TRAJECTA_WORK_ROOT`` or a profile's
``work_root`` field. Without one, work refs are kept as plain text.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

ENV_WORK_ROOT = "TRAJECTA_WORK_ROOT"
STATE_SCHEMA = "trajecta.state/v1"
REF_PATTERN = re.compile(r"\b(?:work|delta):[0-9a-fA-F-]{8,}\b")
_WORK_LINE = re.compile(r"^Work refs \(trajecta-work-memory\): (.+)$", re.MULTILINE)


class WorkStoreError(RuntimeError):
    pass


class WorkStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser()

    @classmethod
    def from_config(cls, profile_extra: dict[str, Any] | None = None, env: dict[str, str] | None = None):
        environ = dict(os.environ if env is None else env)
        root = environ.get(ENV_WORK_ROOT, "").strip() or str((profile_extra or {}).get("work_root", "")).strip()
        return cls(root) if root else None

    def _state(self) -> dict[str, Any]:
        path = self.root / "state.json"
        if not path.exists():
            return {"schema": STATE_SCHEMA, "work": []}
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise WorkStoreError(f"unreadable work state: {path}") from error
        if state.get("schema") != STATE_SCHEMA or not isinstance(state.get("work"), list):
            raise WorkStoreError(f"unsupported work state schema in {path}: {state.get('schema')!r}")
        return state

    def _deltas(self) -> list[dict[str, Any]]:
        path = self.root / "deltas.jsonl"
        if not path.exists():
            return []
        deltas = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                deltas.append(json.loads(line))
            except ValueError:
                continue  # a torn final line belongs to the work store's own recovery
        return deltas

    def work_items(self) -> list[dict[str, Any]]:
        return [self.summarize(item) for item in self._state()["work"]]

    def resolve(self, ref: str) -> dict[str, Any] | None:
        ref = ref.strip()
        if ref.startswith("work:"):
            for item in self._state()["work"]:
                if item.get("id") == ref:
                    return self.summarize(item)
            return None
        if ref.startswith("delta:"):
            for delta in self._deltas():
                if delta.get("id") == ref:
                    work = self.resolve(str(delta.get("workId", "")))
                    return {
                        "ref": ref,
                        "kind": "delta",
                        "delta_kind": delta.get("kind"),
                        "summary": delta.get("summary", ""),
                        "revision": delta.get("revision"),
                        "created_at": delta.get("createdAt"),
                        "work": work,
                    }
            return None
        return None

    def missing(self, refs: list[str]) -> list[str]:
        return [ref for ref in refs if self.resolve(ref) is None]

    @staticmethod
    def summarize(item: dict[str, Any]) -> dict[str, Any]:
        branch = next(
            (b for b in item.get("branches", []) if b.get("id") == item.get("activeBranchId")),
            None,
        )
        return {
            "ref": item.get("id"),
            "kind": "work",
            "topic": item.get("topic", ""),
            "goal": item.get("goal", ""),
            "status": item.get("status"),
            "revision": item.get("revision"),
            "next_action": item.get("nextAction"),
            "open_loops": list(item.get("openLoops", [])),
            "active_branch": branch.get("label") if branch else None,
            "updated_at": item.get("updatedAt"),
        }


def refs_in(content: str) -> list[str]:
    """Work refs recorded on an identity memory."""

    match = _WORK_LINE.search(content or "")
    if not match:
        return []
    return [ref.strip() for ref in match.group(1).split(",") if ref.strip()]
