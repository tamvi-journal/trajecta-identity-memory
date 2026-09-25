from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

from trajecta_identity import cli
from trajecta_identity.recipe import last_profile, resolve

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "trajecta_identity" / "profiles" / "example" / "profile.json"


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAJECTA_IDENTITY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("TRAJECTA_IDENTITY_PROFILE", raising=False)
    monkeypatch.delenv("TRAJECTA_IDENTITY_PROFILES", raising=False)
    return tmp_path / "data"


def custom(name: str) -> dict:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["name"] = name
    data["packet_title"] = name.upper()
    return data


def test_default_is_example_then_last_used(data):
    assert resolve().name == "example"
    assert resolve("researcher").name == "researcher"
    assert last_profile() == "researcher"
    assert resolve().name == "researcher"


def test_bundled_profiles_all_load(data):
    for name in ("example", "companion", "researcher"):
        assert resolve(name, remember_choice=False).name == name


def test_json_file_is_installed_then_usable_by_name(data, tmp_path):
    source = tmp_path / "mine.json"
    source.write_text(json.dumps(custom("mine")), encoding="utf-8")
    assert resolve(str(source)).packet_title == "MINE"
    assert (data / "profiles" / "mine" / "profile.json").is_file()
    source.unlink()
    assert resolve("mine").packet_title == "MINE"


def test_invalid_recipe_is_rejected(data, tmp_path):
    broken = custom("broken")
    del broken["core"]["falsifier"]
    source = tmp_path / "broken.json"
    source.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ValueError, match="falsifier"):
        resolve(str(source))
    assert not (data / "profiles" / "broken").exists()


def test_url_recipe_is_fetched_and_cached(data):
    body = json.dumps(custom("remote")).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/profile.json"
        assert resolve(url).packet_title == "REMOTE"
    finally:
        server.shutdown()
        server.server_close()
    assert resolve("remote", remember_choice=False).packet_title == "REMOTE"


def test_setup_prints_mcp_config(data, capsys):
    cli.main(["-p", "companion", "setup"])
    config = json.loads(capsys.readouterr().out)
    server = config["mcpServers"]["trajecta-identity-companion"]
    assert server["args"][-2:] == ["--profile", "companion"]
    assert (data / "companion.sqlite3").is_file()


def test_profiles_command_lists_bundled(data, capsys):
    cli.main(["profiles"])
    names = {item["name"] for item in json.loads(capsys.readouterr().out)["profiles"]}
    assert {"example", "companion", "researcher"} <= names
    assert "agent-name" not in names  # _template is hidden
