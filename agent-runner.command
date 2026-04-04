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
  if [[ -z "$TERM_PROGRAM_NAME" || -z "$TTY_PATH" || "$TTY_PATH" == "not a tty" ]]; then
    candidates+=("/Library/Frameworks/Python.framework/Versions/3.11/bin/python3")
  fi
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

# Optional web-mode support: if a URL is configured, open it first.
APP_URL="${AGENT_RUNNER_URL:-}"
URL_FILE="${SCRIPT_DIR}/.agent-runner/web-url"
if [[ -z "$APP_URL" && -f "$URL_FILE" ]]; then
  APP_URL="$(head -n 1 "$URL_FILE" | tr -d '\r')"
fi
if [[ -n "$APP_URL" ]]; then
  open "$APP_URL"
fi

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Launching with ${PYTHON_BIN}"
} >>"$LOG_FILE"

nohup env PYTHONPATH="$PYTHONPATH" bash -lc 'exec -a "agent-runner" "$0" -m agent_runner ui --repo "$1"' "$PYTHON_BIN" "$SCRIPT_DIR" >>"$LOG_FILE" 2>&1 &
APP_PID="$!"

# Only close the originating terminal once the app is confirmed running.
sleep 1
if ! kill -0 "$APP_PID" 2>/dev/null; then
  echo "Failed to start agent-runner UI. See ${LOG_FILE} for details." >&2
  exit 1
fi

close_origin_terminal_session
exit 0
