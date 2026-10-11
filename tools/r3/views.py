"""R2e view cross-runtime X: public writer plans, exact HTTP, unchanged store trees."""
from __future__ import annotations

import json
import http.client
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.golden_view.generate import request, request_cases, HEADERS
from tools.r3.common import compare_trees, isolated_env, snapshot
from tools.r3.plans import step
from tools.r3.run import case_for_step, run_case


def cases():
    # Additional oracle checks on the unchanged Python handler, outside the frozen corpus.
    extra = [{"label": path, "method": "GET", "path": path} for path in (
        "http://example.invalid/index.html", "//example.invalid/index.html", "///index.html",
        "/index.html;p#fragment", "/api/retrieve?cue=&cue=first+light")]
    extra += [{"label": "trailing-" + key, "method": "GET", "path": "/api/snapshot",
               "headers": [("Host", "127.0.0.1:{port} ")] if key == "host" else
                          [("Host", "127.0.0.1:{port}"), ("Origin", "http://127.0.0.1:{port} ")]}
              for key in ("host", "origin")]
    extra += [{"label": "expect-" + value, "method": "POST", "path": "/api/snapshot",
               "headers": [("Host", "evil.example"), ("Expect", value)]}
              for value in ("100-continue", "unexpected")]
    extra += [{"label": "brew-bad-host", "method": "BREW", "path": "/api/snapshot",
               "headers": [("Host", "evil.example")]},
              {"label": "brew", "method": "BREW", "path": "/api/snapshot", "comparison": "G16"}]
    # Exact P2 cases only; folded rows have the explicitly allowed G17 asymmetry
    # and are proved independently in each runtime's contract tests.
    extra += [{"label": f"header-budget-{fields}-{evil}-{fragment}", "header_fields": fields,
               "evil_host": evil, "fragment_size": fragment, "expected_status": status}
              for fields, evil, status in ((99, False, 200), (100, False, 431),
                                           (101, False, 431), (100, True, 431))
              for fragment in (0, 3)]
    return request_cases() + extra


def header_request(port, case):
    lines = ["Host: evil.example" if case["evil_host"] else f"Host: 127.0.0.1:{port}"]
    lines.extend(f"X-{i}: value" for i in range(1, case["header_fields"]))
    raw = ("GET / HTTP/1.1\r\n" + "\r\n".join(lines) + "\r\n\r\n").encode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=10) as connection:
        size = case["fragment_size"] or len(raw)
        for offset in range(0, len(raw), size):
            try:
                connection.sendall(raw[offset:offset + size])
            except BrokenPipeError:
                break
            if case["fragment_size"]:
                time.sleep(.001)
        response = http.client.HTTPResponse(connection)
        response.begin()
        body = response.read()
        assert response.status == case["expected_status"]
        if response.status == 431:
            assert body == b"Too many headers"
        return {"status": response.status, "headers": {
            key: response.getheader(key) for key in HEADERS}}, body


def responses(runtime, root):
    env = isolated_env(root)
    command = ([sys.executable, "-B", str(ROOT / "tools/r3/view_worker.py")] if runtime == "py" else
               [shutil.which("node"), "--experimental-strip-types", str(ROOT / "tools/r3/view_worker.ts")])
    process = subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        port = int(process.stdout.readline())
        class Server:
            server_port = port
        before = snapshot(root)
        output = []
        for case in cases():
            actual, body = (header_request(port, case) if "header_fields" in case else request(Server(), case))
            assert set(actual["headers"]) == set(HEADERS)
            assert snapshot(root) == before, (runtime, case["label"], "view changed store tree")
            if case.get("comparison") == "G16":
                assert actual["status"] >= 400
                assert actual["headers"]["Content-Length"] == str(len(body))
                output.append({"label": case["label"], "headers": {
                    k: v for k, v in actual["headers"].items() if k != "Content-Length"}})
            else:
                assert actual["headers"]["Content-Length"] == str(len(body))
                output.append({"label": case["label"], **actual, "body": body})
        assert process.poll() is None
        return output
    finally:
        process.terminate()
        _, stderr = process.communicate(timeout=10)
        assert not stderr, stderr.decode(errors="replace")


def check(parent):
    roots = {runtime: parent / runtime for runtime in ("py", "ts")}
    for root in roots.values(): isolated_env(root)
    actions = [step("py", "cli", "init"),
               step("py", "cli", "log-phase", event_id="view-one", title="First light", summary="Started", open_loop=True),
               step("py", "mcp", "log-phase", event_id="view-two", title="Second phase", summary="Grew"),
               step("py", "mcp", "log-fact", fact_id="view", title="View fact", summary="Synthetic continuity")]
    for index, action in enumerate(actions):
        before = {runtime: snapshot(root) for runtime, root in roots.items()}
        for runtime, root in roots.items():
            result = run_case(runtime, root, case_for_step(root, action, index, {}))
            assert result["exit"] == 0, result
        compare_trees(roots["py"], roots["ts"], before["py"], before["ts"])
    outputs = {(writer, reader): responses(reader, root) for writer, root in roots.items() for reader in ("py", "ts")}
    assert outputs["py", "py"] == outputs["ts", "py"]  # Python on TS-written == Python on Python-written.
    assert outputs["py", "ts"] == outputs["ts", "ts"]  # TS on Python-written == TS on TS-written.
    assert outputs["py", "py"] == outputs["py", "ts"]  # Same store, exact cross-runtime responses.
    # G15: delete an owned store during service; both runtimes must reproduce Python bootstrap.
    # The frozen corpus covers HTTP and dumps; X additionally checks the resulting local files.
    g15 = {}
    g15_roots, g15_before = {}, {}
    for runtime in ("py", "ts"):
        root = parent / ("g15-" + runtime)
        isolated_env(root)
        root.joinpath("store.sqlite3").write_bytes((ROOT / "spec/golden-view-v1/g15-disappear/store.sqlite3").read_bytes())
        g15_roots[runtime] = root
        g15_before[runtime] = snapshot(root)
        command = ([sys.executable, "-B", str(ROOT / "tools/r3/view_worker.py")] if runtime == "py" else
                   [shutil.which("node"), "--experimental-strip-types", str(ROOT / "tools/r3/view_worker.ts")])
        process = subprocess.Popen(command, cwd=root, env=isolated_env(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            port = int(process.stdout.readline())
            root.joinpath("store.sqlite3").unlink()
            class Server:
                server_port = port
            actual, body = request(Server(), {"method": "GET", "path": "/api/snapshot"})
            assert actual["status"] == 200
            g15[runtime] = actual, body
        finally:
            process.terminate()
            _, stderr = process.communicate(timeout=10)
            assert not stderr, stderr
    assert g15["py"] == g15["ts"], "G15 HTTP mismatch"
    compare_trees(g15_roots["py"], g15_roots["ts"], g15_before["py"], g15_before["ts"])
    return {"view_x": "passed", "writer_plans": 2, "public_writes": 8,
            "writer_reader_pairs": 4, "http_cases": len(cases()) * 4, "g15": 2}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="r3-view-x-") as folder:
        print(json.dumps(check(Path(folder).resolve())))
