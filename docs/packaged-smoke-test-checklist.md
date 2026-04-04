# Packaged App Smoke Test Checklist

Run this checklist for `dist/agent-runner.app` after `./scripts/build-packaged-mac-app.sh`.

## Startup

- Launch `dist/agent-runner.app` from Finder.
- Confirm the app opens without using `PYTHONPATH` or `agent-runner.command`.
- Confirm the app launches when current working directory is not the repo root.

## Identity and Branding

- Confirm macOS menu bar app identity is `agent-runner` (not `Python`).
- Confirm `Help -> About agent-runner` shows app branding and build/version label.

## Runtime Behavior

- Confirm `File -> Safe Reload` reopens the packaged app and returns to the UI.
- Confirm `Settings -> Preferences...` opens and saves successfully.
- Confirm settings persist after restart.

## Paths and Persistence

- Confirm settings file is created in `~/Library/Application Support/agent-runner/app-settings.json`.
- Confirm run artifacts are written under `~/Library/Application Support/agent-runner/artifacts`.
- Confirm no write is required to the source checkout for packaged startup.

## Optional Integrations

- Confirm missing local extras (for example `ai-art`) do not block launch.
- Confirm the app remains usable even when optional integrations are absent.
