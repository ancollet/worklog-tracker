"""XDG-conformant paths for app data and config."""
from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

APP_NAME = "worklog"


def icon_path() -> Path:
    """Return filesystem path to the packaged app icon SVG."""
    ref = resources.files("worklog").joinpath("resources/icons/worklog.svg")
    with resources.as_file(ref) as p:
        return Path(p)


def _xdg(env_var: str, fallback: str) -> Path:
    value = os.environ.get(env_var)
    base = Path(value) if value else Path.home() / fallback
    return base / APP_NAME


def data_dir() -> Path:
    p = _xdg("XDG_DATA_HOME", ".local/share")
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_dir() -> Path:
    p = _xdg("XDG_CONFIG_HOME", ".config")
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "worklog.db"


def lock_path() -> Path:
    return data_dir() / ".lock"


def socket_path() -> Path:
    return data_dir() / ".ipc.sock"


def autostart_desktop_path() -> Path:
    p = Path.home() / ".config" / "autostart"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{APP_NAME}.desktop"
