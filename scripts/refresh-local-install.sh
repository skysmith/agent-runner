#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

"${SCRIPT_DIR}/scripts/setup-dev.sh"
"${SCRIPT_DIR}/scripts/install-desktop-icon.sh"

printf '%s\n' "Refresh complete."
printf '  %s\n' "${HOME}/Applications/Alcove.app"
if [[ -d "${HOME}/Desktop" ]]; then
  printf '  %s\n' "${HOME}/Desktop/Alcove.app"
fi
