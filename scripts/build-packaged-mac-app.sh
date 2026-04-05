#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SPEC_FILE="${SCRIPT_DIR}/packaging/agent-runner.spec"
DIST_DIR="${SCRIPT_DIR}/dist"
BUILD_DIR="${SCRIPT_DIR}/build/pyinstaller"
APP_BUNDLE="${DIST_DIR}/Alcove.app"

PYTHON_BIN="${AGENT_RUNNER_PYTHON:-$(command -v python3 || true)}"
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "python3 is required to package Alcove." >&2
  exit 1
fi

if [[ ! -f "$SPEC_FILE" ]]; then
  echo "Missing spec file: $SPEC_FILE" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller is not installed for $PYTHON_BIN" >&2
  echo "Install with: $PYTHON_BIN -m pip install pyinstaller" >&2
  exit 1
fi

# Reuse the dev icon build so packaged app branding stays consistent.
if [[ -x "${SCRIPT_DIR}/scripts/build-dev-mac-app.sh" ]]; then
  "${SCRIPT_DIR}/scripts/build-dev-mac-app.sh" >/dev/null
fi

rm -rf "$APP_BUNDLE" "$BUILD_DIR"

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  "$SPEC_FILE"

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "Packaged app missing: $APP_BUNDLE" >&2
  exit 1
fi

touch "$APP_BUNDLE"
echo "Built packaged app: $APP_BUNDLE"
