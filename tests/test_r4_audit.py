"""The audit refuses payload drift, unrelated MANIFEST edits and false digest claims."""
import json
import pytest
from tools.r4.audit import compare, sha, ARCHIVE_OLD, ARCHIVE_NEW

TABLES = {"tables/identity-v1.json", "tables/text-norm-v2.json", "tables/version-sensitive.json"}
TABLE_BYTES = b"frozen table\n"


def fixture():
    source = b"archived unchanged source"
    payload = {"case/dump.json": b"{}\n", "case/text.txt": b"frozen\n"}
    old = {"files": {path: sha(raw) for path, raw in payload.items()},
           "oracle_sources": {ARCHIVE_OLD: sha(source)}, "oracle_commit": "frozen"}
    old["files"].update({path: sha(TABLE_BYTES) for path in TABLES})
    new = {**old, "oracle_sources": {ARCHIVE_NEW: sha(source)}}
    return (dict(payload, **{"MANIFEST.json": (json.dumps(old, sort_keys=True, separators=(",", ":")) + "\n").encode()}),
            dict(payload, **{"MANIFEST.json": (json.dumps(new, sort_keys=True, separators=(",", ":")) + "\n").encode()}), source)


def test_exact_archive_rekey_is_proven():
    old, new, source = fixture()
    proof = compare("golden-mcp-v1", old, new, lambda _: source, lambda _: source, lambda _: TABLE_BYTES)
    assert proof["unchanged_payload_files"] == 2
    assert proof["manifest_changes"] == [{"field": ["oracle_sources", ARCHIVE_OLD],
                                          "rekey": ARCHIVE_NEW, "sha256": sha(source)}]


@pytest.mark.parametrize("mutation", ["payload", "manifest-value", "manifest-spacing", "manifest-map-spacing", "manifest-map-order", "source-bytes", "source-digest", "source-key", "inventory"])
def test_all_other_drift_fails_closed(mutation):
    old, new, source = fixture()
    read_new = lambda _: source
    if mutation == "payload": new["case/dump.json"] += b" "
    elif mutation == "manifest-value": new["MANIFEST.json"] = new["MANIFEST.json"].replace(b"frozen", b"changed")
    elif mutation == "manifest-spacing": new["MANIFEST.json"] += b" "
    elif mutation == "manifest-map-spacing":
        new["MANIFEST.json"] = new["MANIFEST.json"].replace(b'"case/dump.json":', b'"case/dump.json": ')
    elif mutation == "manifest-map-order":
        value = json.loads(new["MANIFEST.json"])
        value["files"] = dict(reversed(list(value["files"].items())))
        new["MANIFEST.json"] = (json.dumps(value, separators=(",", ":")) + "\n").encode()
    elif mutation == "source-bytes": read_new = lambda _: source + b" "
    elif mutation == "source-digest": new["MANIFEST.json"] = new["MANIFEST.json"].replace(sha(source).encode(), b"0" * 64)
    elif mutation == "source-key": new["MANIFEST.json"] = new["MANIFEST.json"].replace(ARCHIVE_NEW.encode(), b"tools/archive/other.py")
    else: new["case/new.json"] = b"{}\n"
    with pytest.raises(AssertionError):
        compare("golden-mcp-v1", old, new, lambda _: source, read_new, lambda _: TABLE_BYTES)


@pytest.mark.parametrize("mutation", ["missing-table", "extra-table"])
def test_canonical_manifest_external_table_inventory_is_pinned(mutation):
    old, new, source = fixture()
    value = json.loads(new["MANIFEST.json"])
    if mutation == "missing-table":
        del value["files"]["tables/version-sensitive.json"]
    else:
        value["files"]["tables/extra-valid-looking.json"] = sha(TABLE_BYTES)
    # Preserve the canonical writer and valid digests: only the key inventory is wrong.
    new["MANIFEST.json"] = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with pytest.raises(AssertionError):
        compare("golden-mcp-v1", old, new, lambda _: source, lambda _: source, lambda _: TABLE_BYTES)
