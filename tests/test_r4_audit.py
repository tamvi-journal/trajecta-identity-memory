"""The audit refuses payload drift, unrelated MANIFEST edits and false digest claims."""
import json
import pytest
from tools.r4.audit import compare, sha, ARCHIVE_OLD, ARCHIVE_NEW


def fixture():
    source = b"archived unchanged source"
    payload = {"case/dump.json": b"{}\n"}
    old = {"files": {"case/dump.json": sha(payload["case/dump.json"])},
           "oracle_sources": {ARCHIVE_OLD: sha(source)}, "oracle_commit": "frozen"}
    new = {**old, "oracle_sources": {ARCHIVE_NEW: sha(source)}}
    return (dict(payload, **{"MANIFEST.json": (json.dumps(old, sort_keys=True) + "\n").encode()}),
            dict(payload, **{"MANIFEST.json": (json.dumps(new, sort_keys=True) + "\n").encode()}), source)


def test_exact_archive_rekey_is_proven():
    old, new, source = fixture()
    proof = compare("golden-mcp-v1", old, new, lambda _: source, lambda _: source, lambda _: b"")
    assert proof["unchanged_payload_files"] == 1
    assert proof["manifest_changes"] == [{"field": ["oracle_sources", ARCHIVE_OLD],
                                          "rekey": ARCHIVE_NEW, "sha256": sha(source)}]


@pytest.mark.parametrize("mutation", ["payload", "manifest-value", "manifest-spacing", "source-bytes", "source-digest", "source-key", "inventory"])
def test_all_other_drift_fails_closed(mutation):
    old, new, source = fixture()
    read_new = lambda _: source
    if mutation == "payload": new["case/dump.json"] += b" "
    elif mutation == "manifest-value": new["MANIFEST.json"] = new["MANIFEST.json"].replace(b"frozen", b"changed")
    elif mutation == "manifest-spacing": new["MANIFEST.json"] += b" "
    elif mutation == "source-bytes": read_new = lambda _: source + b" "
    elif mutation == "source-digest": new["MANIFEST.json"] = new["MANIFEST.json"].replace(sha(source).encode(), b"0" * 64)
    elif mutation == "source-key": new["MANIFEST.json"] = new["MANIFEST.json"].replace(ARCHIVE_NEW.encode(), b"tools/archive/other.py")
    else: new["case/new.json"] = b"{}\n"
    with pytest.raises(AssertionError):
        compare("golden-mcp-v1", old, new, lambda _: source, read_new, lambda _: b"")
