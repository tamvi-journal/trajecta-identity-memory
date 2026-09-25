"""The fixture store in tests/fixtures/work-store was written by the real
trajecta-work-memory TypeScript store (TrajectaStore + TrajectaRelay)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from trajecta_identity import IdentityMemory, load_profile
from trajecta_identity.work import WorkStore, WorkStoreError

FIXTURE = Path(__file__).parent / "fixtures" / "work-store"


def state():
    return json.loads((FIXTURE / "state.json").read_text(encoding="utf-8"))


def digest(folder: Path) -> str:
    return hashlib.sha256(b"".join(p.read_bytes() for p in sorted(folder.iterdir()))).hexdigest()


@pytest.fixture
def work_id():
    return next(w["id"] for w in state()["work"] if w["topic"] == "Ship identity memory")


@pytest.fixture
def memory(tmp_path, monkeypatch):
    root = tmp_path / "work"
    shutil.copytree(FIXTURE, root)
    monkeypatch.setenv("TRAJECTA_WORK_ROOT", str(root))
    mem = IdentityMemory(load_profile("example"), tmp_path / "m.sqlite3")
    mem.bootstrap()
    return mem


def test_reads_the_real_work_store(work_id):
    store = WorkStore(FIXTURE)
    item = store.resolve(work_id)
    assert item["topic"] == "Ship identity memory"
    assert item["next_action"] == "Build the work bridge"
    assert item["active_branch"] == "merge"
    assert item["revision"] == 3
    delta_id = json.loads((FIXTURE / "deltas.jsonl").read_text().splitlines()[1])["id"]
    delta = store.resolve(delta_id)
    assert delta["kind"] == "delta" and delta["work"]["ref"] == work_id
    assert store.resolve("work:00000000-0000-0000-0000-000000000000") is None
    assert len(store.work_items()) == 2


def test_phase_validates_and_links_work(memory, work_id):
    before = digest(memory.work.root)
    with pytest.raises(ValueError, match="unknown work refs"):
        memory.log_phase("bad", title="t", summary="s",
                         work_refs=["work:00000000-0000-0000-0000-000000000000"])
    memory.log_phase("bridge", title="Built the work bridge", summary="Identity now reads work",
                     work_refs=[work_id], cues=["work bridge"])
    item = next(i for i in memory.retrieve("work bridge", track=False)["items"]
                if i["record_id"] == "phase:bridge")
    assert item["work"][0]["topic"] == "Ship identity memory"
    assert digest(memory.work.root) == before  # identity never writes to work
    assert memory.status()["work_store"] == str(memory.work.root)


def test_without_a_work_store_refs_stay_text(tmp_path, monkeypatch, work_id):
    monkeypatch.delenv("TRAJECTA_WORK_ROOT", raising=False)
    mem = IdentityMemory(load_profile("example"), tmp_path / "m.sqlite3")
    mem.bootstrap()
    mem.log_phase("pp", title="Linked", summary="to work", work_refs=[work_id], cues=["linked"])
    item = next(i for i in mem.retrieve("linked", track=False)["items"] if i["record_id"] == "phase:pp")
    assert item["work"] == [{"ref": work_id, "resolved": False}]


def test_foreign_schema_fails_closed(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"schema": "other/v9", "work": []}))
    with pytest.raises(WorkStoreError, match="unsupported"):
        WorkStore(tmp_path).work_items()
