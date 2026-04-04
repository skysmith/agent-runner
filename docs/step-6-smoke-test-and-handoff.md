# Step-6: Smoke Test And Handoff

Smoke test executed on April 4, 2026 (local repo at `/Users/sky/Documents/codex/lab/scratchpad/agent-runner`).

## What Was Verified

1. Desktop launcher bundle exists and points to this repo:
   - `~/Desktop/agent-runner.app/Contents/Resources/repo-path`
   - Value: `/Users/sky/Documents/codex/lab/scratchpad/agent-runner`
2. Desktop launcher executable resolves to the one-click launcher:
   - `~/Desktop/agent-runner.app/Contents/MacOS/agent-runner`
   - It `exec`s `/Users/sky/Documents/codex/lab/scratchpad/agent-runner/agent-runner.command`
3. Core agent flow works end-to-end via runner in dry-run mode:
   - Command:
     - `PYTHONPATH=src python3 -m agent_runner run --task "Smoke test core flow" --repo . --artifacts-dir .agent-runner/smoke-cli --dry-run`
   - Observed behavior:
     - planner -> builder -> checks -> reviewer -> success
     - auto-detected check executed: `pytest -q=ok`
     - final JSON reported `ok: true`
4. Regression check suite passed:
   - `pytest -q`
   - Result: `14 passed`

## Exact Launch Behavior (Desktop Icon)

When `agent-runner.app` is launched:

1. App executable reads repo path from `Contents/Resources/repo-path`.
2. It changes directory to that repo and runs `agent-runner.command`.
3. `agent-runner.command`:
   - exports `PYTHONPATH="$REPO/src"`
   - opens URL first if configured in `.agent-runner/web-url` or `AGENT_RUNNER_URL`
   - launches UI with:
     - `python3 -m agent_runner ui --repo "$REPO"`

## Fallback Command (Runbook)

If desktop icon launch fails, run this directly from repo root:

```bash
./agent-runner.command
```

If shell launcher execution is blocked, use:

```bash
PYTHONPATH=src python3 -m agent_runner ui --repo .
```

## Known Limitations

1. This session cannot fully validate Finder click-through behavior end-to-end (actual desktop click path still requires manual confirmation in normal GUI use).
