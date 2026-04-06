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
display dialog "Alcove found a local setup issue.\n\nThe app will still open, and you can run 'alcove doctor' in this repo for details." buttons {"OK"} default button "OK"
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
DEFAULT_WEB_PORT="${AGENT_RUNNER_WEB_PORT:-8765}"
WEB_PASSWORD="${AGENT_RUNNER_WEB_PASSWORD:-}"
EXPLICIT_APP_URL="${AGENT_RUNNER_URL:-}"
STATE_DIR="${SCRIPT_DIR}/.agent-runner"
URL_FILE="${STATE_DIR}/web-url"

mkdir -p "$STATE_DIR"

read_saved_url() {
  if [[ -n "$EXPLICIT_APP_URL" ]]; then
    printf '%s\n' "$EXPLICIT_APP_URL"
    return 0
  fi
  if [[ -f "$URL_FILE" ]]; then
    local saved_url
    saved_url="$(tr -d '\r' < "$URL_FILE")"
    if [[ "$saved_url" == http://* || "$saved_url" == https://* ]]; then
      printf '%s\n' "$saved_url"
      return 0
    fi
  fi
  printf 'http://127.0.0.1:%s\n' "$DEFAULT_WEB_PORT"
}

url_port() {
  "$PYTHON_BIN" - "$1" "$DEFAULT_WEB_PORT" <<'PY'
from __future__ import annotations

import sys
from urllib.parse import urlparse

url = sys.argv[1].strip()
fallback = int(sys.argv[2])
try:
    parsed = urlparse(url)
    port = parsed.port
except Exception:
    port = None
print(port or fallback)
PY
}

pick_available_port() {
  "$PYTHON_BIN" - "$WEB_HOST" "$1" <<'PY'
from __future__ import annotations

import socket
import sys

host = sys.argv[1]
start_port = int(sys.argv[2])

for candidate in range(start_port, start_port + 25):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, candidate))
        except OSError:
            continue
    print(candidate)
    sys.exit(0)

sys.exit(1)
PY
}

write_current_url() {
  printf '%s\n' "$1" >"$URL_FILE"
}

build_open_url() {
  local base_url="$1"
  printf '%s%s_ar_open=%s\n' "$base_url" "$([[ "$base_url" == *\?* ]] && printf '&' || printf '?')" "$(date +%s)"
}

server_matches_expected() {
  local candidate_url="$1"
  "$PYTHON_BIN" - "$candidate_url" "$WEB_PASSWORD" "$SCRIPT_DIR" <<'PY'
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

PREFERRED_URL="$(read_saved_url)"
if server_matches_expected "$PREFERRED_URL"; then
  write_current_url "$PREFERRED_URL"
  OPEN_URL="$(build_open_url "$PREFERRED_URL")"
  open "$OPEN_URL"
  close_origin_terminal_session
  exit 0
fi

PREFERRED_PORT="$(url_port "$PREFERRED_URL")"
LAUNCH_PORT="$PREFERRED_PORT"
if [[ -z "$EXPLICIT_APP_URL" && -z "${AGENT_RUNNER_WEB_PORT:-}" ]]; then
  if ! LAUNCH_PORT="$(pick_available_port "$PREFERRED_PORT")"; then
    echo "Could not find an open port for the Alcove web runtime." >&2
    exit 1
  fi
fi

APP_URL="${EXPLICIT_APP_URL:-http://127.0.0.1:${LAUNCH_PORT}}"
OPEN_URL="$(build_open_url "$APP_URL")"

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Launching with ${PYTHON_BIN}"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Opening ${APP_URL}"
  if [[ "$LAUNCH_PORT" != "$PREFERRED_PORT" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Port ${PREFERRED_PORT} was unavailable; using ${LAUNCH_PORT}"
  fi
} >>"$LOG_FILE"

write_current_url "$APP_URL"

LAUNCH_CMD=( "$PYTHON_BIN" -m agent_runner web --repo "$SCRIPT_DIR" --host "$WEB_HOST" --port "$LAUNCH_PORT" )
if [[ -n "$WEB_PASSWORD" ]]; then
  LAUNCH_CMD+=( --password "$WEB_PASSWORD" )
fi
nohup env PYTHONPATH="$PYTHONPATH" AGENT_RUNNER_WEB_PASSWORD="$WEB_PASSWORD" "${LAUNCH_CMD[@]}" >>"$LOG_FILE" 2>&1 &
APP_PID="$!"

# Only close the originating terminal once the expected runtime is confirmed.
for _ in $(seq 1 50); do
  if server_matches_expected "$APP_URL"; then
    write_current_url "$APP_URL"
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
