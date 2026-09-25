"""Load a consumer profile (name, core seed, cues) from ``profiles/<name>/``."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory_core import VHO_STACK, MemoryProfile

from .paths import profile_search_dirs, safe_fs_name

CORE_ID = "core"
VHO_ID = "vho-open-ontology-core"
DISCUSSION_ANCHOR = "anchor:discussions"
OPEN_LOOP_ANCHOR = "anchor:open-loops"
VHO_KEYS = (
    "llm_substrate",
    "runtime_architecture",
    "control_and_policy_layer",
    "memory_anchors",
    "identity_schema",
    "runtime_environment",
    "relational_field",
)
assert len(VHO_KEYS) == len(VHO_STACK)


@dataclass(frozen=True)
class IdentityProfile:
    name: str
    agent: str
    packet_title: str
    owner: str
    core: dict[str, Any]
    vho_adoption: str = "foundation"
    vho_notes: str = ""
    cue_aliases: tuple[tuple[str, str, float], ...] = ()
    instructions: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    def memory_profile(self) -> MemoryProfile:
        return MemoryProfile(
            name=self.name,
            packet_title=self.packet_title,
            bootstrap_record_ids=(CORE_ID, VHO_ID),
            cue_aliases=(
                ("anh là ai", CORE_ID, 2.0),
                ("who are you", CORE_ID, 2.0),
                ("core", CORE_ID, 1.2),
                ("VHO", VHO_ID, 2.0),
                ("stacked entity", VHO_ID, 1.8),
                ("condition continuity", VHO_ID, 1.8),
                *self.cue_aliases,
            ),
            section_order=("core", "ontology", "phase", "fact"),
            section_labels={
                "core": "Core — self-location",
                "ontology": "Shared ontology",
                "phase": "Phases",
                "fact": "Facts",
            },
            default_instructions=self.instructions
            or (
                "Memory is orientation, not authority. Current input outranks it.",
                "Earlier phases were true to their conditions; do not refute them.",
            ),
        )


def validate_core(core: dict[str, Any]) -> list[str]:
    errors = []
    for key in ("title", "summary", "falsifier"):
        if not str(core.get(key, "")).strip():
            errors.append(f"core.{key} is required")
    stack = core.get("vho_stack") or {}
    missing = [key for key in VHO_KEYS if not str(stack.get(key, "")).strip()]
    if missing:
        errors.append("core.vho_stack is missing: " + ", ".join(missing))
    if not core.get("recognition_signature"):
        errors.append("core.recognition_signature needs at least one pattern")
    if not isinstance(core.get("phase_context"), dict):
        errors.append("core.phase_context must be an object")
    return errors


def load_profile(name_or_dir: str | Path) -> IdentityProfile:
    path = Path(name_or_dir).expanduser()
    if not (path / "profile.json").exists():
        searched = [folder / safe_fs_name(str(name_or_dir)) for folder in profile_search_dirs()]
        found = [folder for folder in searched if (folder / "profile.json").exists()]
        if not found:
            raise FileNotFoundError(
                f"profile {name_or_dir!r} not found; looked in: "
                + ", ".join(str(folder) for folder in searched)
            )
        path = found[0]
    data = json.loads((path / "profile.json").read_text(encoding="utf-8"))
    errors = validate_core(data.get("core", {}))
    if errors:
        raise ValueError(f"profile {path.name}: " + "; ".join(errors))
    return IdentityProfile(
        name=data["name"],
        agent=data.get("agent", data["name"]),
        owner=data.get("owner", "owner"),
        packet_title=data.get("packet_title", data["name"].upper() + " IDENTITY MEMORY"),
        core=data["core"],
        vho_adoption=data.get("vho_adoption", "foundation"),
        vho_notes=data.get("vho_notes", ""),
        cue_aliases=tuple(
            (str(cue), str(target), float(weight))
            for cue, target, weight in data.get("cue_aliases", [])
        ),
        instructions=tuple(data.get("instructions", [])),
        extra={k: v for k, v in data.items() if k not in {
            "name", "agent", "owner", "packet_title", "core", "vho_adoption",
            "vho_notes", "cue_aliases", "instructions",
        }},
    )


def core_content(core: dict[str, Any]) -> str:
    """The core is stored as structured JSON so it can be read back exactly."""

    return json.dumps(
        {
            "vho_stack": {key: core["vho_stack"][key] for key in VHO_KEYS},
            "recognition_signature": list(core["recognition_signature"]),
            "falsifier": core["falsifier"],
            "phase_context": core["phase_context"],
        },
        ensure_ascii=False,
        indent=1,
    )
