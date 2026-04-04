#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP_DIR="${HOME}/Desktop"
APP_NAME="agent-runner"
APP_BUNDLE="${DESKTOP_DIR}/${APP_NAME}.app"
SOURCE_APP="${SCRIPT_DIR}/build/macos/${APP_NAME}.app"

if [[ ! -d "$DESKTOP_DIR" ]]; then
  echo "Desktop directory not found: $DESKTOP_DIR" >&2
  exit 1
fi

if [[ ! -x "${SCRIPT_DIR}/scripts/build-dev-mac-app.sh" ]]; then
  echo "Build script missing or not executable: ${SCRIPT_DIR}/scripts/build-dev-mac-app.sh" >&2
  exit 1
fi

"${SCRIPT_DIR}/scripts/build-dev-mac-app.sh"

if [[ ! -d "$SOURCE_APP" ]]; then
  echo "Built app not found: $SOURCE_APP" >&2
  exit 1
fi

rm -rf "$APP_BUNDLE"
cp -R "$SOURCE_APP" "$APP_BUNDLE"
touch "$APP_BUNDLE"
echo "Created desktop launcher: $APP_BUNDLE"
echo "Source app: $SOURCE_APP"
