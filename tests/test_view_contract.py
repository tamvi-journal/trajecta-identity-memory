"""P21 request-boundary regressions use real loopback sockets and owned stores."""
import http.client
import socket
import threading
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from trajecta_identity import IdentityMemory, load_profile
from trajecta_identity import view

POLICY = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@contextmanager
def running(memory):
    server = ThreadingHTTPServer(("127.0.0.1", 0), view.make_handler(memory))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01})
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(server, method="GET", path="/", headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in headers if headers is not None else [("Host", f"127.0.0.1:{server.server_port}")]:
            connection.putheader(key, value)
        connection.endheaders()
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


@pytest.fixture
def memory(tmp_path):
    mem = IdentityMemory(load_profile("example"), tmp_path / "store.sqlite3", surface="test")
    mem.bootstrap()
    return mem


def unchanged(memory):
    path = Path(memory.db_path)
    return path.read_bytes(), path.stat().st_mtime_ns, sorted(p.name for p in path.parent.iterdir())


def policy(headers):
    for key, value in POLICY.items():
        assert headers[key] == value
    assert "Content-Type" in headers and "Content-Length" in headers


BAD = [
    ("host-evil", [("Host", "evil.example:{port}")], b"forbidden host"),
    ("host-port", [("Host", "127.0.0.1:{other}")], b"forbidden host"),
    ("host-missing", [], b"forbidden host"),
    ("host-duplicate", [("Host", "127.0.0.1:{port}"), ("Host", "127.0.0.1:{port}")], b"forbidden host"),
    ("host-empty-port", [("Host", "127.0.0.1:")], b"forbidden host"),
    ("host-nonnumeric", [("Host", "127.0.0.1:abc")], b"forbidden host"),
    ("host-bracket", [("Host", "[::1")], b"forbidden host"),
    ("origin-evil", [("Origin", "http://evil.example")], b"forbidden origin"),
    ("origin-null", [("Origin", "null")], b"forbidden origin"),
    ("origin-https", [("Origin", "https://127.0.0.1:{port}")], b"forbidden origin"),
    ("origin-port", [("Origin", "http://127.0.0.1:{other}")], b"forbidden origin"),
    ("origin-duplicate", [("Origin", "http://127.0.0.1:{port}"), ("Origin", "http://127.0.0.1:{port}")], b"forbidden origin"),
    ("origin-other-name", [("Origin", "http://localhost:{port}")], b"forbidden origin"),
]


@pytest.mark.parametrize("name,headers,body", BAD, ids=[x[0] for x in BAD])
def test_p21_refusals_are_pure(memory, name, headers, body):
    before = unchanged(memory)
    with running(memory) as server:
        rendered = [(key, val.format(port=server.server_port, other=server.server_port % 65535 + 1))
                    for key, val in headers]
        if name.startswith("origin"):
            rendered.insert(0, ("Host", f"127.0.0.1:{server.server_port}"))
        status, output_headers, output = request(server, headers=rendered)
        assert status == 403
        assert output == body
        assert output_headers["Content-Type"] == "text/plain; charset=utf-8"
        policy(output_headers)
    assert unchanged(memory) == before


@pytest.mark.parametrize("method", ["POST", "DELETE", "PUT", "PATCH", "OPTIONS", "HEAD", "CONNECT", "BREW"])
def test_p21_all_methods_guard_and_do_not_write(memory, method):
    before = unchanged(memory)
    with running(memory) as server:
        status, headers, body = request(server, method, "/api/snapshot", [("Host", "evil.example")])
        assert status == 403
        policy(headers)
        status, headers, body = request(server, method, "/api/snapshot")
        assert status >= 400
        policy(headers)
    assert unchanged(memory) == before


@pytest.mark.parametrize("host,origin", [("127.0.0.1", None), ("127.0.0.1", "http://127.0.0.1"),
                                       ("LOCALHOST", "HTTP://LOCALHOST"), ("localhost", None)])
def test_p21_allowed_own_origin(memory, host, origin):
    with running(memory) as server:
        headers = [("Host", f"{host}:{server.server_port}")]
        if origin:
            headers.append(("Origin", f"{origin}:{server.server_port}"))
        status, result, body = request(server, headers=headers)
        assert status == 200
        policy(result)


def test_p21_404_and_500_policy_and_purity(memory, monkeypatch):
    before = unchanged(memory)
    with running(memory) as server:
        status, headers, body = request(server, path="/missing")
        assert (status, body) == (404, b"not found")
        assert headers["Content-Type"] == "text/plain"
        policy(headers)
        def fail(_):
            raise RuntimeError("synthetic handler failure")
        monkeypatch.setattr(view, "snapshot", fail)
        status, headers, body = request(server, path="/api/snapshot")
        assert status == 500
        policy(headers)
    assert unchanged(memory) == before


def test_p21_ipv6_bound_port_and_printed_url(memory, monkeypatch, capsys):
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            probe.bind(("::1", 0))
    except OSError as exc:
        pytest.skip(f"IPv6 loopback unavailable: {exc}")
    results = []
    def one_request(server):
        assert server.address_family == socket.AF_INET6
        port = server.server_port
        def client():
            connection = http.client.HTTPConnection("::1", port, timeout=5)
            try:
                connection.request("GET", "/", headers={"Host": f"[::1]:{port}"})
                response = connection.getresponse()
                results.append((port, response.status, dict(response.getheaders()), response.read()))
            finally:
                connection.close()
        thread = threading.Thread(target=client)
        thread.start()
        server.handle_request()
        thread.join(6)
        assert not thread.is_alive()
    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", one_request)
    before = unchanged(memory)
    view.serve(memory, host="::1", port=0, open_browser=False)
    assert results and results[0][1] == 200
    policy(results[0][2])
    assert f"http://[::1]:{results[0][0]}/" in capsys.readouterr().out
    assert unchanged(memory) == before
