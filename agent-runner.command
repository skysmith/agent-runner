#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
TTY_PATH="$(tty || true)"
TERM_PROGRAM_NAME="${TERM_PROGRAM:-}"
LOG_DIR="${SCRIPT_DIR}/.agent-runner/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/ui-launch.log"
PYTHON_BIN="${AGENT_RUNNER_PYTHON:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  candidates=()
  candidates+=("${SCRIPT_DIR}/.venv/bin/python")
  candidates+=("${SCRIPT_DIR}/.venv/bin/python3")
  candidates+=("$(command -v python3 || true)")
  candidates+=("/Library/Frameworks/Python.framework/Versions/3.11/bin/python3")
  for candidate in "${candidates[@]}"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "Could not find a usable python3 interpreter." >&2
  exit 1
fi

run_doctor_check() {
  local doctor_output
  if doctor_output="$("$PYTHON_BIN" -m agent_runner doctor --repo "$SCRIPT_DIR" 2>&1)"; then
    return 0
  fi
  {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Doctor check failed"
    printf '%s\n' "$doctor_output"
  } >>"$LOG_FILE"
  printf '%s\n' "$doctor_output" >&2
  if command -v osascript >/dev/null 2>&1; then
    osascript >/dev/null 2>&1 <<APPLESCRIPT &
display dialog "Alcove found a local setup issue.\n\nThe app will still open, and you can run 'agent-runner doctor' in this repo for details." buttons {"OK"} default button "OK"
APPLESCRIPT
  fi
  return 0
}
run_doctor_check

close_origin_terminal_session() {
  # Close only the terminal session that launched this script.
  if [[ -z "$TTY_PATH" || "$TTY_PATH" == "not a tty" ]]; then
    return 0
  fi
  if [[ "$TERM_PROGRAM_NAME" == "Apple_Terminal" ]]; then
    osascript >/dev/null 2>&1 <<APPLESCRIPT
tell application "Terminal"
  set targetTty to "$TTY_PATH"
  repeat with w in windows
    repeat with t in tabs of w
      if tty of t is targetTty then
        close t
        return
      end if
    end repeat
  end repeat
end tell
APPLESCRIPT
    return 0
  fi
  if [[ "$TERM_PROGRAM_NAME" == "iTerm.app" ]]; then
    osascript >/dev/null 2>&1 <<APPLESCRIPT
tell application "iTerm2"
  set targetTty to "$TTY_PATH"
  repeat with w in windows
    repeat with t in tabs of w
      repeat with s in sessions of t
        if tty of s is targetTty then
          close s
          return
        end if
      end repeat
    end repeat
  end repeat
end tell
APPLESCRIPT
  fi
}

WEB_HOST="${AGENT_RUNNER_WEB_HOST:-0.0.0.0}"
WEB_PORT="${AGENT_RUNNER_WEB_PORT:-8765}"
WEB_PASSWORD="${AGENT_RUNNER_WEB_PASSWORD:-}"
APP_URL="${AGENT_RUNNER_URL:-http://127.0.0.1:${WEB_PORT}}"
OPEN_URL="${APP_URL}$([[ "$APP_URL" == *\?* ]] && printf '&' || printf '?')_ar_open=$(date +%s)"
URL_FILE="${SCRIPT_DIR}/.agent-runner/web-url"

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Launching with ${PYTHON_BIN}"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Opening ${APP_URL}"
} >>"$LOG_FILE"

mkdir -p "$(dirname "$URL_FILE")"
printf '%s\n' "$APP_URL" >"$URL_FILE"

server_matches_expected() {
  "$PYTHON_BIN" - "$APP_URL" "$WEB_PASSWORD" "$SCRIPT_DIR" <<'PY'
import base64
import json
import sys
import urllib.error
import urllib.request

url, password, expected_repo = sys.argv[1:4]
request = urllib.request.Request(url.rstrip("/") + "/api/server-info")
if password:
    token = base64.b64encode(f"user:{password}".encode("utf-8")).decode("ascii")
    request.add_header("Authorization", f"Basic {token}")
try:
    with urllib.request.urlopen(request, timeout=1.5) as response:
        payload = json.loads(response.read().decode("utf-8"))
except Exception:
    sys.exit(1)
if payload.get("server_kind") != "agent_runner_web":
    sys.exit(2)
if payload.get("repo_path") != expected_repo:
    sys.exit(3)
sys.exit(0)
PY
}

if server_matches_expected; then
  open "$OPEN_URL"
  close_origin_terminal_session
  exit 0
fi

LAUNCH_CMD=( "$PYTHON_BIN" -m agent_runner web --repo "$SCRIPT_DIR" --host "$WEB_HOST" --port "$WEB_PORT" )
if [[ -n "$WEB_PASSWORD" ]]; then
  LAUNCH_CMD+=( --password "$WEB_PASSWORD" )
fi
nohup env PYTHONPATH="$PYTHONPATH" AGENT_RUNNER_WEB_PASSWORD="$WEB_PASSWORD" "${LAUNCH_CMD[@]}" >>"$LOG_FILE" 2>&1 &
APP_PID="$!"

# Only close the originating terminal once the expected runtime is confirmed.
for _ in $(seq 1 50); do
  if server_matches_expected; then
    open "$OPEN_URL"
    close_origin_terminal_session
    exit 0
  fi
  if ! kill -0 "$APP_PID" 2>/dev/null; then
    echo "Failed to start Alcove web runtime. See ${LOG_FILE} for details." >&2
    exit 1
  fi
  sleep 0.1
done

echo "Alcove web runtime did not become healthy on ${APP_URL}. See ${LOG_FILE} for details." >&2
exit 1
