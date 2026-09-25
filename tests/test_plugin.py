import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from trajecta_identity.plugin import build_plugin, plugin_files


class PluginBuildTest(unittest.TestCase):
    def test_layout_has_no_bin_and_launcher_in_scripts(self):
        for target in ("posix", "windows"):
            files = plugin_files("example", target=target, env={"TRAJECTA_IDENTITY_DATA_DIR": "~/x"})
            tops = {name.split("/", 1)[0] for name in files}
            self.assertNotIn("bin", tops)
            self.assertIn("scripts", tops)
            mcp = json.loads(files[".mcp.json"])
            server = mcp["mcpServers"]["trajecta-identity-example"]
            self.assertTrue(server["args"][0].startswith("${CLAUDE_PLUGIN_ROOT}/scripts/"))
            self.assertIn("trajecta_identity/mcp_server.py", files)
            self.assertIn("memory_core/__init__.py", files)
            self.assertIn("skills/identity-continuity/SKILL.md", files)
            self.assertFalse(any("__pycache__" in name for name in files))

    def test_build_is_atomic_and_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = build_plugin(tmp, "example", target="posix", house="~/house")
            data_one = Path(first["plugin"]).read_bytes()
            second = build_plugin(tmp, "example", target="posix", house="~/house")
            self.assertEqual(data_one, Path(second["plugin"]).read_bytes())
            self.assertEqual(sorted(os.listdir(tmp)), ["trajecta-identity-example.plugin"])
            self.assertEqual(first["env"]["TRAJECTA_IDENTITY_DATA_DIR"], "~/house/house-data/identity")

    @unittest.skipIf(os.name == "nt", "posix launcher")
    def test_posix_launcher_starts_the_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            report = build_plugin(tmp, "example", target="posix", data_dir=str(data))
            root = Path(tmp) / "unpacked"
            with zipfile.ZipFile(report["plugin"]) as archive:
                archive.extractall(root)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("TRAJECTA_", "PYTHONPATH"))}
            env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
            requests = "\n".join(json.dumps(r) for r in (
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "identity_status", "arguments": {}}},
            )) + "\n"
            out = subprocess.run(
                ["/bin/sh", str(root / "scripts" / "identity.sh")],
                input=requests, capture_output=True, text=True, env=env, timeout=60,
            )
            lines = [json.loads(line) for line in out.stdout.splitlines() if line.strip()]
            self.assertEqual(len(lines), 2, out.stderr)
            status = json.loads(lines[1]["result"]["content"][0]["text"])
            self.assertEqual(status["profile"], "example")
            self.assertTrue(status["db"].startswith(str(data)))


if __name__ == "__main__":
    unittest.main()
