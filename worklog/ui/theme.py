"""App theme: Fusion style + a palette and one stylesheet built from colour tokens.

Widgets never hard-code colours. Text that carries a meaning gets a role
(`set_role`, `set_status`); item colours come from `color()`.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from string import Template

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

SETTINGS_UI_THEME = "ui_theme"
SYSTEM_THEME = "system"
LIGHT_THEME = "light"
DARK_THEME = "dark"
DEFAULT_UI_THEME = SYSTEM_THEME

# (label shown in the dropdown, theme value)
THEMES: list[tuple[str, str]] = [
    ("System (hell/dunkel automatisch)", SYSTEM_THEME),
    ("Hell", LIGHT_THEME),
    ("Dunkel", DARK_THEME),
]

LIGHT = dict(
    bg="#F5F6F8", surface="#FFFFFF", surface2="#EEF0F4", border="#E2E5EA",
    text="#111827", muted="#6B7280", accent="#4F46E5", accent_hover="#4338CA",
    accent_soft="#EEF2FF", on_accent="#FFFFFF", success="#047857",
    success_soft="#E7F6EF", warn="#B45309", danger="#B91C1C",
    group="#E5E7EB", subgroup="#F3F4F6",
)
DARK = dict(
    bg="#0F1116", surface="#181B22", surface2="#222630", border="#2B303B",
    text="#E7E9EE", muted="#949CAB", accent="#818CF8", accent_hover="#A5ACFB",
    accent_soft="#262A52", on_accent="#0F1116", success="#34D399",
    success_soft="#12302A", warn="#FBBF24", danger="#F87171",
    group="#2B303B", subgroup="#222630",
)

_tokens = LIGHT
_asset_dir: Path | None = None
_watching_system = False


def color(name: str) -> str:
    """Hex value of a colour token in the active theme, e.g. color("success")."""
    return _tokens[name]


def set_role(widget: QWidget, role: str) -> None:
    """Give a widget a text role the stylesheet knows:
    hint, hint-ok, hint-error, muted, title, running, warn."""
    widget.setProperty("role", role)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_status(widget: QWidget, kind: str = "neutral") -> None:
    """Small status line: kind is "ok", "error" or anything else for neutral."""
    set_role(widget, {"ok": "hint-ok", "error": "hint-error"}.get(kind, "hint"))


def resolve_theme(app: QApplication, theme: str | None) -> str:
    """Map a stored theme value (including old qt-material names) to light/dark."""
    if theme == DARK_THEME or (theme or "").startswith("dark_"):
        return DARK_THEME
    if theme == LIGHT_THEME or (theme or "").startswith("light_"):
        return LIGHT_THEME
    dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    return DARK_THEME if dark else LIGHT_THEME


def apply_theme(app: QApplication, theme: str | None) -> None:
    global _tokens, _watching_system
    _tokens = DARK if resolve_theme(app, theme) == DARK_THEME else LIGHT
    app.setProperty("worklog_theme", theme or SYSTEM_THEME)
    if not _watching_system:
        _watching_system = True
        app.styleHints().colorSchemeChanged.connect(
            lambda _scheme: apply_theme(app, app.property("worklog_theme"))
        )
    app.setStyle("Fusion")
    app.setPalette(_palette(_tokens))
    app.setStyleSheet(_QSS.substitute(_tokens, **_arrow_assets(_tokens)))


def _palette(t: dict) -> QPalette:
    p = QPalette()
    roles = QPalette.ColorRole
    for role, token in (
        (roles.Window, "bg"), (roles.WindowText, "text"), (roles.Base, "surface"),
        (roles.AlternateBase, "subgroup"), (roles.Text, "text"), (roles.Button, "surface"),
        (roles.ButtonText, "text"), (roles.Highlight, "accent"), (roles.HighlightedText, "on_accent"),
        (roles.ToolTipBase, "text"), (roles.ToolTipText, "bg"), (roles.PlaceholderText, "muted"),
        (roles.Link, "accent"), (roles.Mid, "border"), (roles.Dark, "muted"), (roles.Light, "surface"),
    ):
        p.setColor(role, QColor(t[token]))
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["muted"]))
    return p


def _arrow_assets(t: dict) -> dict[str, str]:
    """Write the chevrons and the check mark in the theme's colours; QSS needs them as files."""
    global _asset_dir
    if _asset_dir is None:
        _asset_dir = Path(tempfile.mkdtemp(prefix="worklog-theme-"))
    out = {}
    stroke = ' fill="none" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"'
    for name, path, token, width in (
        ("chevron_down", "M6 9l6 6 6-6", "muted", 2.5),
        ("chevron_up", "M6 15l6-6 6 6", "muted", 2.5),
        ("check", "M5 12.5l4.5 4.5L19 7.5", "on_accent", 3.5),
    ):
        f = _asset_dir / f"{name}-{t[token].lstrip('#')}.svg"
        f.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"'
            + stroke.format(c=t[token], w=width) + f'><path d="{path}"/></svg>'
        )
        out[name] = f.as_posix()
    return out


_QSS = Template("""
QWidget { font-size: 13px; }
QToolTip { background: $text; color: $bg; border: none; padding: 4px 8px; }

QLabel[role="hint"] { color: $muted; font-size: 11px; }
QLabel[role="hint-ok"] { color: $success; font-size: 11px; }
QLabel[role="hint-error"] { color: $danger; font-size: 11px; }
QLabel[role="muted"] { color: $muted; }
QLabel[role="title"] { font-weight: 600; }
QLabel[role="running"] { color: $success; font-weight: 600; }
QLabel[role="warn"] { color: $warn; }

QLineEdit, QComboBox, QAbstractSpinBox, QPlainTextEdit, QTextEdit {
    background: $surface; border: 1px solid $border; border-radius: 8px;
    selection-background-color: $accent; selection-color: $on_accent;
}
QLineEdit, QComboBox, QAbstractSpinBox { padding: 0 10px; min-height: 32px; }
QPlainTextEdit, QTextEdit { padding: 6px; }
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border: 1px solid $accent;
}
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled { background: $surface2; color: $muted; }
QLineEdit:read-only { background: $surface2; }
QComboBox::drop-down, QDateTimeEdit::drop-down { border: none; width: 28px; }
QComboBox::down-arrow, QDateTimeEdit::down-arrow { image: url($chevron_down); width: 14px; height: 14px; }
QComboBox QAbstractItemView {
    background: $surface; border: 1px solid $border; outline: 0;
    selection-background-color: $accent_soft; selection-color: $text;
}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { border: none; background: transparent; width: 22px; }
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover { background: $surface2; }
QAbstractSpinBox::up-arrow { image: url($chevron_up); width: 11px; height: 11px; }
QAbstractSpinBox::down-arrow { image: url($chevron_down); width: 11px; height: 11px; }

QPushButton {
    background: $surface; border: 1px solid $border; border-radius: 8px;
    padding: 0 14px; min-height: 32px; font-weight: 600;
}
QPushButton:hover { background: $surface2; }
QPushButton:pressed { background: $border; }
QPushButton:disabled { color: $muted; background: $surface2; }
QPushButton:default, QPushButton[variant="primary"] { background: $accent; color: $on_accent; border: none; }
QPushButton:default:hover, QPushButton[variant="primary"]:hover { background: $accent_hover; }
QPushButton:default:disabled, QPushButton[variant="primary"]:disabled { background: $surface2; color: $muted; }
QAbstractItemView QPushButton { min-height: 22px; padding: 0 10px; border-radius: 6px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 4px 8px; }
QToolButton:hover { background: $surface2; }

QCheckBox::indicator, QRadioButton::indicator, QAbstractItemView::indicator {
    width: 15px; height: 15px; border: 1px solid $muted; border-radius: 4px; background: $surface;
}
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover, QAbstractItemView::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {
    background: $accent; border-color: $accent; image: url($check);
}
QRadioButton::indicator:checked { width: 7px; height: 7px; border: 5px solid $accent; background: $surface; }
QCheckBox::indicator:disabled, QAbstractItemView::indicator:disabled { background: $surface2; border-color: $border; }

QProgressBar { background: $surface2; border: none; border-radius: 4px; max-height: 8px; text-align: center; color: transparent; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QSplitter::handle { background: transparent; }

QTabWidget::pane { border: none; border-top: 1px solid $border; }
QTabBar::tab {
    background: transparent; border: none; border-bottom: 2px solid transparent;
    padding: 10px 16px; color: $muted; font-weight: 600;
}
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected { color: $accent; border-bottom: 2px solid $accent; }

QTreeView, QTableView, QListView {
    background: $surface; alternate-background-color: $subgroup;
    border: 1px solid $border; border-radius: 10px; outline: 0; gridline-color: transparent;
}
QTreeView::item, QTableView::item, QListView::item { padding: 5px 2px; }
QTreeView::item:hover, QTableView::item:hover, QListView::item:hover { background: $surface2; }
QTreeView::item:selected, QTableView::item:selected, QListView::item:selected {
    background: $accent_soft; color: $text;
}
QHeaderView { background: transparent; }
QHeaderView::section {
    background: $surface; color: $muted; border: none; border-bottom: 1px solid $border;
    padding: 8px; font-size: 11px; font-weight: 700;
}
QTableCornerButton::section { background: $surface; border: none; }

QGroupBox { border: 1px solid $border; border-radius: 10px; margin-top: 10px; padding: 14px 10px 10px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: $muted; font-weight: 600; }

QMenu { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 6px; }
QMenu::item:selected { background: $accent_soft; color: $text; }
QMenu::item:disabled { color: $muted; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: $border; border-radius: 3px; min-height: 30px; min-width: 30px; }
QScrollBar::handle:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
""")
