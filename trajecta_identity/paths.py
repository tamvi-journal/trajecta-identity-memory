"""Where identity memory lives on each OS. Memory never lives in the repo."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Trajecta Identity Memory"
ENV_DATA_DIR = "TRAJECTA_IDENTITY_DATA_DIR"


def data_dir(platform: str | None = None, env: dict[str, str] | None = None) -> Path:
    env = dict(os.environ if env is None else env)
    override = env.get(ENV_DATA_DIR, "").strip()
    if override:
        return Path(override).expanduser()
    platform = platform or sys.platform
    home = Path(env.get("HOME") or env.get("USERPROFILE") or Path.home())
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    if platform.startswith("win"):
        base = env.get("LOCALAPPDATA") or env.get("APPDATA")
        root = Path(base) if base else home / "AppData" / "Local"
        return root / APP_NAME
    xdg = env.get("XDG_DATA_HOME", "").strip()
    root = Path(xdg) if xdg else home / ".local" / "share"
    return root / "trajecta-identity-memory"


def profile_db(profile: str, **kwargs) -> Path:
    safe = "".join(ch for ch in profile if ch.isalnum() or ch in "-_") or "default"
    return data_dir(**kwargs) / f"{safe}.sqlite3"


ENV_PROFILES_DIR = "TRAJECTA_IDENTITY_PROFILES"


def repo_profiles_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "profiles"


def profile_search_dirs(env: dict[str, str] | None = None) -> list[Path]:
    """Where a profile name is looked up, in order.

    1. ``$TRAJECTA_IDENTITY_PROFILES`` (a private profiles folder)
    2. ``<data dir>/profiles``
    3. ``profiles/`` in the source checkout (editable installs)
    """

    env = dict(os.environ if env is None else env)
    dirs = []
    if env.get(ENV_PROFILES_DIR, "").strip():
        dirs.append(Path(env[ENV_PROFILES_DIR]).expanduser())
    dirs.append(data_dir(env=env) / "profiles")
    dirs.append(repo_profiles_dir())
    return dirs


def utf8_stdio() -> None:
    """Windows consoles and pipes default to a legacy code page; force UTF-8."""

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="strict" if stream is sys.stdin else "replace")
