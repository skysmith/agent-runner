#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build/macos"
APP_NAME="agent-runner"
APP_BUNDLE="${BUILD_DIR}/${APP_NAME}.app"
APP_CONTENTS="${APP_BUNDLE}/Contents"
APP_MACOS="${APP_CONTENTS}/MacOS"
APP_RESOURCES="${APP_CONTENTS}/Resources"
EMOJI_ICON="🕵️"

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
  <string>agent-runner</string>
  <key>CFBundleExecutable</key>
  <string>agent-runner</string>
  <key>CFBundleIconFile</key>
  <string>agent-runner</string>
  <key>CFBundleIdentifier</key>
  <string>local.agent-runner.devapp</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>agent-runner</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
</dict>
</plist>
PLIST

printf '%s\n' "$SCRIPT_DIR" > "${APP_RESOURCES}/repo-path"

cat > "${APP_MACOS}/agent-runner" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_PATH="$(cat "${APP_ROOT}/Resources/repo-path")"
LAUNCHER="${REPO_PATH}/agent-runner.command"
export AGENT_RUNNER_APP_BUNDLE="${APP_ROOT%/Contents}"

if [[ ! -x "$LAUNCHER" ]]; then
  osascript -e 'display alert "agent-runner" message "Launcher script is missing or not executable." as critical'
  exit 1
fi

cd "$REPO_PATH"
exec /bin/bash "$LAUNCHER"
LAUNCHER
chmod +x "${APP_MACOS}/agent-runner"

TMP_DIR="$(mktemp -d)"
ICON_PNG="${TMP_DIR}/agent-runner-1024.png"
ICONSET_DIR="${TMP_DIR}/agent-runner.iconset"
ICON_FILE="${APP_RESOURCES}/agent-runner.icns"

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

touch "$APP_BUNDLE"
echo "Built dev mac app: $APP_BUNDLE"
