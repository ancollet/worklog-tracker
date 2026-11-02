#!/usr/bin/env bash
# Builds dist/worklog_<version>_amd64.deb: a standalone PyInstaller build under /opt/worklog
# plus launcher symlink, .desktop entry and icons. Needs uv and dpkg-deb (any Debian/Ubuntu).
#
#   ./packaging/linux/build-deb.sh 0.1.0
set -euo pipefail

VERSION="${1:?usage: build-deb.sh <version>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

uv sync --extra build
uv run pyinstaller --noconfirm --windowed --name worklog \
  --paths . \
  --collect-all PyQt6 \
  --collect-submodules keyring \
  --add-data "worklog/resources/icons:worklog/resources/icons" \
  packaging/run_worklog.py

PKG="build/deb"
rm -rf "$PKG"
install -d "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" "$PKG/usr/share/applications" \
  "$PKG/usr/share/icons/hicolor/scalable/apps"
cp -r dist/worklog "$PKG/opt/worklog"
ln -s /opt/worklog/worklog "$PKG/usr/bin/worklog"
cp packaging/worklog.desktop "$PKG/usr/share/applications/"
cp worklog/resources/icons/worklog.svg worklog/resources/icons/worklog-active.svg \
  "$PKG/usr/share/icons/hicolor/scalable/apps/"

cat > "$PKG/DEBIAN/control" <<CONTROL
Package: worklog
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: libxcb-cursor0, libxkbcommon-x11-0, libgl1, libegl1, libfontconfig1, libdbus-1-3
Recommends: gnome-keyring
Maintainer: A.Collet <dev@brighter.cloud>
Description: Time tracker / worklog desktop app
 Tracks working time per Jira-style task and books it to Salesforce.
CONTROL

mkdir -p dist
dpkg-deb --build --root-owner-group "$PKG" "dist/worklog_${VERSION}_amd64.deb"
