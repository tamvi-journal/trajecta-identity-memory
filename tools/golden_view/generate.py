"""Python HTTP oracle for view-api/v1; all stores and clocks are isolated."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import http.client
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import unicodedata
from urllib.parse import parse_qs, quote, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.golden.generate import START, canonical, clock_context, dump_database, write
from trajecta_identity import IdentityMemory, load_profile
from trajecta_identity.view import make_handler

ORACLE_BASE_COMMIT = "fc2a2de"
HEADERS = ("Content-Type", "Content-Length", "Cache-Control", "X-Content-Type-Options",
           "X-Frame-Options", "Referrer-Policy")
SOURCES = (
    "tools/archive/migrate_aml.py","memory_core/*.py", "memory_core/schema.sql", "trajecta_identity/*.py",
           "trajecta_identity/assets/view.html", "trajecta_identity/profiles/example/profile.json",
           "tools/golden/generate.py", "tools/golden_view/*.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def in_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def memory():
    # A relative public db path makes status() portable without changing output bytes.
    return IdentityMemory(load_profile(ROOT / "trajecta_identity/profiles/example"),
                          Path("store.sqlite3"), surface="view")


class TTY:
    """Test-only human-presence seam; never used by the product."""
    def __init__(self, value):
        self.value = value
    def isatty(self): return True
    def readline(self): return self.value + "\n"
    def write(self, value): return len(value)
    def flush(self): pass


def view_fixture(mem):
    mem.bootstrap()
    mem.log_phase("one", title="First phase", summary="Started", cues=["first light"])
    mem.log_phase("two", title="Second phase", summary="Grew", follows=["phase:one"], open_loop=True)
    proposal = mem.identity_core_propose(reason="runtime moved", phase_context={"model": "m2"})
    terminal = TTY("APPLY " + proposal["proposal_id"].split(":", 1)[1][:12])
    receipt = mem.issue_core_receipt(proposal["proposal_id"], outcome="apply",
                                     stdin=terminal, stdout=terminal)
    mem.identity_core_apply(receipt["receipt_id"])
    mem.identity_core_propose(reason="next reading", phase_context={"model": "m3"})


def request_cases():
    cases = [{"label": label, "method": "GET", "path": path}
             for label, path in (("page", "/"), ("index", "/index.html"),
                                 ("snapshot", "/api/snapshot"), ("missing", "/missing"))]
    cues = [("empty", ""), ("whitespace", quote(" \t\x1c\u3000 ")),
            ("astral-2001", quote("😀" * 2001)), ("percent", "first%20light"),
            ("plus", "first+light"), ("duplicate", "a&cue=b"),
            ("matching", "first%20light"), ("nonmatching", "qzx-nonmatching-7492"),
            ("percent-literal", "%"), ("percent-malformed", "%G1"),
            ("utf8-truncated", "%E2%82"), ("utf8-ff", "%FF"),
            ("utf8-overlong", "%C0%AF"), ("utf8-surrogate", "%ED%A0%80")]
    for label, cue in cues:
        path = "/api/retrieve?cue=" + cue
        decoded = (parse_qs(urlparse(path).query).get("cue") or [""])[0].strip()[:2000]
        cases.append({"label": "cue-" + label, "method": "GET", "path": path,
                      "decoded_cue": decoded})
    bad = [
        ("host-evil", [("Host", "evil.example:{port}")]),
        ("host-port", [("Host", "127.0.0.1:{other}")]),
        ("host-missing", []),
        ("host-duplicate", [("Host", "127.0.0.1:{port}")] * 2),
        ("host-empty-port", [("Host", "127.0.0.1:")]),
        ("host-nonnumeric", [("Host", "127.0.0.1:abc")]),
        ("host-bracket", [("Host", "[::1")]),
        ("origin-evil", [("Origin", "http://evil.example")]),
        ("origin-null", [("Origin", "null")]),
        ("origin-https", [("Origin", "https://127.0.0.1:{port}")]),
        ("origin-port", [("Origin", "http://127.0.0.1:{other}")]),
        ("origin-duplicate", [("Origin", "http://127.0.0.1:{port}")] * 2),
        ("origin-other-name", [("Origin", "http://localhost:{port}")]),
    ]
    for label, headers in bad:
        if label.startswith("origin"):
            headers = [("Host", "127.0.0.1:{port}"), *headers]
        cases.append({"label": label, "method": "GET", "path": "/api/snapshot", "headers": headers})
    for label, headers in (
        ("own-origin", [("Host", "127.0.0.1:{port}"), ("Origin", "http://127.0.0.1:{port}")]),
        ("localhost", [("Host", "LOCALHOST:{port}"), ("Origin", "HTTP://LOCALHOST:{port}")]),
    ):
        cases.append({"label": label, "method": "GET", "path": "/", "headers": headers})
    for method in ("POST", "DELETE"):
        cases.append({"label": method.lower() + "-bad-host", "method": method,
                      "path": "/api/snapshot", "headers": [("Host", "evil.example:{port}")]})
        cases.append({"label": method.lower(), "method": method, "path": "/api/snapshot",
                      "comparison": "G16"})
    return cases


@contextmanager
def running(mem):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(mem))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(server, case):
    port = server.server_port
    headers = case.get("headers", [("Host", "127.0.0.1:{port}")])
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.putrequest(case["method"], case["path"], skip_host=True, skip_accept_encoding=True)
        for key, value in headers:
            connection.putheader(key, value.format(port=port, other=port % 65535 + 1))
        connection.endheaders()
        response = connection.getresponse()
        body = response.read()
        return {"status": response.status, "headers": {key: response.getheader(key) for key in HEADERS}}, body
    finally:
        connection.close()


def inventory(directory):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir() if p.is_file()}


def record_cases(mem, directory):
    cases = []
    before = inventory(Path.cwd())
    with running(mem) as server:
        for case in request_cases():
            with clock_context():
                result, body = request(server, case)
            # Every fixture is initialized before serving; refusal stores must also remain untouched.
            assert inventory(Path.cwd()) == before, case["label"]
            if result["status"] == 500:
                case["comparison"] = "handler-error"
            body_file = "responses/" + case["label"] + ".body"
            (directory / body_file).parent.mkdir(exist_ok=True)
            (directory / body_file).write_bytes(body)
            cases.append({**case, "response": {**result, "body": body_file}, "store_unchanged": True})
    (directory / "cases.jsonl").write_bytes(("".join(canonical(case) + "\n" for case in cases)).encode())


def generate(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixtures = [("r0-" + p.parent.name, p) for p in sorted((ROOT / "spec/golden").glob("*/store.sqlite3"))]
    fixtures.extend([("view-fixture", None), ("legacy-v4", ROOT / "spec/golden/recall/store.sqlite3")])
    for name, source in fixtures:
        directory = output / name
        directory.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="view-oracle-") as temporary, in_directory(temporary):
            path = Path("store.sqlite3")
            mem = memory()
            if source:
                shutil.copyfile(source, path)
                shutil.copyfile(path, directory / "input.sqlite3")
            with clock_context():
                if source is None:
                    # Match tests/test_view.py, including its writer surface.
                    writer = IdentityMemory(mem.profile, path, surface="test")
                    view_fixture(writer)
                    initial = "ready"
                else:
                    initial = mem.store.schema_info()["state"]
                    if initial == "uninitialized":
                        mem.bootstrap()  # The frozen CLI rule, before serving (not read purity).
            shutil.copyfile(path, directory / "store.sqlite3")
            write(directory / "dump.json", dump_database(path))
            write(directory / "fixture.json", {"profile": "example", "surface": "view", "db_path": "store.sqlite3",
                  "initial_state": initial, "bootstrap_before_serve": initial == "uninitialized"})
            record_cases(mem, directory)

    directory = output / "g15-disappear"
    directory.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="view-g15-") as temporary, in_directory(temporary):
        mem = memory()
        with clock_context():
            mem.bootstrap()
        shutil.copyfile("store.sqlite3", directory / "store.sqlite3")
        with running(mem) as server:
            Path("store.sqlite3").unlink()  # Only the owned fixture, while the view is serving.
            with clock_context():
                response, body = request(server, {"method": "GET", "path": "/api/snapshot"})
        result = Path("store.sqlite3").read_bytes()
        shutil.copyfile("store.sqlite3", directory / "result.sqlite3")
        write(directory / "dump.json", dump_database(Path("store.sqlite3")))
        Path("store.sqlite3").unlink()
        with clock_context():
            memory().bootstrap()
        assert Path("store.sqlite3").read_bytes() == result, "G15 differs from direct Python bootstrap"
        (directory / "snapshot.body").write_bytes(body)
        write(directory / "cases.jsonl", {"label": "g15-disappear", "method": "GET", "path": "/api/snapshot",
              "action": "delete-store-while-serving", "store_unchanged": False,
              "response": {**response, "body": "snapshot.body"}})

    sources = {p.relative_to(ROOT).as_posix(): sha(p) for pattern in SOURCES for p in sorted(ROOT.glob(pattern))}
    files = {p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob("*"))
             if p.is_file() and p.name != "MANIFEST.json"}
    for p in sorted((ROOT / "memory_core/tables").glob("*.json")):
        files["tables/" + p.name] = sha(p)
    write(output / "MANIFEST.json", {"schema": "trajecta.golden-view-manifest/v1",
          "oracle_base_commit": ORACLE_BASE_COMMIT, "oracle_semantics": ["P21", "A", "P22", "P23", "P24", "G15", "G16"],
          "oracle_sources": sources, "python": sys.version.split()[0], "unicode": unicodedata.unidata_version,
          "sqlite": sqlite3.sqlite_version, "clock": {"start": START.isoformat(), "reset": "each request",
          "seconds_per_call": 1, "run_id_microseconds_per_call": 1}, "files": dict(sorted(files.items()))})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "spec/golden-view-v1")
    generate(parser.parse_args().output)
