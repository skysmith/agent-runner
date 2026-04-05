# Alcove

Calm, repo-scoped control for Codex, built around visible artifacts.

Alcove is a browser-first workspace for steering Codex against real local projects with one durable chat per workspace, clear context management, and a right pane that can show the live thing being built. The product is strongest when the left pane is control and the right pane is the artifact.

It is not trying to replace the terminal. It is trying to make high-leverage Codex workflows easier to steer, easier to trust, and easier to pick back up from anywhere.

## Product Shape

Alcove now has two closely related product patterns:

- **Finance Drawer**
  An embedded, page-aware assistant surface that lives inside another product and understands the current route, filters, entities, and visible data.

- **Studio modes**
  Workspace-driven creation surfaces where the right pane shows a live artifact and the left pane steers it through a durable chat.

The long-term studio family is:

- `finance_drawer`
- `studio_game`
- `studio_web`
- `studio_data`
- `studio_docs`

The shared platform idea is simple:

- one durable thread per workspace
- `Clear Chat` resets context without deleting the artifact
- preview state and preview URL are first-class
- publish/share/export flows are explicit
- remix/template flows should reuse the same shell and service contract

## Why this exists

Codex is powerful, but raw terminal loops can still feel fragile or high-friction when you want to:

- keep work tied to a specific repo or artifact
- understand run status at a glance
- see what changed and what checks ran
- manage context intentionally instead of letting chat history sprawl
- kick off or monitor work from your phone
- keep the thing you are building visible while you steer it

Alcove is an opinionated answer to that workflow.

## Core ideas

- One chat per workspace.
  Your project gets a durable working thread instead of a pile of disconnected prompts.

- Clear chat on purpose.
  Reset the workspace thread when context gets stale or too large, without deleting the artifact itself.

- GUI first, not terminal only.
  Use Codex through a browser-first interface with visible status, review output, changed files, and controls like `Stop Safely`.

- Phone companion built in.
  Open the same workspace from your phone to check status, continue the thread, or send the next prompt.

- Artifact visible by default.
  Alcove is best when the right pane shows the live artifact: a game, a website, a document, a table, or an embedded contextual product surface.

- Calm operational visibility.
  Planner, builder, reviewer, checks, artifacts, and build IDs are surfaced so the tool feels legible instead of magical.

## Studio roadmap

The unified Alcove roadmap now treats studios as a product family:

- **Game Studio**
  The first flagship studio. Child-friendly, template-first, managed preview, and one-click publish.

- **Web Studio**
  The broadest developer-facing studio. Chat on the left, live site/app preview on the right.

- **Data Studio**
  Spreadsheet/database understanding first, safe derived transformations second, stronger trust cues throughout.

- **Docs Studio**
  Rendered docs, landing pages, tutorials, and guides beside the conversation, with strong publish/export flows.

Read the unified roadmap here:

- `docs/alcove-unified-studio-roadmap.md`

The older finance-specific roadmap in `docs/alcove.rtf` still matters, but it should now be read as the Finance Drawer branch inside the broader Alcove platform.

## Current runtime

Browser-first runtime:

```bash
agent-runner web
```

Legacy alias (same HTTP runtime, network-first bind default):

```bash
agent-runner serve
```

Desktop launcher:

```bash
agent-runner ui
```

`ui` acts as a thin launcher for the browser-first runtime and opens your browser.

Direct CLI run:

```bash
agent-runner run task.md --check "pytest -q"
```

Inline task mode:

```bash
agent-runner run --task "check this repo for docs and summarize the architecture"
```

By default, `agent-runner run` targets the current directory. Use `--repo` only when you want to point at another repository.

## Current capabilities

Desktop and browser UI support:

- multiple windows
- tabs per window
- one global active run at a time
- one durable chat per workspace
- `Clear Chat` to intentionally reset workspace context
- local voice capture into the prompt box via the `Mic` button
- a short preflight clarifying pass before loop runs when follow-up questions would help
- `Stop Safely` to halt after the current phase and keep your workspace state
- compact status indicator animation in the composer while runs are active
- mobile companion flow at `/m`
- Alcove Studio v1 for game workspaces with managed preview and publish/share URLs

Or without installing the script entrypoint:

```bash
PYTHONPATH=src python -m agent_runner run task.md --repo /absolute/path/to/target/repo
```

## Install (dev)

Prerequisites:

- Python 3.11+
- Codex CLI installed (`codex --version`)
- Codex authenticated (`codex login status` should show ChatGPT login)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Launch and packaging

To launch the UI directly, use:

```bash
./agent-runner.command
```

Create a one-click desktop app icon named `agent-runner`:

```bash
./scripts/install-desktop-icon.sh
```

For faster local iteration, there is also a thin dev-wrapper build:

```bash
./scripts/build-dev-mac-app.sh
```

Build the standalone packaged mac app:

```bash
./scripts/build-packaged-mac-app.sh
```

## Phone workflow

The web runtime serves:

- `/` for the main interface
- `/m` for the compact mobile companion
- `/studio/preview/...` for managed studio previews
- `/play/...` for published studio artifacts

`agent-runner web` binds to `127.0.0.1` by default and prints local/LAN URL details at startup.

`agent-runner serve` keeps `0.0.0.0` default binding for easier LAN access.

Optional password protection is available with `--password` using HTTP basic auth.

`agent-runner.command` defaults to web mode with `0.0.0.0` bind and password `jungleboogie` (override via `AGENT_RUNNER_WEB_PASSWORD`).

Run artifacts save with build-aware folders such as `run-b0001-<utc-stamp>`, and each run includes `run_metadata.json`.

Useful handoff/runbook docs:

- `docs/step-6-smoke-test-and-handoff.md`
- `docs/hosting-handoff.md`

## Command flags

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

Nested `codex exec` calls are run with `--sandbox workspace-write`, so they can write in the target repo directory.

## Task format

The parser expects Markdown headings:

- `# task` required
- `# constraints` optional
- `# success` required
- `# checks` optional

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
