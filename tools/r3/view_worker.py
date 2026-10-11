"""Test-only HTTP adapter: the unchanged Python handler with per-request clocks."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.golden.generate import clock_context
from trajecta_identity import IdentityMemory, load_profile
from trajecta_identity.view import make_handler

memory = IdentityMemory(load_profile(ROOT / "trajecta_identity/profiles/example"), Path("store.sqlite3"), surface="view")
base = make_handler(memory)


class Handler(base):
    def handle_one_request(self):
        with clock_context():
            return super().handle_one_request()


with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
    print(server.server_port, flush=True)
    server.serve_forever()
