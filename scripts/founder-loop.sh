#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$ROOT_DIR/.agent-runner"
LOG_DIR="$STATE_DIR/logs"
PID_FILE="$STATE_DIR/founder-loop.pid"
PORT_FILE="$STATE_DIR/founder-loop.port"
PASSWORD_FILE="$STATE_DIR/web-password"
URL_FILE="$STATE_DIR/web-url"
INFO_FILE="$STATE_DIR/founder-loop-info.txt"
LOG_FILE="$LOG_DIR/founder-loop.log"
HOST="${AGENT_RUNNER_WEB_HOST:-0.0.0.0}"
PORT="${AGENT_RUNNER_WEB_PORT:-8765}"
PYTHON_BIN="${AGENT_RUNNER_PYTHON:-$ROOT_DIR/.venv/bin/python}"

mkdir -p "$STATE_DIR" "$LOG_DIR"

ensure_python() {
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Python interpreter not found at $PYTHON_BIN" >&2
    echo "Create the virtualenv first with: python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'" >&2
    exit 1
  fi
}

ensure_password() {
  if [[ -n "${AGENT_RUNNER_WEB_PASSWORD:-}" ]]; then
    printf '%s' "$AGENT_RUNNER_WEB_PASSWORD" > "$PASSWORD_FILE"
    chmod 600 "$PASSWORD_FILE"
    return
  fi
  if [[ -s "$PASSWORD_FILE" ]]; then
    return
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 24 | tr -d '\n' > "$PASSWORD_FILE"
  else
    LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 > "$PASSWORD_FILE"
  fi
  chmod 600 "$PASSWORD_FILE"
}

read_password() {
  cat "$PASSWORD_FILE"
}

read_pid() {
  [[ -f "$PID_FILE" ]] || return 1
  cat "$PID_FILE"
}

is_running() {
  local pid
  pid="$(read_pid 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

port_pid() {
  lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n 1
}

stop_pid_if_present() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.25
  done
  kill -9 "$pid" 2>/dev/null || true
}

reclaim_port() {
  local active_pid=""
  active_pid="$(port_pid || true)"
  if [[ -n "$active_pid" ]]; then
    stop_pid_if_present "$active_pid"
  fi
}

healthcheck() {
  local password
  password="$(read_password)"
  curl -fsS -u phone:"$password" "http://127.0.0.1:${PORT}/api/server-info" >/dev/null
}

resolve_urls() {
  local serve_url=""
  local tailscale_ip=""
  local lan_ip=""
  if command -v tailscale >/dev/null 2>&1; then
    serve_url="$(tailscale serve status 2>/dev/null | awk '/^https:\/\// { print $1; exit }')"
  fi
  if command -v tailscale >/dev/null 2>&1; then
    tailscale_ip="$(tailscale ip -4 2>/dev/null | awk '/^100\./ { print; exit }')"
  fi
  lan_ip="$(python3 - <<'PY'
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.connect(("8.8.8.8", 80))
    ip = sock.getsockname()[0]
except OSError:
    ip = ""
finally:
    sock.close()
print(ip)
PY
)"
  local local_url="http://127.0.0.1:${PORT}"
  local tailscale_url=""
  local lan_url=""
  if [[ -n "$tailscale_ip" ]]; then
    tailscale_url="http://${tailscale_ip}:${PORT}"
  fi
  if [[ -n "$lan_ip" && "$lan_ip" != 127.* ]]; then
    lan_url="http://${lan_ip}:${PORT}"
  fi
  {
    echo "Local URL: $local_url"
    if [[ -n "$lan_url" ]]; then
      echo "LAN URL: $lan_url"
    fi
    if [[ -n "$serve_url" ]]; then
      echo "Tailscale HTTPS URL: $serve_url"
    fi
    if [[ -n "$tailscale_url" ]]; then
      echo "Tailscale URL: $tailscale_url"
    fi
    echo "Password: $(read_password)"
    echo "Log: $LOG_FILE"
  } > "$INFO_FILE"
  if [[ -n "$serve_url" ]]; then
    printf '%s\n' "$serve_url" > "$URL_FILE"
  elif [[ -n "$tailscale_url" ]]; then
    printf '%s\n' "$tailscale_url" > "$URL_FILE"
  else
    printf '%s\n' "$local_url" > "$URL_FILE"
  fi
}

start() {
  ensure_python
  ensure_password
  if is_running && healthcheck; then
    status
    return 0
  fi
  reclaim_port
  rm -f "$PID_FILE"
  local password
  password="$(read_password)"
  : > "$LOG_FILE"
  nohup bash -lc 'cd "$1" && exec env PYTHONPATH="$2" AGENT_RUNNER_WEB_PASSWORD="$3" "$4" -u -m agent_runner web --repo "$1" --host "$5" --port "$6" --password "$3"' _ \
    "$ROOT_DIR" "$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$password" "$PYTHON_BIN" "$HOST" "$PORT" \
    >> "$LOG_FILE" 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"
  printf '%s\n' "$PORT" > "$PORT_FILE"
  for _ in {1..40}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "Founder loop exited during startup. See $LOG_FILE" >&2
      rm -f "$PID_FILE"
      exit 1
    fi
    if healthcheck; then
      resolve_urls
      status
      return 0
    fi
    sleep 0.25
  done
  echo "Founder loop did not become ready in time. See $LOG_FILE" >&2
  exit 1
}

status() {
  ensure_password
  resolve_urls
  echo "Founder loop"
  if is_running && healthcheck; then
    echo "Status: running (pid $(read_pid))"
  elif is_running; then
    echo "Status: starting (pid $(read_pid))"
  else
    echo "Status: stopped"
  fi
  cat "$INFO_FILE"
}

stop() {
  local pid
  pid="$(read_pid 2>/dev/null || true)"
  if [[ -n "$pid" ]]; then
    stop_pid_if_present "$pid"
  fi
  local active_pid=""
  active_pid="$(port_pid || true)"
  if [[ -n "$active_pid" ]]; then
    stop_pid_if_present "$active_pid"
  fi
  if [[ -z "$pid" && -z "$active_pid" ]]; then
    echo "Founder loop is not running"
    rm -f "$PID_FILE"
    return 0
  fi
  rm -f "$PID_FILE"
  echo "Founder loop stopped"
}

restart() {
  stop || true
  start
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart) restart ;;
  status) status ;;
  *)
    echo "Usage: $0 [start|stop|restart|status]" >&2
    exit 1
    ;;
esac
