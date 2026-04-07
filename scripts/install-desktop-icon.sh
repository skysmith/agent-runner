#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP_DIR="${HOME}/Desktop"
APPLICATIONS_DIR="${HOME}/Applications"
APP_NAME="Alcove"
SOURCE_APP="${SCRIPT_DIR}/build/macos/${APP_NAME}.app"

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

TARGET_DIRS=("$APPLICATIONS_DIR")
if [[ -d "$DESKTOP_DIR" ]]; then
  TARGET_DIRS+=("$DESKTOP_DIR")
fi

for target_dir in "${TARGET_DIRS[@]}"; do
  app_bundle="${target_dir}/${APP_NAME}.app"
  legacy_app_bundle="${target_dir}/agent-runner.app"
  rm -rf "$app_bundle"
  rm -rf "$legacy_app_bundle"
  cp -R "$SOURCE_APP" "$app_bundle"
  touch "$app_bundle"
  echo "Installed launcher: $app_bundle"
  echo "Removed legacy launcher: $legacy_app_bundle"
done

echo "Source app: $SOURCE_APP"
