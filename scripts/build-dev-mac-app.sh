#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build/macos"
APP_NAME="Alcove"
APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
APP_CONTENTS="${APP_BUNDLE}/Contents"
APP_MACOS="${APP_CONTENTS}/MacOS"
APP_RESOURCES="${APP_CONTENTS}/Resources"
EMOJI_ICON="A"

rm -rf "$APP_BUNDLE"
mkdir -p "$APP_MACOS" "$APP_RESOURCES"

cat > "${APP_CONTENTS}/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>English</string>
  <key>CFBundleDisplayName</key>
  <string>Alcove</string>
  <key>CFBundleExecutable</key>
  <string>Alcove</string>
  <key>CFBundleIconFile</key>
  <string>Alcove</string>
  <key>CFBundleIdentifier</key>
  <string>local.alcove.devapp</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Alcove</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeName</key>
      <string>Folder</string>
      <key>CFBundleTypeRole</key>
      <string>Viewer</string>
      <key>LSHandlerRank</key>
      <string>Alternate</string>
      <key>LSItemContentTypes</key>
      <array>
        <string>public.folder</string>
      </array>
    </dict>
  </array>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>Alcove uses the microphone to turn speech into text for chat prompts.</string>
  <key>NSSpeechRecognitionUsageDescription</key>
  <string>Alcove uses speech recognition to transcribe spoken prompts into the chat composer.</string>
</dict>
</plist>
PLIST

printf '%s\n' "$SCRIPT_DIR" > "${APP_RESOURCES}/repo-path"

cat > "${APP_MACOS}/Alcove" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_PATH="$(cat "${APP_ROOT}/Resources/repo-path")"
export AGENT_RUNNER_APP_BUNDLE="${APP_ROOT%/Contents}"
export AGENT_RUNNER_WRAPPER_EXECUTABLE="${APP_ROOT}/MacOS/Alcove"
for extra_path in \
  "$HOME/.npm-global/bin" \
  "$HOME/.local/bin" \
  "$HOME/.volta/bin" \
  "$HOME/.yarn/bin" \
  "$HOME/.cargo/bin" \
  "/opt/homebrew/bin" \
  "/usr/local/bin"; do
  if [[ -d "$extra_path" && ":${PATH:-}:" != *":$extra_path:"* ]]; then
    PATH="${PATH:+$PATH:}$extra_path"
  fi
done
export PATH
WEB_HOST="${AGENT_RUNNER_WEB_HOST:-0.0.0.0}"
WEB_PORT="${AGENT_RUNNER_WEB_PORT:-8765}"
PASSWORD_FILE="${REPO_PATH}/.agent-runner/web-password"
WEB_PASSWORD="${AGENT_RUNNER_WEB_PASSWORD:-}"
if [[ -z "${WEB_PASSWORD}" && -f "${PASSWORD_FILE}" ]]; then
  WEB_PASSWORD="$(head -n 1 "${PASSWORD_FILE}" | tr -d '\r')"
fi

PYTHON_BIN=""
for candidate in \
  "${REPO_PATH}/.venv/bin/python" \
  "${REPO_PATH}/.venv/bin/python3" \
  "$(command -v python3 || true)" \
  "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"; do
  if [[ -n "${candidate}" && -x "${candidate}" ]]; then
    PYTHON_BIN="${candidate}"
    break
  fi
done

if [[ -z "${PYTHON_BIN}" ]]; then
  osascript -e 'display alert "Alcove" message "Could not find a usable Python interpreter." as critical'
  exit 1
fi

cd "$REPO_PATH"
export PYTHONPATH="${REPO_PATH}/src${PYTHONPATH:+:$PYTHONPATH}"

export AGENT_RUNNER_PYTHON="${PYTHON_BIN}"
export AGENT_RUNNER_REPO="${REPO_PATH}"
export AGENT_RUNNER_WEB_HOST="${WEB_HOST}"
export AGENT_RUNNER_WEB_PORT="${WEB_PORT}"
if [[ -n "${WEB_PASSWORD}" ]]; then
  export AGENT_RUNNER_WEB_PASSWORD="${WEB_PASSWORD}"
fi

if [[ "${1:-}" != "--service" && "${1:-}" != "--control" ]]; then
  "${PYTHON_BIN}" -m agent_runner doctor --repo "${REPO_PATH}" >/dev/null 2>&1 || true
fi

exec "${PYTHON_BIN}" -m agent_runner.packaged_entry "$@"
LAUNCHER
chmod +x "${APP_MACOS}/Alcove"

TMP_DIR="$(mktemp -d)"
ICON_PNG="${TMP_DIR}/alcove-1024.png"
ICONSET_DIR="${TMP_DIR}/alcove.iconset"
ICON_FILE="${APP_RESOURCES}/Alcove.icns"

build_icon() {
swift - "$ICON_PNG" "$EMOJI_ICON" <<'SWIFT'
import AppKit

let outPath = CommandLine.arguments[1]
let emoji = CommandLine.arguments[2]
let canvas = NSRect(x: 0, y: 0, width: 1024, height: 1024)
let image = NSImage(size: canvas.size)
image.lockFocus()

NSColor(calibratedWhite: 0.96, alpha: 1.0).setFill()
NSBezierPath(roundedRect: canvas.insetBy(dx: 48, dy: 48), xRadius: 210, yRadius: 210).fill()

let style = NSMutableParagraphStyle()
style.alignment = .center
let attrs: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 730),
    .paragraphStyle: style
]
(emoji as NSString).draw(in: NSRect(x: 0, y: 110, width: 1024, height: 820), withAttributes: attrs)

image.unlockFocus()
guard let tiff = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let png = bitmap.representation(using: .png, properties: [:]) else {
    fputs("failed to create icon PNG\n", stderr)
    exit(1)
}
try png.write(to: URL(fileURLWithPath: outPath))
SWIFT

mkdir -p "$ICONSET_DIR"
sips -z 16 16     "$ICON_PNG" --out "${ICONSET_DIR}/icon_16x16.png" >/dev/null
sips -z 32 32     "$ICON_PNG" --out "${ICONSET_DIR}/icon_16x16@2x.png" >/dev/null
sips -z 32 32     "$ICON_PNG" --out "${ICONSET_DIR}/icon_32x32.png" >/dev/null
sips -z 64 64     "$ICON_PNG" --out "${ICONSET_DIR}/icon_32x32@2x.png" >/dev/null
sips -z 128 128   "$ICON_PNG" --out "${ICONSET_DIR}/icon_128x128.png" >/dev/null
sips -z 256 256   "$ICON_PNG" --out "${ICONSET_DIR}/icon_128x128@2x.png" >/dev/null
sips -z 256 256   "$ICON_PNG" --out "${ICONSET_DIR}/icon_256x256.png" >/dev/null
sips -z 512 512   "$ICON_PNG" --out "${ICONSET_DIR}/icon_256x256@2x.png" >/dev/null
sips -z 512 512   "$ICON_PNG" --out "${ICONSET_DIR}/icon_512x512.png" >/dev/null
cp "$ICON_PNG" "${ICONSET_DIR}/icon_512x512@2x.png"
iconutil -c icns "$ICONSET_DIR" -o "$ICON_FILE"
}

if ! build_icon; then
  echo "Warning: failed to build emoji icon; continuing with default app icon." >&2
fi
rm -rf "$TMP_DIR"

NATIVE_SPEECH_SRC="${SCRIPT_DIR}/packaging/macos/AlcoveNativeSpeech.swift"
NATIVE_SPEECH_BIN="${APP_MACOS}/AlcoveNativeSpeech"

if [[ -f "$NATIVE_SPEECH_SRC" ]] && command -v swiftc >/dev/null 2>&1; then
  if swiftc -O -framework AVFoundation -framework Speech "$NATIVE_SPEECH_SRC" -o "$NATIVE_SPEECH_BIN"; then
    chmod +x "$NATIVE_SPEECH_BIN"
  else
    rm -f "$NATIVE_SPEECH_BIN"
    echo "Warning: could not build native speech helper." >&2
  fi
else
  echo "Warning: could not build native speech helper; swiftc or source file is missing." >&2
fi

HELPER_SRC="${SCRIPT_DIR}/packaging/macos/AlcoveMenuBar.swift"
HELPER_APP="${APP_RESOURCES}/AlcoveMenuBar.app"
HELPER_CONTENTS="${HELPER_APP}/Contents"
HELPER_MACOS="${HELPER_CONTENTS}/MacOS"
HELPER_RESOURCES="${HELPER_CONTENTS}/Resources"

if [[ -f "$HELPER_SRC" ]] && command -v swiftc >/dev/null 2>&1; then
  rm -rf "$HELPER_APP"
  mkdir -p "$HELPER_MACOS" "$HELPER_RESOURCES"
  cat > "${HELPER_CONTENTS}/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>English</string>
  <key>CFBundleDisplayName</key>
  <string>Alcove Menu Bar</string>
  <key>CFBundleExecutable</key>
  <string>AlcoveMenuBar</string>
  <key>CFBundleIdentifier</key>
  <string>local.alcove.menubar</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>AlcoveMenuBar</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
PLIST
  swiftc -O -framework AppKit "$HELPER_SRC" -o "${HELPER_MACOS}/AlcoveMenuBar"
  chmod +x "${HELPER_MACOS}/AlcoveMenuBar"
  if [[ -f "$ICON_FILE" ]]; then
    cp "$ICON_FILE" "${HELPER_RESOURCES}/Alcove.icns"
  fi
else
  echo "Warning: could not build Alcove menu bar helper; swiftc or source file is missing." >&2
fi

touch "$APP_BUNDLE"
echo "Built dev mac app: $APP_BUNDLE"
