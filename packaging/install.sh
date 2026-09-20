#!/usr/bin/env bash
# Install Worklog into the user's environment (no root required).
#
# - installs the `worklog` CLI via `uv tool install`
# - copies the SVG icon into the user's hicolor theme
# - registers the .desktop entry so Worklog appears in the launcher / dock
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ICON_SRC="$PROJECT_ROOT/worklog/resources/icons/worklog.svg"
DESKTOP_SRC="$PROJECT_ROOT/packaging/worklog.desktop"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
APPS_DIR="$DATA_HOME/applications"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: 'uv' is not installed. See https://docs.astral.sh/uv/" >&2
  exit 1
fi

echo "==> installing worklog via uv tool"
uv tool install --reinstall "$PROJECT_ROOT"

echo "==> installing icons to $ICON_DIR"
mkdir -p "$ICON_DIR"
cp "$ICON_SRC" "$ICON_DIR/worklog.svg"
cp "$PROJECT_ROOT/worklog/resources/icons/worklog-active.svg" "$ICON_DIR/worklog-active.svg"

echo "==> installing desktop entry to $APPS_DIR"
mkdir -p "$APPS_DIR"
cp "$DESKTOP_SRC" "$APPS_DIR/worklog.desktop"
chmod +x "$APPS_DIR/worklog.desktop" || true

if command -v update-desktop-database >/dev/null 2>&1; then
  echo "==> refreshing desktop database"
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  echo "==> refreshing icon cache"
  gtk-update-icon-cache --force --ignore-theme-index "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
fi

echo
echo "✓ worklog installed."
echo "  CLI:    $(command -v worklog || echo "(reopen shell for PATH)")"
echo "  Icon:   $ICON_DIR/worklog.svg"
echo "  Entry:  $APPS_DIR/worklog.desktop"
echo
echo "Look for 'Worklog' in your application launcher."
