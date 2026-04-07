#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$(command -v "$candidate")"
      break
    fi
  done
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "Could not find Python 3.11+." >&2
  exit 1
fi

VENV_DIR="${SCRIPT_DIR}/.venv"
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip >/dev/null
python -m pip install -e ".[dev]"

printf '%s\n' "Setup complete."
printf '%s\n' "Next:"
printf '  %s\n' "./alcove.command"
printf '  %s\n' "Local URL: http://127.0.0.1:8765/"
printf '  %s\n' "Health check: alcove doctor"
if command -v tailscale >/dev/null 2>&1; then
  printf '  %s\n' "Tailscale detected: phone access can be enabled through Alcove Settings."
else
  printf '  %s\n' "Tailscale not detected: desktop use still works normally."
fi
