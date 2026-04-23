#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SPEC_FILE="${SCRIPT_DIR}/packaging/agent-runner.spec"
DIST_DIR="${SCRIPT_DIR}/dist"
BUILD_DIR="${SCRIPT_DIR}/build/pyinstaller"
APP_BUNDLE="${DIST_DIR}/Alcove.app"
DEV_HELPER_APP="${SCRIPT_DIR}/build/macos/Alcove.app/Contents/Resources/AlcoveMenuBar.app"
DEV_REPO_PATH_FILE="${SCRIPT_DIR}/build/macos/Alcove.app/Contents/Resources/repo-path"
DEV_NATIVE_SPEECH_BIN="${SCRIPT_DIR}/build/macos/Alcove.app/Contents/MacOS/AlcoveNativeSpeech"

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

if [[ -d "$DEV_HELPER_APP" ]]; then
  rm -rf "${APP_BUNDLE}/Contents/Resources/AlcoveMenuBar.app"
  cp -R "$DEV_HELPER_APP" "${APP_BUNDLE}/Contents/Resources/AlcoveMenuBar.app"
fi

if [[ -f "$DEV_NATIVE_SPEECH_BIN" ]]; then
  cp "$DEV_NATIVE_SPEECH_BIN" "${APP_BUNDLE}/Contents/MacOS/AlcoveNativeSpeech"
  chmod +x "${APP_BUNDLE}/Contents/MacOS/AlcoveNativeSpeech"
fi

if [[ -f "$DEV_REPO_PATH_FILE" ]]; then
  cp "$DEV_REPO_PATH_FILE" "${APP_BUNDLE}/Contents/Resources/repo-path"
fi

"$PYTHON_BIN" - <<'PY' "${APP_BUNDLE}/Contents/Info.plist"
from pathlib import Path
import plistlib
import sys

path = Path(sys.argv[1])
with path.open("rb") as handle:
    payload = plistlib.load(handle)

payload["NSMicrophoneUsageDescription"] = "Alcove uses the microphone to turn speech into text for chat prompts."
payload["NSSpeechRecognitionUsageDescription"] = "Alcove uses speech recognition to transcribe spoken prompts into the chat composer."
payload["CFBundleDocumentTypes"] = [
    {
        "CFBundleTypeName": "Folder",
        "CFBundleTypeRole": "Viewer",
        "LSHandlerRank": "Alternate",
        "LSItemContentTypes": ["public.folder"],
    }
]

with path.open("wb") as handle:
    plistlib.dump(payload, handle, sort_keys=True)
PY

touch "$APP_BUNDLE"
echo "Built packaged app: $APP_BUNDLE"
