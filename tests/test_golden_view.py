"""Replay the frozen Python HTTP oracle on copies, never on corpus stores."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from tools.golden.generate import clock_context, dump_database
from tools.golden_view.generate import (
    HEADERS, ROOT, in_directory, inventory, memory, request, request_cases, running,
)

CORPUS = ROOT / "spec/golden-view-v1"
SCENARIOS = sorted(p.name for p in CORPUS.iterdir() if p.is_dir()) if CORPUS.exists() else []


def test_view_manifest_covers_every_file_and_pinned_table():
    manifest = json.loads((CORPUS / "MANIFEST.json").read_bytes())
    actual = {p.relative_to(CORPUS).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in CORPUS.rglob("*") if p.is_file() and p.name != "MANIFEST.json"}
    actual.update({"tables/" + p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (ROOT / "memory_core/tables").glob("*.json")})
    assert actual == manifest["files"]
    assert manifest["oracle_base_commit"] == "fc2a2de"
    assert manifest["sqlite"] == "3.40.1"
    assert manifest["unicode"] == "14.0.0"
    expected = {"r0-" + p.parent.name for p in (ROOT / "spec/golden").glob("*/store.sqlite3")}
    assert set(SCENARIOS) == expected | {"view-fixture", "legacy-v4", "g15-disappear"}


def compare(case, actual, body, directory):
    expected = case["response"]
    mode = case.get("comparison", "exact")
    assert set(actual["headers"]) == set(HEADERS)
    if mode == "G16":
        assert actual["status"] >= 400
    else:
        assert actual["status"] == expected["status"]
    for key in HEADERS:
        if mode in ("G16", "handler-error") and key == "Content-Length":
            assert actual["headers"][key] == str(len(body))
        else:
            assert actual["headers"][key] == expected["headers"][key]
    if mode == "exact":
        assert body == (directory / expected["body"]).read_bytes(), case["label"]
    else:
        assert mode in ("G16", "handler-error")  # Only the spec's explicit non-contract bodies.


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_view_corpus_replay_is_pure(scenario, tmp_path):
    directory = CORPUS / scenario
    original = inventory(directory)
    shutil.copyfile(directory / "store.sqlite3", tmp_path / "store.sqlite3")
    with in_directory(tmp_path):
        mem = memory()
        cases = [json.loads(line) for line in (directory / "cases.jsonl").read_bytes().splitlines()]
        if scenario == "g15-disappear":
            with running(mem) as server:
                Path("store.sqlite3").unlink()
                with clock_context():
                    actual, body = request(server, cases[0])
            compare(cases[0], actual, body, directory)
            assert dump_database(Path("store.sqlite3")) == json.loads((directory / "dump.json").read_bytes())
            result = Path("store.sqlite3").read_bytes()
            Path("store.sqlite3").unlink()
            with clock_context():
                memory().bootstrap()
            assert Path("store.sqlite3").read_bytes() == result
        else:
            assert [c["label"] for c in cases] == [c["label"] for c in request_cases()]
            before = inventory(tmp_path)
            with running(mem) as server:
                for case in cases:
                    with clock_context():
                        actual, body = request(server, case)
                    compare(case, actual, body, directory)
                    assert case["store_unchanged"] is True
                    assert inventory(tmp_path) == before, case["label"]
    assert inventory(directory) == original


@pytest.mark.parametrize("cue,expected", [
    ("", ""), ("%20%09%1C%E3%80%80", ""), ("a&cue=b", "a"),
    ("first+light", "first light"), ("%", "%"), ("%G1", "%G1"),
    ("%E2%82", "\ufffd"), ("%FF", "\ufffd"), ("%C0%AF", "\ufffd\ufffd"),
    ("%ED%A0%80", "\ufffd\ufffd\ufffd"),
    ("%F0%9F%98%80" * 2001, "😀" * 2000),
], ids=["empty", "unicode-whitespace", "first-duplicate", "plus", "percent", "malformed",
         "truncated", "ff", "overlong", "surrogate", "astral-boundary"])
def test_actual_handler_cue_boundary(cue, expected, tmp_path, monkeypatch):
    # Capture the value arriving at the public retrieval API, not a second decoder implementation.
    with in_directory(tmp_path):
        mem = memory()
        received = []
        def retrieve(value, *, track):
            assert track is False
            received.append(value)
            return {"packet": "synthetic", "items": []}
        monkeypatch.setattr(mem, "retrieve", retrieve)
        with running(mem) as server:
            actual, body = request(server, {"method": "GET", "path": "/api/retrieve?cue=" + cue})
        assert actual["status"] == 200
        assert received == ([expected] if expected else [])
        assert not Path("store.sqlite3").exists()


def test_view_fixture_has_the_required_product_history_and_both_recall_outcomes():
    fixture = CORPUS / "view-fixture"
    snapshot = json.loads((fixture / "responses/snapshot.body").read_bytes())
    assert snapshot["core"]["revisions"] == 2
    assert snapshot["open_core_proposals"] and snapshot["open_loops"]
    assert {row["record_id"] for row in snapshot["timeline"]} >= {"phase:one", "phase:two"}
    matching = json.loads((fixture / "responses/cue-matching.body").read_bytes())
    assert "First phase" in matching["packet"]
    assert matching["items"]
    # Pinned core can still be recalled for an unrelated cue; the no-hit case uses an R0 raw store.
    outcomes = []
    for directory in CORPUS.iterdir():
        if not directory.is_dir() or directory.name == "g15-disappear":
            continue
        case = next(json.loads(line) for line in (directory / "cases.jsonl").read_bytes().splitlines()
                    if json.loads(line)["label"] == "cue-nonmatching")
        if case["response"]["status"] == 200:
            outcomes.append(json.loads((directory / case["response"]["body"]).read_bytes()))
    assert any(value.get("items") == [] for value in outcomes)
