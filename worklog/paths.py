"""XDG-conformant paths for app data and config (native equivalents on Windows)."""
from __future__ import annotations

import os
import sys
from importlib import resources
from pathlib import Path

APP_NAME = "worklog"


def icon_path() -> Path:
    """Return filesystem path to the packaged app icon SVG."""
    ref = resources.files("worklog").joinpath("resources/icons/worklog.svg")
    with resources.as_file(ref) as p:
        return Path(p)


def _xdg(env_var: str, fallback: str) -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
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


def _autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return f'"{sys.executable}" -m worklog'


def _win_autostart_key():
    import winreg

    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_ALL_ACCESS,
    )


def _linux_autostart_path() -> Path:
    p = Path.home() / ".config" / "autostart"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{APP_NAME}.desktop"


def is_autostart_enabled() -> bool:
    if sys.platform == "win32":
        import winreg

        with _win_autostart_key() as key:
            try:
                winreg.QueryValueEx(key, APP_NAME)
                return True
            except FileNotFoundError:
                return False
    return _linux_autostart_path().exists()


def set_autostart(enabled: bool) -> None:
    """Register/unregister Worklog to start on login (Windows Run key / XDG autostart)."""
    if sys.platform == "win32":
        import winreg

        with _win_autostart_key() as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return

    path = _linux_autostart_path()
    if enabled:
        path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Worklog\n"
            f"Exec={_autostart_command()}\n"
            "X-GNOME-Autostart-enabled=true\n"
            "NoDisplay=false\n"
            "Terminal=false\n"
        )
    else:
        path.unlink(missing_ok=True)
