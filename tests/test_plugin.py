import json
import errno
import io
import os
import ntpath
import runpy
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from trajecta_identity.plugin import build_plugin, plugin_files
import trajecta_identity.plugin as plugin


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

    def test_k2_failed_cross_volume_copy_leaves_no_partial_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "memory.plugin"

            def partial_copy(source, destination):
                Path(destination).write_bytes(b"partial archive")
                raise OSError(errno.EIO, "synthetic interrupted copy")

            with patch.object(plugin.os, "replace", side_effect=OSError(errno.EXDEV, "synthetic cross volume")):
                with patch.object(plugin.shutil, "copyfile", side_effect=partial_copy):
                    with self.assertRaises(OSError):
                        build_plugin(target, "example", target="posix")
            self.assertFalse(target.exists(), "K2: a failed build must leave no partial .plugin")

    def test_k2_failed_cross_volume_copy_preserves_existing_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "memory.plugin"
            build_plugin(target, "example", target="posix")
            good = target.read_bytes()

            def partial_copy(source, destination):
                Path(destination).write_bytes(b"partial archive")
                raise OSError(errno.EIO, "synthetic interrupted copy")

            with patch.object(plugin.os, "replace", side_effect=OSError(errno.EXDEV, "synthetic cross volume")):
                with patch.object(plugin.shutil, "copyfile", side_effect=partial_copy):
                    with self.assertRaises(OSError):
                        build_plugin(target, "example", target="posix")
            self.assertEqual(target.read_bytes(), good, "K2: a failed build must preserve an existing good archive")

    def test_k5_windows_launcher_refuses_when_no_suitable_python_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "scripts" / "launch.py"
            script.parent.mkdir()
            script.write_bytes(plugin_files("example", target="windows")["scripts/launch.py"])
            marker = root / "server-started"

            def attempted_start(*args, **kwargs):
                marker.write_text("attempted server start", encoding="utf-8")
                return 42

            stderr = io.StringIO()
            with patch.object(sys, "version_info", (3, 9, 0)):
                with patch.object(plugin.shutil, "which", return_value=None):
                    with patch.object(plugin.subprocess, "call", side_effect=attempted_start):
                        with patch.object(plugin.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
                            with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                                runpy.run_path(str(script), run_name="__main__")
            self.assertEqual(raised.exception.code, 1, "K5: missing suitable runtime must exit 1")
            self.assertRegex(stderr.getvalue(), r"^trajecta-identity-example: need .+\n$")
            self.assertFalse(marker.exists(), "K5: must not attempt to start a half-working server")

    def test_k2_failures_preserve_output_and_original_exception(self):
        for existing in (False, True):
            for failure in ("replace", "write"):
                with self.subTest(existing=existing, failure=failure), tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp) / "memory.plugin"
                    if existing:
                        build_plugin(target, "example", target="posix")
                    before = target.read_bytes() if existing else None
                    original = OSError(errno.EXDEV if failure == "replace" else errno.EIO, failure)
                    if failure == "replace":
                        def fail_replace(source, destination):
                            self.assertEqual(Path(source).parent, target.parent)
                            self.assertTrue(Path(source).name.startswith(".build-"))
                            self.assertEqual(Path(source).suffix, ".plugin")
                            # A complete, closed archive is readable at the commit boundary.
                            with zipfile.ZipFile(source) as archive:
                                self.assertIsNone(archive.testzip())
                            raise original
                        seam = patch.object(plugin.os, "replace", side_effect=fail_replace)
                    else:
                        saved_write = zipfile.ZipFile.writestr
                        count = 0
                        def fail_write(archive, *args, **kwargs):
                            nonlocal count
                            saved_write(archive, *args, **kwargs)
                            count += 1
                            if count == 2:
                                raise original
                        seam = patch.object(zipfile.ZipFile, "writestr", new=fail_write)
                    with seam, self.assertRaises(OSError) as raised:
                        build_plugin(target, "example", target="posix")
                    self.assertIs(raised.exception, original)
                    self.assertEqual(target.read_bytes() if target.exists() else None, before)
                    self.assertEqual(sorted(os.listdir(tmp)), ["memory.plugin"] if existing else [])

    def test_k5_windows_launcher_uses_valid_second_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "scripts" / "launch.py"
            script.parent.mkdir()
            script.write_bytes(plugin_files("example", target="windows", name="custom-server")["scripts/launch.py"])
            probes, starts = [], []
            def probe(argv, **kwargs):
                probes.append(argv)
                return subprocess.CompletedProcess(argv, 0 if argv[0] == "candidate-py" else 1)
            def start(argv, **kwargs):
                starts.append(argv)
                return 0
            with patch.object(plugin.shutil, "which", side_effect=lambda name: "candidate-py" if name == "py" else None):
                with patch.object(plugin.subprocess, "run", side_effect=probe):
                    with patch.object(plugin.subprocess, "call", side_effect=start):
                        with self.assertRaises(SystemExit) as raised:
                            runpy.run_path(str(script), run_name="__main__")
            self.assertEqual(raised.exception.code, 0)
            code = "import sys; sys.exit(sys.version_info < (3, 10))"
            self.assertEqual(probes, [[sys.executable, "-c", code], ["candidate-py", "-3", "-c", code]])
            self.assertEqual(starts, [["candidate-py", "-3", "-m", "trajecta_identity.mcp_server", "--profile", "example"]])

    def test_k3_entry_bytes_timestamps_and_modes_are_reproducible(self):
        for platform in ("posix", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                first = Path(tmp) / "first.plugin"
                second = Path(tmp) / "second.plugin"
                build_plugin(first, "example", target=platform)
                build_plugin(second, "example", target=platform)
                with zipfile.ZipFile(first) as a, zipfile.ZipFile(second) as b:
                    self.assertEqual(a.namelist(), b.namelist())
                    for left, right in zip(a.infolist(), b.infolist()):
                        self.assertEqual(a.read(left), b.read(right))
                        self.assertEqual(left.date_time, (2026, 1, 1, 0, 0, 0))
                        self.assertEqual(right.date_time, left.date_time)
                        mode = 0o755 if left.filename.startswith("scripts/") else 0o644
                        self.assertEqual(left.external_attr >> 16, mode)
                        self.assertEqual(right.external_attr >> 16, mode)

    def test_k4_windows_default_paths_expand_and_existing_value_wins(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                script = root / "scripts" / "launch.py"
                script.parent.mkdir()
                defaults = {"TRAJECTA_IDENTITY_DATA_DIR": "$HOME/data", "TRAJECTA_IDENTITY_PROFILES": "~/profiles"}
                script.write_bytes(plugin_files("example", target="windows", env=defaults)["scripts/launch.py"])
                environment = {"HOME": "Z:/contradictory-home", "USERPROFILE": str(root)}
                if existing:
                    environment["TRAJECTA_IDENTITY_DATA_DIR"] = str(root / "override")
                code = compile(script.read_bytes(), str(script), "exec")
                observed = {}
                def start(argv, *, env):
                    observed.update(env)
                    return 0
                with patch.dict(os.environ, environment, clear=True), patch.object(os, "path", ntpath):
                    with patch.object(plugin.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
                        with patch.object(plugin.subprocess, "call", side_effect=start):
                            with self.assertRaises(SystemExit) as raised:
                                exec(code, {"__file__": str(script), "__name__": "__main__"})
                self.assertEqual(raised.exception.code, 0)
                self.assertEqual(observed["TRAJECTA_IDENTITY_DATA_DIR"],
                                 str(root / "override") if existing else str(root) + "/data")
                self.assertEqual(observed["TRAJECTA_IDENTITY_PROFILES"], str(root) + "/profiles")

    def test_p24_windows_home_rules_with_ntpath(self):
        cases = [
            ("tilde", "~/x", None, {"USERPROFILE": "C:/oracle"}, "C:/oracle/x"),
            ("dollar", "$HOME/x", None, {"USERPROFILE": "C:/oracle"}, "C:/oracle/x"),
            ("drive", "$HOME/x", None, {"HOMEDRIVE": "D:", "HOMEPATH": r"\house"}, r"D:\house/x"),
            ("missing", "~/x", None, {}, None),
            ("preset", "~/x", "$HOME/~verbatim", {}, "$HOME/~verbatim"),
            ("empty", "$HOME/x", "", {"USERPROFILE": "C:/oracle"}, "C:/oracle/x"),
            ("plain", "D:/data", None, {}, "D:/data"),
            ("tilde-user", "~user/x", None, {}, "~user/x"),
            ("backslash", r"~\\x", None, {}, r"~\\x"),
            ("other-var", "$OTHER/x", None, {}, "$OTHER/x"),
        ]
        for name, default, preset, homes, expected in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "launch.py"
                path.write_bytes(plugin_files("example", name="home-server", target="windows",
                                              env={"TRAJECTA_IDENTITY_DATA_DIR": default})["scripts/launch.py"])
                code = compile(path.read_bytes(), str(path), "exec")
                environment = {"HOME": "Z:/contradictory-home", **homes}
                if preset is not None:
                    environment["TRAJECTA_IDENTITY_DATA_DIR"] = preset
                starts = []
                def start(argv, *, env):
                    starts.append(env["TRAJECTA_IDENTITY_DATA_DIR"])
                    return 0
                stderr = io.StringIO()
                with patch.dict(os.environ, environment, clear=True), patch.object(os, "path", ntpath):
                    with patch.object(plugin.shutil, "which", return_value=None):
                        with patch.object(plugin.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
                            with patch.object(plugin.subprocess, "call", side_effect=start):
                                with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                                    exec(code, {"__file__": str(path), "__name__": "__main__"})
                if expected is None:
                    self.assertEqual(raised.exception.code, 1)
                    self.assertEqual(stderr.getvalue(), "home-server: cannot resolve home folder for TRAJECTA_IDENTITY_DATA_DIR\n")
                    self.assertEqual(starts, [])
                else:
                    self.assertEqual(raised.exception.code, 0)
                    self.assertEqual(stderr.getvalue(), "")
                    self.assertEqual(starts, [expected])

    @unittest.skipIf(os.name == "nt", "POSIX launcher")
    def test_k5_posix_refusal_with_unavailable_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.sh"
            path.write_bytes(b"command() { return 1; }\n" + plugin_files("example", target="posix")["scripts/identity.sh"])
            result = subprocess.run(["/bin/sh", str(path)], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, b"trajecta-identity-example: need Python 3.10+\n")
            self.assertEqual(result.stdout, b"")

    @unittest.skipIf(os.name == "nt", "POSIX launcher")
    def test_k4_posix_defaults_empty_and_preset(self):
        for default in ("~/data", "$HOME/data"):
            for preset in (None, "", "override"):
                with self.subTest(default=default, preset=preset), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    home = root / "home"
                    home.mkdir()
                    report = build_plugin(root / "payload.plugin", "example", target="posix", data_dir=default,
                                          profiles_dir=str(root / "profiles"))
                    payload = root / "payload"
                    with zipfile.ZipFile(report["plugin"]) as archive:
                        archive.extractall(payload)
                    env = dict(os.environ, HOME=str(home), TRAJECTA_IDENTITY_PROFILES=str(root / "profiles"))
                    env.pop("TRAJECTA_IDENTITY_DATA_DIR", None)
                    if preset is not None:
                        env["TRAJECTA_IDENTITY_DATA_DIR"] = str(root / "override") if preset else ""
                    request = '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"identity_status","arguments":{}}}\n'
                    result = subprocess.run(["/bin/sh", str(payload / "scripts" / "identity.sh")],
                                            input=request, text=True, capture_output=True, env=env, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    status = json.loads(json.loads(result.stdout)["result"]["content"][0]["text"])
                    want = root / "override" if preset else home / "data"
                    self.assertTrue(status["db"].startswith(str(want) + os.sep), status["db"])

    @unittest.skipIf(os.name == "nt", "posix launcher")
    def test_posix_launcher_starts_the_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            report = build_plugin(tmp, "example", target="posix", data_dir=str(data),
                                  profiles_dir=str(Path(tmp) / "profiles"))
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
