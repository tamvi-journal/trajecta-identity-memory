"""Build a Claude plugin (.plugin zip) that runs this identity memory.

Install the file once; the MCP server then starts with Claude, with no config
to paste. The plugin carries its own copy of ``trajecta_identity`` and
``memory_core`` (both stdlib-only), the identity-continuity skill, and a small
launcher that finds a Python >= 3.10 by itself (desktop apps often do not see
Homebrew's PATH) and points the server at the chosen data folders.

Layout notes, learned the hard way:

- Launchers live in ``scripts/``. Plugin uploads refuse a top-level ``bin/``.
- The zip is written to a temporary file and moved into place at the end, so a
  failed build never leaves a half-written ``.plugin`` next to a good one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .paths import safe_fs_name

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
VENDORED = ("trajecta_identity", "memory_core")
SKILL = "identity-continuity"
LAUNCHER_DIR = "scripts"
FORBIDDEN_TOP_LEVEL = {"bin"}
SKIP_PARTS = {"__pycache__", ".DS_Store"}

SH_LAUNCHER = """#!/bin/sh
# Start the identity memory MCP server for profile '{profile}'.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then echo "{server}: need Python 3.10+" >&2; exit 1; fi
{exports}
export PYTHONPATH="$ROOT${{PYTHONPATH:+:$PYTHONPATH}}"
export PYTHONIOENCODING=utf-8
exec "$PY" -m trajecta_identity.mcp_server --profile {profile_q}
"""

PY_LAUNCHER = '''"""Start the identity memory MCP server for profile {profile!r} (Windows)."""
import os, shutil, subprocess, sys
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = dict(os.environ)
for key, value in {env!r}.items():
    env.setdefault(key, os.path.expanduser(value))
env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
env["PYTHONIOENCODING"] = "utf-8"
python = sys.executable
if sys.version_info < (3, 10):
    for name in ("py", "python3", "python"):
        found = shutil.which(name)
        if found:
            python = found
            break
cmd = [python] + (["-3"] if os.path.basename(python).lower().startswith("py.") else [])
sys.exit(subprocess.call(cmd + ["-m", "trajecta_identity.mcp_server", "--profile", {profile!r}], env=env))
'''


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _sh_value(value: str) -> str:
    # Keep a leading ~ or $HOME expandable; quote everything else.
    if value.startswith("~/"):
        return '"$HOME"' + _sh_quote(value[1:])
    if value.startswith("$HOME/"):
        return '"$HOME"' + _sh_quote(value[5:])
    return _sh_quote(value)


def _git_rev() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("trajecta-identity-memory")
    except Exception:  # not installed: read pyproject
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8") if (REPO_ROOT / "pyproject.toml").exists() else ""
        for line in text.splitlines():
            if line.strip().startswith("version"):
                return line.split("=", 1)[1].strip().strip('"')
    return "0.0.0"


def _skill_dir() -> Path | None:
    for base in (REPO_ROOT / "skills", PACKAGE_ROOT / "skills"):
        if (base / SKILL / "SKILL.md").exists():
            return base / SKILL
    return None


def plugin_env(*, house: str | None = None, data_dir: str | None = None,
               profiles_dir: str | None = None, work_root: str | None = None) -> dict[str, str]:
    env: dict[str, str] = {}
    if house:
        house = house.rstrip("/\\")
        data_dir = data_dir or f"{house}/house-data/identity"
        profiles_dir = profiles_dir or f"{house}/private-profiles"
        work_root = work_root or f"{house}/house-data/work"
    if data_dir:
        env["TRAJECTA_IDENTITY_DATA_DIR"] = data_dir
    if profiles_dir:
        env["TRAJECTA_IDENTITY_PROFILES"] = profiles_dir
    if work_root:
        env["TRAJECTA_WORK_ROOT"] = work_root
    return env


def plugin_files(profile: str, *, name: str | None = None, target: str | None = None,
                 env: dict[str, str] | None = None) -> dict[str, bytes]:
    """Every file of the plugin, keyed by its path inside the zip."""

    env = env or {}
    target = target or ("windows" if os.name == "nt" else "posix")
    if target not in {"posix", "windows"}:
        raise ValueError("target must be 'posix' or 'windows'")
    server = name or f"trajecta-identity-{safe_fs_name(profile).strip('_') or profile}"
    rev = _git_rev()
    version = _package_version()
    files: dict[str, bytes] = {}

    files[".claude-plugin/plugin.json"] = (json.dumps({
        "name": server,
        "version": version,
        "description": (
            f"Identity memory for profile '{profile}' (trajecta-identity-memory {version}"
            + (f" @ {rev}" if rev else "") + "). Install once; it starts with Claude."
        ),
        "author": {"name": "trajecta-identity-memory"},
        "keywords": ["identity", "continuity", "memory", "vho"],
    }, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    if target == "posix":
        launcher = f"{LAUNCHER_DIR}/identity.sh"
        command = {"command": "/bin/sh", "args": ["${CLAUDE_PLUGIN_ROOT}/" + launcher]}
        exports = "\n".join(
            f'[ -n "${key}" ] || {key}={_sh_value(value)}; export {key}' for key, value in env.items()
        )
        files[launcher] = SH_LAUNCHER.format(
            profile=profile, profile_q=_sh_quote(profile), server=server, exports=exports
        ).encode("utf-8")
    else:
        launcher = f"{LAUNCHER_DIR}/launch.py"
        command = {"command": "python", "args": ["${CLAUDE_PLUGIN_ROOT}/" + launcher]}
        files[launcher] = PY_LAUNCHER.format(profile=profile, env=env).encode("utf-8")

    files[".mcp.json"] = (json.dumps({"mcpServers": {server: command}}, indent=2) + "\n").encode("utf-8")

    for package in VENDORED:
        source = REPO_ROOT / package if (REPO_ROOT / package).is_dir() else PACKAGE_ROOT.parent / package
        for path in sorted(source.rglob("*")):
            if path.is_file() and not SKIP_PARTS.intersection(path.parts) and path.suffix != ".pyc":
                files[f"{package}/{path.relative_to(source).as_posix()}"] = path.read_bytes()

    skill = _skill_dir()
    if skill:
        for path in sorted(skill.rglob("*")):
            if path.is_file() and not SKIP_PARTS.intersection(path.parts):
                files[f"skills/{SKILL}/{path.relative_to(skill).as_posix()}"] = path.read_bytes()

    bad = {key.split("/", 1)[0] for key in files} & FORBIDDEN_TOP_LEVEL
    if bad:  # guard against regressions: uploads reject these folders
        raise ValueError(f"plugin must not contain top-level folders: {sorted(bad)}")
    return files


def build_plugin(out: str | Path, profile: str, **kwargs: Any) -> dict[str, Any]:
    """Write the .plugin zip atomically and return a short report."""

    env = plugin_env(**{k: kwargs.pop(k) for k in ("house", "data_dir", "profiles_dir", "work_root") if k in kwargs})
    files = plugin_files(profile, env=env, **kwargs)
    out = Path(out).expanduser()
    if out.is_dir() or not out.suffix:
        server = json.loads(files[".claude-plugin/plugin.json"])["name"]
        out = out / f"{server}.plugin"
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".plugin", prefix=".build-")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o755 if name.startswith(LAUNCHER_DIR + "/") else 0o644) << 16
                archive.writestr(info, data)
        try:
            os.replace(tmp, out)
        except OSError:  # temp dir on another volume, or the folder forbids rename
            shutil.copyfile(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {"plugin": str(out), "files": len(files), "env": env,
            "server": json.loads(files[".claude-plugin/plugin.json"])["name"]}


if __name__ == "__main__":  # pragma: no cover
    sys.exit("use: trajecta-identity plugin --profile NAME --out DIR")
