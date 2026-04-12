# Alcove Roadmap Checkpoint

Updated: April 7, 2026  
Repo: `/Users/sky/Documents/codex/lab/scratchpad/agent-runner-fresh-onboarding`

## Current position

This checkpoint now sits inside a broader Alcove product story.

Alcove is no longer just “the finance drawer roadmap” or “a browser-first Codex runner.” It is becoming a platform with:

- **Finance Drawer**
  the embedded, page-aware assistant surface
- **Studio modes**
  artifact-driven workspaces such as Game Studio, Web Studio, Data Studio, and Docs Studio

The new source of truth for that product direction is:

- `docs/alcove-unified-studio-roadmap.md`

The older `docs/alcove.rtf` roadmap still matters, but it should now be read as the Finance Drawer branch inside the larger Alcove platform.

## Completed in this slice

### 1. Naming and product direction groundwork

- Updated product language around `Alcove`
- Established browser-first Alcove surface as the primary runtime
- Introduced the idea that workspace is the durable unit of context and execution

### 2. Capability model groundwork

- Added conversation-level capability modes:
  - `ask`
  - `ops`
  - `dev`
- Added guardrail so `loop` mode is only allowed in `dev`
- Added UI controls for switching capability mode in the main composer

### 3. Structured page context model

- Added persistent conversation-level `page_context` storage
- Added normalization/adapter pipeline for:
  - `inventory`
  - `cashflow`
  - `payouts`
  - fallback `generic`
- Added context endpoints:
  - `GET /api/conversations/{id}/context`
  - `PATCH /api/conversations/{id}/context`

### 4. Auto-population and active-context UX

- Added context input fields near the composer:
  - route
  - entity
  - date window
  - filters
  - visible columns
- Added URL-seeded context support
- Added automatic context persistence on blur
- Added automatic context inclusion on send
- Added live `Active context` summary chip near the composer

### 5. Studio platform beginning

- Added the first Alcove Studio workspace type:
  - `studio_game`
- Added managed preview and publish/share URLs for Studio game workspaces
- Proved that the workspace + preview + publish pattern can live inside the existing Alcove shell

### 6. Shared Studio Platform expansion

- Added Studio creation flows for:
  - `studio_web`
  - `studio_data`
  - `studio_docs`
- Standardized public workspace kind handling across service, HTTP API, and browser UI
- Reused the same preview/publish shell across Studio workspaces instead of introducing separate app surfaces
- Added repo import heuristics so imported folders can map into standard workspaces or Studio kinds

### 7. Workspace contract and browser shell refinement

- Locked browser workspaces to one durable chat per workspace
- Added `Rename` and non-destructive `Remove` controls for workspaces
- Added drawer-based workspace metadata instead of always-visible row clutter
- Simplified the home/workspace browser so the list, preview pane, and resize split stay stable
- Simplified the default Studio surface so it centers the artifact preview instead of always-visible share/link chrome

### 8. Packaged macOS runtime and native bridge work

- Added a packaged macOS launcher with menu-bar helper coordination
- Added wrapper-backed native speech transcription for the desktop `Mic` button
- Added folder import via Finder/Open With, Dock drag-drop, and menu-bar icon drag-drop
- Updated the menu-bar helper to open the current workspace folder in Finder
- Tightened desktop affordances around status, workspace targeting, and local browser launch behavior

### 9. Safety and foolproofing pass

- Hardened workspace and conversation persistence against unsafe IDs and malformed JSON payloads
- Hardened app settings loading so invalid values fall back cleanly instead of crashing or silently drifting
- Added request/upload path validation for local web endpoints
- Required `--password` whenever `alcove ui`, `alcove web`, or `alcove serve` bind off localhost

## Verification status

Targeted verification completed for the current implemented slices:

- `pytest -q tests/test_page_context.py tests/test_service.py tests/test_http_api.py`
- `python3 -m compileall -q src`
- `pytest -q tests/test_cli.py tests/test_conversation_store.py tests/test_http_api.py tests/test_macos_wrapper.py tests/test_packaged_entry.py tests/test_service.py tests/test_settings_store.py tests/test_web_ui.py`
- `swiftc -typecheck packaging/macos/AlcoveMenuBar.swift -framework AppKit`
- `swiftc -typecheck packaging/macos/AlcoveNativeSpeech.swift -framework AVFoundation -framework Speech`
- `bash scripts/build-dev-mac-app.sh`
- `bash scripts/build-packaged-mac-app.sh`

## Roadmap mapping

From the unified roadmap, current work advances:

- Finance Drawer:
  - product boundary groundwork
  - shared service contract
  - page-aware context model
  - ask-mode UX support
- Studio Platform:
  - multiple public workspace kinds
  - one-chat-per-workspace contract
  - rename/remove/import browser management
  - preview/publish metadata pattern
  - artifact-visible studio proof via Game, Web, Data, and Docs shells
- Desktop runtime:
  - packaged macOS launcher
  - native speech input
  - Dock/menu-bar folder import
  - safer public bind defaults

## Recommended next slice

### 1. Finance Drawer completion

- expand typed page adapters
- improve ask-mode explanation quality
- add stricter validation and limits for page context
- define initial ops allowlist
- add explicit handoff into full Alcove workspace flows

### 2. Studio platform polish

- add clearer share/export surfaces that do not crowd the default Studio preview
- finish native macOS app-menu consolidation for things like `Alcove > Settings…`
- persist and restore more view/layout preferences intentionally instead of implicitly
- keep simplifying workspace and Studio chrome without losing discoverability

### 3. Data and Docs Studio maturity

- strengthen trust cues for source vs transformed data
- define export/publish expectations for Docs and Data Studio
- make preview failure states more legible than raw file/server errors

### 4. Shared Studio Platform extraction

- finish standard preview/publish/export contracts across all studio kinds
- keep shared desktop/browser behaviors aligned instead of diverging by surface
- keep workspace memory, artifact metadata, and publish state canonical across the platform

## Notes

- The repository contains in-flight implementation work beyond the original Finance Drawer roadmap.
- This checkpoint is intended to keep the product direction unambiguous while Finance Drawer and Studio work proceed in parallel.
