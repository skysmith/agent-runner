# Step-4: Create One-Click Launch Experience

## Implemented

1. Upgraded `scripts/install-desktop-icon.sh` to create a real desktop app bundle at `~/Desktop/agent-runner.app`.
2. Added a generated emoji-branded app icon (`🕵️`) via Swift + `iconutil` during install.
3. Added runtime launcher wiring in the app bundle so one click runs `agent-runner.command` for this repo.
4. Extended `agent-runner.command` with optional web URL auto-open support (`.agent-runner/web-url` or `AGENT_RUNNER_URL`).

## Result

- Desktop shows a launcher icon for `agent-runner`.
- Clicking the icon starts the app with no manual terminal steps.
- Launcher supports web-target opening automatically when configured.
- Emoji icon branding is visible on the launcher app bundle.
