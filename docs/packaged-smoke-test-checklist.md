# Packaged App Smoke Test Checklist

Run this checklist for `dist/agent-runner.app` after `./scripts/build-packaged-mac-app.sh`.

Standardize packaged build verification on port `8765`. Do not override `AGENT_RUNNER_WEB_PORT` for the normal smoke-test path.

## Startup

- Launch `dist/agent-runner.app` from Finder.
- Confirm the app opens without using `PYTHONPATH` or `agent-runner.command`.
- Confirm the app launches when current working directory is not the repo root.
- Confirm the packaged app serves on `http://127.0.0.1:8765/`.

## Identity and Branding

- Confirm macOS menu bar app identity is `agent-runner` (not `Python`).
- Confirm `Help -> About agent-runner` shows app branding and build/version label.

## Runtime Behavior

- Confirm `File -> Safe Reload` reopens the packaged app and returns to the UI.
- Confirm `Settings -> Preferences...` opens and saves successfully.
- Confirm settings persist after restart.

## Native Wrapper Integrations

- Confirm a native macOS notification appears on run success.
- Confirm a native macOS notification appears on run failure or follow-up-required state.
- Confirm the menu bar item appears and can:
  - open Alcove
  - show current run state
  - stop a run
  - copy the local URL
  - copy the phone URL when available
- Confirm Finder Quick Action can open a selected repo folder in Alcove.
- Confirm long-running execution holds a power management assertion only while the run is active.

## Paths and Persistence

- Confirm settings file is created in `~/Library/Application Support/agent-runner/app-settings.json`.
- Confirm run artifacts are written under `~/Library/Application Support/agent-runner/artifacts`.
- Confirm no write is required to the source checkout for packaged startup.
- If local wrapper auth is enabled, confirm credentials are stored in Keychain once that integration ships.

## Optional Integrations

- Confirm missing local extras (for example `ai-art`) do not block launch.
- Confirm the app remains usable even when optional integrations are absent.
