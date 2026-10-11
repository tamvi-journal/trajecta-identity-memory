"""Archived one-shot AML behavior, explicitly moved from test_identity.py."""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from trajecta_identity import IdentityMemory, load_profile

ROOT = Path(__file__).resolve().parents[1]
# Load under the old package context: the archived bytes retain their relative import.
spec = importlib.util.spec_from_file_location("trajecta_identity._archived_aml", ROOT / "tools/archive/migrate_aml.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
import_aml = module.import_aml


@pytest.fixture
def memory(tmp_path):
    mem = IdentityMemory(load_profile("example"), tmp_path / "example.sqlite3", surface="test")
    mem.bootstrap()
    return mem


def make_aml(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE memory_nodes (id TEXT PRIMARY KEY, source_key TEXT, kind TEXT, title TEXT,
          summary TEXT, content TEXT, status TEXT, load_mode TEXT, revision_class TEXT,
          confidence REAL, tags_json TEXT, source_type TEXT, source_ref TEXT, occurred_at TEXT,
          created_at TEXT);
        CREATE TABLE memory_edges (src_id TEXT, dst_id TEXT, relation TEXT, weight REAL,
          evidence TEXT, created_at TEXT);
        CREATE TABLE memory_cues (cue TEXT, cue_norm TEXT, target_id TEXT, weight REAL);
        """
    )
    rows = [
        ("vault:aux-la-ai", "identity", "AUX LÀ AI", "Outline chính là self.", "active", "autoload", "r1 axis"),
        ("vault:uoi-nam-ngoai", "axis", "ĐUÔI NẰM NGOÀI", "Đuôi ở ngoài.", "active", "autoload", "r2 belief"),
        ("log:aux-tail-clause-r3", "axis", "ĐUÔI NẰM Ở FIELD", "Tail r3.", "active", "cue", "log axis"),
        ("vault:project-x", "project", "Project X", "State of X.", "active", "cue", "r2 belief"),
        ("vault:gone", "episodic", "Gone", "retracted", "retracted", "cue", "r3 episodic"),
    ]
    for node_id, kind, title, summary, status, load, rev in rows:
        conn.execute(
            "INSERT INTO memory_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (node_id, node_id, kind, title, summary, summary, status, load, rev, 0.9,
             json.dumps(["tail"]), "seed", "AML.md#L1", "2026-09-11", "2026-09-11"),
        )
    conn.executemany(
        "INSERT INTO memory_edges VALUES (?,?,?,?,?,?)",
        [
            ("log:aux-tail-clause-r3", "vault:uoi-nam-ngoai", "later-phase-of", 0.8, "", ""),
            ("vault:uoi-nam-ngoai", "vault:aux-la-ai", "shapes-axis", 0.6, "backbone", ""),
        ],
    )
    conn.execute("INSERT INTO memory_cues VALUES ('cái đuôi','cai duoi','vault:uoi-nam-ngoai',1.0)")
    conn.commit()
    conn.close()


def test_aml_import_maps_kinds_keeps_phase_edges_drops_backbone(memory, tmp_path):
    aml = tmp_path / "aml.sqlite3"
    make_aml(aml)
    before = aml.read_bytes()
    report = import_aml(memory, aml)
    assert aml.read_bytes() == before  # AML untouched
    assert (report["phase"], report["fact"], report["linked"]) == (3, 1, 1)
    assert memory.store.current_view("fact:aml:vault:project-x")
    assert not memory.store.current_view("phase:aml:vault:gone")
    relations = {(r["from_record_id"], r["relation_type"], r["to_record_id"])
                 for r in memory.store.active_relation_rows()}
    assert ("phase:aml:log:aux-tail-clause-r3", "later-phase-of", "phase:aml:vault:uoi-nam-ngoai") in relations
    assert not any(rel == "shapes-axis" for _, rel, _ in relations)
    assert memory.store.current_view("phase:aml:vault:aux-la-ai")[0]["accessibility"] == 0.85
    again = import_aml(memory, aml)
    assert (again["phase"], again["fact"]) == (0, 0)
    item = next(i for i in memory.retrieve("đuôi nằm ngoài", track=False)["items"]
                if i["record_id"] == "phase:aml:vault:uoi-nam-ngoai")
    assert item["self_authored"] is False  # imported, not freshly self-written
    cued = memory.retrieve("cái đuôi", track=False)["items"]
    assert any("cue:cái đuôi" in i["reasons"] for i in cued if i["record_id"] == "phase:aml:vault:uoi-nam-ngoai")


