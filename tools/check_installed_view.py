"""Build/install acceptance: run only an installed wheel outside the checkout."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]


def check(wheel):
    with tempfile.TemporaryDirectory(prefix="installed-view-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel.resolve())],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        env = dict(os.environ, TRAJECTA_IDENTITY_DATA_DIR=str(root / "data"),
                   TRAJECTA_IDENTITY_PROFILES=str(root / "profiles"), PYTHONUNBUFFERED="1",
                   PYTHONIOENCODING="utf-8")
        env.pop("PYTHONPATH", None)
        cwd = ROOT.parent
        assert cwd != ROOT and ROOT not in cwd.parents
        location = subprocess.check_output([str(python), "-c",
            "import trajecta_identity; print(trajecta_identity.__file__)"], cwd=cwd, env=env).decode().strip()
        # Framework Python on macOS resolves /var through /private/var. Verify
        # actual filesystem ownership, including aliases, not lexical spelling.
        assert Path(location).resolve().is_relative_to(environment.resolve()), (location, str(environment))
        process = subprocess.Popen([str(python), "-m", "trajecta_identity.cli", "--profile", "example",
                                    "view", "--port", "0", "--no-browser"],
                                   cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            line = process.stdout.readline()
            match = re.search(rb"http://127\.0\.0\.1:(\d+)/", line)
            assert match, (line, process.stderr.read() if process.poll() is not None else b"")
            # Ignore machine proxy configuration for this local fixture.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(match.group().decode(), timeout=10) as response:
                assert response.status == 200
                assert response.read() == (ROOT / "trajecta_identity/assets/view.html").read_bytes()
            print("installed wheel: external cwd GET / equals canonical bytes")
        finally:
            process.terminate()
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    check(parser.parse_args().wheel)
