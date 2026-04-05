# Web Migration Plan

## Goal

Move `agent-runner` from a Tk desktop app with a separate companion UI to a single local web application:

- one backend process
- one HTTP API
- one browser UI that works on desktop and phone
- no separate companion-server lifecycle
- no Tk-specific process and environment issues

## Why This Is Worth It

The current system has three layers that create operational drag:

1. Tk desktop UI
2. local background service/state
3. separate HTTP companion UI

That split causes repeated issues:

- desktop process environment can differ from shell environment
- companion server may or may not be running
- desktop and phone can show different state
- localhost, LAN, and Tailscale URLs all need separate handling
- browser/mobile debugging is harder because the primary UX lives in Tk

A web-first design removes most of that.

## What To Keep

These parts are already good building blocks and should stay:

- `src/agent_runner/service.py`
- `src/agent_runner/conversation_store.py`
- `src/agent_runner/run_coordinator.py`
- `src/agent_runner/codex_client.py`
- `src/agent_runner/providers.py`
- `src/agent_runner/context_assembler.py`
- `src/agent_runner/runner.py`

These parts should become the foundation of the web app:

- `src/agent_runner/http_api.py`
- the existing workspace / conversation / message routes

## What To Replace

These parts should stop being the primary UX:

- `src/agent_runner/ui.py`
- Tk menus, windows, panes, and widget state
- the current “desktop app plus companion page” mental model

The current companion UI is useful as a bootstrap, but it should become the main app shell rather than a sidecar/mobile-only surface.

## Target Architecture

### Backend

A single local Python server process owns:

- HTTP routes
- run lifecycle
- workspace and conversation persistence
- Codex / Ollama execution
- status polling or streaming

Suggested direction:

- keep the current stdlib server first for low churn
- optionally move to FastAPI later if you want typed request models, SSE, and cleaner route composition

### Frontend

A single browser UI serves:

- workspace list
- conversation rail
- thread view
- composer
- run status
- settings
- image-gen links / external integrations

Suggested direction:

- start with server-rendered HTML + small vanilla JS
- only introduce React/Vite if the interaction model becomes too heavy

That keeps deployment simple and avoids adding a full JS build tool before the UX has stabilized.

## Recommended End State

### CLI

Keep:

- `agent-runner run`
- `agent-runner serve`

Add or redefine:

- `agent-runner web`
  Starts the local server and prints/opens the browser URL.

Possible future aliases:

- `agent-runner open`
- `agent-runner dev`

### Desktop Wrapper

If you still want a one-click app icon on macOS:

- keep the wrapper app
- have it launch the local web server
- open the browser to the local web URL

That preserves easy launch without keeping Tk in the critical path.

## Phased Migration

## Phase 1: Promote HTTP API To Primary Runtime

### Goal

Make the existing HTTP layer the main product path.

### Work

- rename the current companion UI concept to simply “web UI”
- make `agent-runner serve` the canonical UI runtime
- improve `http_api.py` structure so routes and HTML rendering are easier to extend
- add a root page intended for desktop, not just mobile
- keep current JSON endpoints stable

### Deliverable

You can do all normal usage from the browser without opening Tk.

## Phase 2: Build A Real Desktop Web UI

### Goal

Replace the narrow mobile layout with a full desktop-capable interface.

### Work

- create a two-column layout:
  - left rail: workspaces + conversations
  - main area: thread + composer + status
- add settings page or settings drawer
- add “new conversation”, rename, delete, and run controls
- replace full-page reload behavior with polling or targeted fetch updates

### Deliverable

The browser UI can fully replace the existing Tk conversation workflow.

## Phase 3: Add Live Status Updates

### Goal

Stop relying on refresh-driven status updates.

### Work

- start with `/api/run-status` polling every 1-2 seconds
- optionally add Server-Sent Events later:
  - `/api/events`
  - status events
  - conversation updates
  - completion/error events

### Deliverable

Desktop and phone stay in sync without weird stale yellow/red indicators.

## Phase 4: Move Settings And Controls To Web

### Goal

Remove the last Tk-only controls.

### Work

- expose app settings via HTTP routes
- expose workspace overrides via HTTP routes
- expose provider/model selection via web forms
- expose stop-run and status controls in-browser

### Deliverable

No core workflow requires the Tk app.

## Phase 5: Retire Tk

### Goal

Make Tk optional or remove it completely.

### Options

Option A:
- keep Tk only as a legacy launcher for one release

Option B:
- replace Tk with a thin launcher script / packaged app wrapper

Option C:
- remove Tk entirely and keep only CLI + browser UX

### Recommended choice

Option B is the cleanest transition.

## Backend Refactor Plan

## 1. Split Route Logic From Rendering

Current `http_api.py` mixes:

- route matching
- data access
- HTML generation
- inline CSS/JS

Refactor into:

- `http_api.py`
  server + routing
- `web_views.py`
  HTML page rendering
- `web_assets.py` or static files
  CSS/JS payloads

This makes the browser UI easier to iterate on.

## 2. Add Explicit Web View Models

Instead of passing raw service payloads straight into HTML, define small helper serializers:

- workspace summary
- conversation summary
- thread detail
- run status summary

That will make the eventual move to a richer frontend much easier.

## 3. Keep Service Layer As The Source Of Truth

Do not move business logic into the browser or route layer.

The service should remain responsible for:

- workspace selection
- conversation persistence
- message sending
- run coordination
- stop requests
- summaries

## Frontend Plan

## First Pass

Use plain HTML/CSS/JS:

- fetch JSON from existing routes
- render with lightweight templates
- poll for status and updated thread content

Why:

- zero build tooling
- easier debugging
- fastest migration path

## Second Pass

If needed later, move to a small SPA:

- React + Vite
- or server-rendered templates + HTMX-style interaction

Only do this after the information architecture is settled.

## URL Structure

Recommended browser URLs:

- `/`
  app shell
- `/workspaces/:workspace_id`
  workspace-focused view
- `/conversations/:conversation_id`
  direct thread view
- `/settings`
  app settings

Keep JSON API namespaced:

- `/api/workspaces`
- `/api/conversations/...`
- `/api/run-status`
- `/api/settings`

## State Model

The browser should treat the backend as authoritative.

Do:

- fetch state from the server
- submit actions via POST/PATCH/DELETE
- update from polling or events

Avoid:

- duplicating run state heavily in the client
- browser-only assumptions about active workspace state

## Security / Exposure Model

For a local-first product:

- default to `127.0.0.1`
- optionally allow `0.0.0.0` with an explicit flag
- if exposed on LAN/Tailscale, add a lightweight auth token before wider sharing

Recommended future addition:

- `AGENT_RUNNER_WEB_TOKEN`
- browser sends token via header or query on first bootstrap

That is especially useful if the app can trigger shell commands or Codex runs.

## Risks

### Risk 1: Route Layer Becomes Another UI Monolith

Mitigation:

- split route, render, and asset concerns early

### Risk 2: Browser UI Reimplements Business Logic

Mitigation:

- keep orchestration in `service.py`

### Risk 3: Overbuilding The Frontend Too Early

Mitigation:

- start with server-rendered HTML and polling

### Risk 4: Mobile/Desktop UX Diverges Again

Mitigation:

- one responsive web app, not separate desktop and companion UIs

## Proposed First Implementation Slice

If we start coding this migration, the first slice should be:

1. Add a desktop-oriented browser page at `/`
2. Reuse existing JSON endpoints
3. Add polling for:
   - thread updates
   - run status
4. Support:
   - list workspaces
   - list conversations
   - open thread
   - send message
   - stop run
5. Keep Tk only as a launcher during the transition

This is the smallest slice that proves the architecture.

## Suggested Milestones

### Milestone 1

Browser UI can replace the current companion page.

### Milestone 2

Browser UI can replace the Tk conversation workflow.

### Milestone 3

Desktop wrapper opens browser-based app by default.

### Milestone 4

Tk no longer required for normal usage.

## Recommendation

The best migration is not “rewrite everything as a SPA.”

The best migration is:

- keep the service/orchestration core
- promote the HTTP server to the main runtime
- build one responsive browser UI
- demote Tk to a launcher
- remove Tk once the browser UI fully covers the workflow

That path gives you a simpler product with much less operational weirdness and the least wasted work.
