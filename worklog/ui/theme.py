"""Optional qt-material theming. Default is the plain native Qt look."""
from __future__ import annotations

from PyQt6.QtWidgets import QApplication

SETTINGS_UI_THEME = "ui_theme"
# Plain, native Qt look — the default. qt-material is strictly opt-in.
PLAIN_THEME = "none"
DEFAULT_UI_THEME = PLAIN_THEME

# (label shown in the dropdown, theme value). The first entry is the plain
# native look; the rest are qt-material themes the user can opt into.
THEMES: list[tuple[str, str]] = [
    ("Standard (schlicht)", PLAIN_THEME),
    ("Dark · Teal", "dark_teal.xml"),
    ("Dark · Blue", "dark_blue.xml"),
    ("Dark · Cyan", "dark_cyan.xml"),
    ("Dark · Purple", "dark_purple.xml"),
    ("Dark · Amber", "dark_amber.xml"),
    ("Dark · Pink", "dark_pink.xml"),
    ("Light · Teal", "light_teal.xml"),
    ("Light · Blue", "light_blue.xml"),
    ("Light · Purple", "light_purple.xml"),
    ("Light · Amber", "light_amber.xml"),
]


def apply_theme(app: QApplication, theme: str | None) -> None:
    """Apply a theme. PLAIN_THEME (or unknown) restores the native Qt look."""
    if not theme or theme == PLAIN_THEME:
        app.setStyleSheet("")
        return
    try:
        from qt_material import apply_stylesheet
    except ImportError:
        return
    apply_stylesheet(
        app,
        theme=theme,
        invert_secondary=theme.startswith("light"),
        extra={"density_scale": "-1"},
    )
