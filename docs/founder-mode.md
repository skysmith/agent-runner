# Founder Mode Loop

This laptop is the live design-and-fix host for `agent-runner`.

## Start the app

```bash
cd /Users/sky/Documents/codex/agent-runner
./scripts/founder-loop.sh start
```

That command will:

- reuse `.venv/bin/python`
- bind the app to `0.0.0.0:8765`
- generate and persist a private password in `.agent-runner/web-password`
- write the preferred preview URL to `.agent-runner/web-url`
  - prefers the Tailscale HTTPS URL when `tailscale serve` is enabled
  - otherwise falls back to the Tailscale IP or local URL
- log output to `.agent-runner/logs/founder-loop.log`

## Check status

```bash
./scripts/founder-loop.sh status
```

## Stop or restart

```bash
./scripts/founder-loop.sh stop
./scripts/founder-loop.sh restart
```

## Founder workflow

1. Keep this repo on the same machine running Codex Desktop.
2. Run the founder loop once.
3. Open the Tailscale or local URL reported by the script.
4. Make small changes locally in Codex Desktop.
5. Refresh the browser and iterate.
6. Commit only when a checkpoint is worth keeping.

## Notes

- If you want a custom password for the session, export `AGENT_RUNNER_WEB_PASSWORD` before starting.
- If you want a different port, export `AGENT_RUNNER_WEB_PORT` before starting.
- `.agent-runner/` is gitignored, so local host details stay out of version control.
