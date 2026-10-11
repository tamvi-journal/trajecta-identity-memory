import hashlib
from pathlib import Path

from test_view_contract import running, request, memory

ROOT = Path(__file__).resolve().parents[1]
PAGE_SHA256 = "e2d77258d70875102717490ad76390ee29010146becd45824202d21c5323d913"


def test_shared_asset_matches_frozen_page_bytes():
    canonical = (ROOT / "trajecta_identity/assets/view.html").read_bytes()
    copy = (ROOT / "node/assets/view.html").read_bytes()
    assert canonical == copy
    assert hashlib.sha256(canonical).hexdigest() == PAGE_SHA256
    assert hashlib.sha256(copy).hexdigest() == PAGE_SHA256


def test_get_serves_canonical_asset(memory):
    with running(memory) as server:
        for path in ("/", "/index.html"):
            status, headers, body = request(server, path=path)
            assert status == 200
            assert body == (ROOT / "trajecta_identity/assets/view.html").read_bytes()
