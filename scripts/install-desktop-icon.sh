#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP_DIR="${HOME}/Desktop"
APPLICATIONS_DIR="${HOME}/Applications"
APP_NAME="Alcove"
SOURCE_APP="${SCRIPT_DIR}/build/macos/${APP_NAME}.app"
AUTHORITATIVE_APP="${APPLICATIONS_DIR}/${APP_NAME}.app"

mkdir -p "$APPLICATIONS_DIR"

if [[ ! -x "${SCRIPT_DIR}/scripts/build-dev-mac-app.sh" ]]; then
  echo "Build script missing or not executable: ${SCRIPT_DIR}/scripts/build-dev-mac-app.sh" >&2
  exit 1
fi

"${SCRIPT_DIR}/scripts/build-dev-mac-app.sh"

if [[ ! -d "$SOURCE_APP" ]]; then
  echo "Built app not found: $SOURCE_APP" >&2
  exit 1
fi

rm -rf "$AUTHORITATIVE_APP"
rm -rf "${APPLICATIONS_DIR}/agent-runner.app"
cp -R "$SOURCE_APP" "$AUTHORITATIVE_APP"
touch "$AUTHORITATIVE_APP"
echo "Installed authoritative launcher: $AUTHORITATIVE_APP"
echo "Removed legacy launcher: ${APPLICATIONS_DIR}/agent-runner.app"

if [[ -d "$DESKTOP_DIR" ]]; then
  desktop_app="${DESKTOP_DIR}/${APP_NAME}.app"
  legacy_desktop_app="${DESKTOP_DIR}/agent-runner.app"
  rm -rf "$desktop_app"
  rm -rf "$legacy_desktop_app"
  ln -s "$AUTHORITATIVE_APP" "$desktop_app"
  echo "Installed desktop shortcut: $desktop_app -> $AUTHORITATIVE_APP"
  echo "Removed legacy launcher: $legacy_desktop_app"
fi

echo "Source app: $SOURCE_APP"
