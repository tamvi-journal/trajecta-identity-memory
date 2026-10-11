"""R4 audit: named case replacements, digest-only provenance and the S2 exact re-key."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.r3.fixture_headers import json_spans

BASE = "0b1a45c"
CORPORA = ("golden", "golden-authority-v2", "golden-writes-v5", "golden-mcp-v1",
           "golden-cli-v1", "golden-view-v1")
REMOVED = {"resolve-overwrite-json", "resolve-overwrite-url", "migration-dry-parent"}
ADDED = {"resolve-p25-" + mode for mode in (
    "conflict-json", "replace-json", "identical-json", "conflict-url", "replace-url",
    "identical-url", "identical-nan", "conflict-nan", "conflict-format")} | {
    "migration-p26-missing-parent-chain", "migration-p26-concurrent-parent"}
ARCHIVE_OLD = "trajecta_identity/migrate_aml.py"
ARCHIVE_NEW = "tools/archive/migrate_aml.py"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inventory(path):
    return {p.relative_to(path).as_posix(): p.read_bytes()
            for p in path.rglob("*") if p.is_file()}


def mask(raw, spans, paths):
    for path in sorted(paths, key=lambda p: spans[p][0], reverse=True):
        a, b = spans[path]
        raw = raw[:a] + b'"<validated-digest-fields>"' + raw[b:]
    return raw


def compare(name, old, new, old_source, new_source, table_source):
    allowed_old = REMOVED if name == "golden-cli-v1" else set()
    allowed_new = ADDED if name == "golden-cli-v1" else set()
    old_names = {p for p in old if p.split("/")[0] not in allowed_old}
    new_names = {p for p in new if p.split("/")[0] not in allowed_new}
    assert old_names == new_names, (name, "unexpected corpus inventory change", old_names ^ new_names)
    if name == "golden-cli-v1":
        assert {p.split("/")[0] for p in old} & REMOVED == REMOVED
        assert not ({p.split("/")[0] for p in new} & REMOVED)
        assert {p.split("/")[0] for p in new} & ADDED == ADDED
    for path in sorted(old_names - {"MANIFEST.json"}):
        assert old[path] == new[path], (name, "unpermitted payload change", path)
    a, b = old["MANIFEST.json"], new["MANIFEST.json"]
    left, left_spans = json_spans(a)
    right, right_spans = json_spans(b)
    # Both historical and generated MANIFESTs use this exact deterministic writer.
    # Authenticate it before masking maps: their key order/format cannot hide drift.
    for raw, value in ((a, left), (b, right)):
        canonical = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")) + "\n").encode("utf-8")
        assert raw == canonical, (name, "manifest byte format/order changed")
    assert left.keys() == right.keys(), (name, "manifest top-level keys")
    changes = []
    fields = [("files",), ("oracle_sources",)]
    # First authenticate both complete payload inventories, including external tables.
    for manifest, payload in ((left, old), (right, new)):
        assert set(manifest["files"]) == (set(payload) - {"MANIFEST.json"}) | {
            k for k in manifest["files"] if k.startswith("tables/")}
        for path, digest in manifest["files"].items():
            raw = table_source(path) if path.startswith("tables/") else payload[path]
            assert sha(raw) == digest, (name, "payload digest does not match", path)
    old_sources, new_sources = left["oracle_sources"], right["oracle_sources"]
    expected_keys = set(old_sources)
    if ARCHIVE_OLD in expected_keys:
        expected_keys.remove(ARCHIVE_OLD)
        expected_keys.add(ARCHIVE_NEW)
        assert ARCHIVE_NEW in new_sources, "missing archived source key"
        assert old_source(ARCHIVE_OLD) == new_source(ARCHIVE_NEW), "archived source bytes changed"
        assert old_sources[ARCHIVE_OLD] == new_sources[ARCHIVE_NEW], "archive digest changed"
        changes.append({"field": ["oracle_sources", ARCHIVE_OLD], "rekey": ARCHIVE_NEW,
                        "sha256": new_sources[ARCHIVE_NEW]})
    assert set(new_sources) == expected_keys, (name, "unexpected source key changes")
    for path, digest in old_sources.items():
        assert sha(old_source(path)) == digest, (name, "old source digest", path)
    for path, digest in new_sources.items():
        assert sha(new_source(path)) == digest, (name, "new source digest", path)
        previous = old_sources.get(path)
        if previous is not None and digest != previous:
            changes.append({"field": ["oracle_sources", path], "old_sha256": previous, "new_sha256": digest})
    if "oracle_source_sha256" in left:
        fields.append(("oracle_source_sha256",))
        for manifest in (left, right):
            listing = "".join(f"{path}\0{digest}\n" for path, digest in sorted(manifest["oracle_sources"].items()))
            assert sha(listing.encode()) == manifest["oracle_source_sha256"]
        if left["oracle_source_sha256"] != right["oracle_source_sha256"]:
            changes.append({"field": ["oracle_source_sha256"],
                            "old_sha256": left["oracle_source_sha256"], "new_sha256": right["oracle_source_sha256"]})
    for path in set(left["files"]) & set(right["files"]):
        if left["files"][path] != right["files"][path]:
            assert path.split("/")[0] in allowed_new, (name, "unpermitted file digest change", path)
    assert mask(a, left_spans, fields) == mask(b, right_spans, fields), (name, "non-digest manifest bytes changed")
    return {"corpus": name, "unchanged_payload_files": len(old_names) - 1,
            "removed_cases": sorted(allowed_old), "added_cases": sorted(allowed_new),
            "manifest_changes": changes}


def old_bytes(path):
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT)


def audit(output):
    proof = []
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE, "--", "spec"], cwd=ROOT).decode().splitlines()
    for name in CORPORA:
        prefix = "spec/" + name + "/"
        old = {p[len(prefix):]: old_bytes(p) for p in paths if p.startswith(prefix)}
        proof.append(compare(name, old, inventory(output / name), old_bytes,
                             lambda p: (ROOT / p).read_bytes(),
                             lambda p: (ROOT / "memory_core" / p).read_bytes()))
    return {"base": BASE, "law": "R4 P25/P26 named replacements; Aux S2 source re-key",
            "corpora": proof}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "spec")
    args = parser.parse_args()
    print(json.dumps(audit(args.output), ensure_ascii=False, sort_keys=True, indent=2))
