#!/usr/bin/env bash
# Builds dist/Worklog-<version>-<arch>.dmg: a standalone Worklog.app (PyInstaller) in a
# compressed disk image. Run on macOS; needs uv (hdiutil ships with macOS).
#
#   ./packaging/macos/build-dmg.sh 0.1.0
set -euo pipefail

VERSION="${1:?usage: build-dmg.sh <version>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
ARCH="$(uname -m)"   # arm64 on Apple Silicon, x86_64 on Intel

uv sync --extra build
uv run pyinstaller --noconfirm --windowed --name Worklog \
  --paths . \
  --collect-all PyQt6 \
  --collect-submodules keyring \
  --add-data "worklog/resources/icons:worklog/resources/icons" \
  --osx-bundle-identifier cloud.brighter.worklog \
  packaging/run_worklog.py

STAGE="build/dmg"
rm -rf "$STAGE"
mkdir -p "$STAGE" dist
cp -R dist/Worklog.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"   # drag-to-install target

rm -f "dist/Worklog-${VERSION}-${ARCH}.dmg"
hdiutil create -volname "Worklog ${VERSION}" -srcfolder "$STAGE" -ov -format UDZO \
  "dist/Worklog-${VERSION}-${ARCH}.dmg"
