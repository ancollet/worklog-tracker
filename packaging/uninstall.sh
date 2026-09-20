#!/usr/bin/env bash
set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"

echo "==> removing CLI"
uv tool uninstall worklog 2>/dev/null || true

echo "==> removing icons"
rm -f "$DATA_HOME/icons/hicolor/scalable/apps/worklog.svg"
rm -f "$DATA_HOME/icons/hicolor/scalable/apps/worklog-active.svg"

echo "==> removing desktop entry"
rm -f "$DATA_HOME/applications/worklog.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache --force --ignore-theme-index "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
fi

echo
echo "✓ worklog uninstalled."
echo "  Data dir untouched: $DATA_HOME/worklog/  (your DB lives here)"
