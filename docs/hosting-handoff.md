# Hosting Handoff

Prepared: April 5, 2026  
Repo: `/Users/sky/Documents/codex/agent-runner`

## Current Hosted Location

- Network: Tailscale (private tailnet)
- Host: `100.81.18.26` (ck-server machine)
- URL: `http://100.81.18.26:8766/`
- Auth: HTTP Basic Auth is enabled
  - Current username: `phone`
  - Current password: `jungleboogie`

Quick checks:

- Unauthenticated request returns `401 Authentication required`
- Authenticated `GET /api/run-status` returns `200` with JSON

## Runtime On Host

- Process manager: user `launchd` agent
- Label: `com.sky.agent-runner-hosted`
- Plist: `/Users/sky/Library/LaunchAgents/com.sky.agent-runner-hosted.plist`
- App dir: `/Users/sky/Library/Application Support/agent-runner-hosted`
- Port: `8766`
- Provider default: `ollama`
- Model default: `llama2:latest`

## Why `Errno 2: 'codex'` Happened

That host did not have a `codex` binary on PATH. When provider was `codex`, runs failed with:

- `[Errno 2] No such file or directory: 'codex'`

The hosted service was switched to `--provider ollama --model llama2:latest`, which matches the machine's available runtime.

## Source Of Truth For Ops

Primary ops scripts and machine docs live in:

- `/Users/sky/Documents/codex/business/ck-server`

Relevant files:

- `docs/AGENT_RUNNER_HOSTED.md`
- `scripts/agent-runner-hosted.sh`
- `scripts/deploy-agent-runner-hosted.sh`
- `docs/MACHINE_ACCESS.md`

## Deploy / Update Flow

From `ck-server` repo:

```bash
./scripts/deploy-agent-runner-hosted.sh
```

This script syncs this repo to the host app directory, reapplies host compatibility tweaks, and restarts the launchd service.

Useful service commands:

```bash
./scripts/agent-runner-hosted.sh status
./scripts/agent-runner-hosted.sh restart
./scripts/agent-runner-hosted.sh logs
```

## Local UI vs Hosted UI

- Local development UI (this repo): run `agent-runner web` locally.
- Hosted shareable UI: use the Tailscale URL on `8766` with Basic Auth.

Both desktop and mobile clients should use the same hosted URL; mobile layout is handled by responsive UI behavior in the web app.
