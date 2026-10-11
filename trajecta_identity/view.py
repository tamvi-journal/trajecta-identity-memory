"""A local, read-only web view of an agent's identity memory.

`trajecta-identity view` serves one page on 127.0.0.1. Nothing on the page can
write: recall from the page never changes activation.
"""

from __future__ import annotations

import json
import socket
import webbrowser
from importlib.resources import files
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .activation import state_of
from .identity import PINNED, IdentityMemory


def snapshot(memory: IdentityMemory) -> dict[str, Any]:
    if memory.store.schema_info()["state"] == "uninitialized":
        memory.bootstrap()
    rows = [row for row in memory.store.current_view() if row["domain"] != "anchor"]
    nodes = []
    for row in rows:
        nodes.append({
            "record_id": row["record_id"],
            "domain": row["domain"],
            "title": row["title"],
            "summary": row["summary"],
            "revision": row["revision_number"],
            "state": state_of(row, memory.activation, PINNED),
            "accessibility": round(float(row["accessibility"]), 3),
            "access_count": row["access_count"],
        })
    nodes.sort(key=lambda node: (-node["accessibility"], node["record_id"]))
    relations = [
        {"from": row["from_record_id"], "type": row["relation_type"], "to": row["to_record_id"]}
        for row in memory.store.active_relation_rows()
        if not row["to_record_id"].startswith("anchor:")
    ]
    core = memory.store.current_view("core")
    return {
        "profile": memory.profile.name,
        "agent": memory.profile.agent,
        "owner": memory.profile.owner,
        "status": memory.status(),
        "core": {
            "title": core[0]["title"],
            "summary": core[0]["summary"],
            "detail": json.loads(core[0]["content"]),
            "revisions": len(memory.store.historical_view("core")),
        } if core else None,
        "timeline": memory.timeline(200),
        "nodes": nodes,
        "relations": relations,
        "open_core_proposals": memory.open_core_proposals(),
        "open_discussions": memory.open_discussions(),
        "open_loops": memory.open_loops(),
    }


PAGE = files("trajecta_identity").joinpath("assets/view.html").read_bytes()


def make_handler(memory: IdentityMemory):
    class Handler(BaseHTTPRequestHandler):
        def parse_request(self):
            if not super().parse_request():
                return False
            port = self.server.server_port
            local = "[::1]" if self.server.address_family == socket.AF_INET6 else "127.0.0.1"
            hosts = self.headers.get_all("Host", [])
            ascii_lower = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
            if len(hosts) != 1 or hosts[0].translate(ascii_lower) not in (f"{local}:{port}", f"localhost:{port}"):
                self._send(HTTPStatus.FORBIDDEN, b"forbidden host", "text/plain; charset=utf-8")
                return False
            origins = self.headers.get_all("Origin", [])
            if origins and (len(origins) != 1 or origins[0].translate(ascii_lower) != ("http://" + hosts[0]).translate(ascii_lower)):
                self._send(HTTPStatus.FORBIDDEN, b"forbidden origin", "text/plain; charset=utf-8")
                return False
            return True

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def send_error(self, code, message=None, explain=None):
            self._send(code, (message or self.responses.get(code, ("error",))[0]).encode("utf-8"), "text/plain")

        def _json(self, value: Any) -> None:
            self._send(HTTPStatus.OK, json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"),
                       "application/json; charset=utf-8")

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            try:
                if url.path in ("/", "/index.html"):
                    self._send(HTTPStatus.OK, PAGE, "text/html; charset=utf-8")
                elif url.path == "/api/snapshot":
                    self._json(snapshot(memory))
                elif url.path == "/api/retrieve":
                    cue = (parse_qs(url.query).get("cue") or [""])[0].strip()[:2000]
                    if not cue:
                        self._json({"packet": ""})
                    else:
                        result = memory.retrieve(cue, track=False)
                        self._json({"packet": result["packet"], "items": result["items"]})
                else:
                    self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            except Exception as error:  # shown to the local viewer only
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, str(error).encode("utf-8"), "text/plain")

        def log_message(self, *args):
            pass

    return Handler


class IPv6HTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def serve(memory: IdentityMemory, *, host: str = "127.0.0.1", port: int = 8767, open_browser: bool = True):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("the memory view only binds to localhost")
    server_class = IPv6HTTPServer if host == "::1" else ThreadingHTTPServer
    server = server_class((host, port), make_handler(memory))
    authority = "[::1]" if host == "::1" else host
    url = f"http://{authority}:{server.server_port}/"
    print(f"Identity memory view for {memory.profile.agent}: {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
