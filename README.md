# Secret Agent: Codex Agent Loop v1.01

Local orchestration loop for Codex CLI that repeatedly plans, builds, verifies, and reviews until a task is complete.

## What this does

- Reads a task spec from `task.md` style input.
- Calls `codex exec` in three prompted roles:
  - planner
  - builder
  - reviewer
- Runs local verification commands after each builder step.
- Retries failing steps with reviewer feedback.
- Writes run artifacts under `.agent-runner/`.
- Assigns a monotonic build number to each run and stores metadata for traceability.

## Prerequisites

- Python 3.11+
- Codex CLI installed (`codex --version`)
- Codex authenticated (`codex login status` should show ChatGPT login)

## Install (dev)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
agent-runner run task.md --check "pytest -q"
```

Desktop UI (paragraph prompt + status + what changed):

```bash
agent-runner ui
```

Desktop UI now supports:

- multiple windows
- tabs per window
- one global active run at a time
- `File -> New Image Gen Tab` to control and open `lab/ai-art` dashboard
- `Settings -> Preferences...` for global provider/model defaults
- `Workspace -> Workspace Options...` for per-workspace override, run mode (`loop` or `message`), and loop count
- local voice capture into the prompt box via the `Mic` button
- a short preflight clarifying pass before loop runs when follow-up questions would help
- `Stop Safely` to halt after the current phase and keep your workspace state
- compact status indicator animation in the composer while runs are active

Inline task mode (no task file):

```bash
agent-runner run --task "check this repo for docs and summarize the architecture"
```

By default, `agent-runner run` targets the current directory. Use `--repo` only when you want to point at another repository.

Or without installing the script entrypoint:

```bash
PYTHONPATH=src python -m agent_runner run task.md --repo /absolute/path/to/target/repo
```

To launch the UI directly, use:

```bash
./agent-runner.command
```

Create a one-click desktop app icon named `agent-runner` (dev wrapper around this checkout):

```bash
./scripts/install-desktop-icon.sh
```

This creates `~/Desktop/agent-runner.app`. Click it once to launch `agent-runner` without terminal steps.
If `.agent-runner/web-url` exists (or `AGENT_RUNNER_URL` is set), the launcher opens that URL first.

For faster local iteration, there is also a thin dev-wrapper build:

```bash
./scripts/build-dev-mac-app.sh
```

This builds `build/macos/agent-runner.app` as a lightweight wrapper around the current repo checkout. You can keep iterating on source in-place, then rebuild or reinstall the wrapper when you want to test the mac app experience.

Build the standalone packaged mac app (friend-shareable artifact):

```bash
./scripts/build-packaged-mac-app.sh
```

This produces `dist/agent-runner.app` with a bundled Python runtime entrypoint. Use this for distribution; keep the desktop wrapper flow as a dev convenience only.

Run artifacts now save with build-aware folders such as `run-b0001-<utc-stamp>`, and each run includes `run_metadata.json`.

Smoke test + handoff notes for launch behavior and fallback commands:

- `docs/step-6-smoke-test-and-handoff.md`

Flags:

- `--max-step-retries N` maximum retries per step (default `2`)
- `--phase-timeout-seconds N` timeout for each planner/builder/reviewer phase (default `240`)
- `--check CMD` repeatable verification command
- `--artifacts-dir PATH` defaults to `.agent-runner`
- `--codex-bin NAME` defaults to `codex`
- `--provider {codex|ollama}` defaults to `codex`
- `--model NAME` defaults to `gpt-5.3-codex`
- `--ollama-host URL` defaults to `http://127.0.0.1:11434`
- `--extra-access-dir PATH` defaults to disabled (`None`)
- `--dry-run` run loop without invoking Codex

If `--check` is not supplied and `# checks` is missing, the runner auto-detects checks from repo files:

- JavaScript/TypeScript: `npm|pnpm|yarn test`, plus `run build` when available
- Python: `pytest -q`
- Rust: `cargo test`
- Go: `go test ./...`

The runner prints phase progress to stderr (planner/builder/reviewer/checks), a final human-readable message, and exits with a concise error if a phase times out or Codex output is invalid.

Nested `codex exec` calls are run with `--sandbox workspace-write`, so they can write in the target repo directory.

## Task format

The parser expects Markdown headings:

- `# task` (required)
- `# constraints` (optional)
- `# success` (required)
- `# checks` (optional; one command per line, supports list syntax)

Example:

```markdown
# task
add inventory forecasting page

# constraints
- use existing prisma schema
- keep UI consistent

# success
- page loads
- forecast uses real data
- tests pass

# checks
npm test
npm run build
```

## Non-goals for v0

- No task queue
- No background daemon
- No multi-agent swarm
- No notification layer
- No long-term memory

## Future Notes

- Consider a native embedded webview host so the `lab/ai-art` dashboard can run inside an `Image Gen` tab instead of opening externally.
- Packaged app smoke-test checklist: `docs/packaged-smoke-test-checklist.md`
