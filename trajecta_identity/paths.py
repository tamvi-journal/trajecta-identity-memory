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


def repo_profiles_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "profiles"
