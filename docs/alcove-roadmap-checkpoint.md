# Alcove Roadmap Checkpoint

Updated: April 5, 2026  
Repo: `/Users/sky/Documents/codex/agent-runner`

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

## Verification status

Targeted verification completed for the current implemented slices:

- `pytest -q tests/test_page_context.py tests/test_service.py tests/test_http_api.py`
- `python3 -m compileall -q src`

## Roadmap mapping

From the unified roadmap, current work advances:

- Finance Drawer:
  - product boundary groundwork
  - shared service contract
  - page-aware context model
  - ask-mode UX support
- Studio Platform:
  - first workspace-kind implementation
  - preview/publish metadata pattern
  - first artifact-visible studio proof via Game Studio

## Recommended next slice

### 1. Finance Drawer completion

- expand typed page adapters
- improve ask-mode explanation quality
- add stricter validation and limits for page context
- define initial ops allowlist
- add explicit handoff into full Alcove workspace flows

### 2. Web Studio definition

- define `studio_web` product contract
- reuse preview/publish shell from Game Studio
- decide the first template/import model for live web previews

### 3. Shared Studio Platform extraction

- unify workspace-kind metadata rules
- standardize preview/publish/export contracts
- standardize child-friendly/simple-mode vs advanced-mode presentation rules

### 4. Data Studio contract

- define read-only first experience
- define derived-view and export rules
- define trust cues for source vs transformed output

## Notes

- The repository contains in-flight implementation work beyond the original Finance Drawer roadmap.
- This checkpoint is intended to keep the product direction unambiguous while Finance Drawer and Studio work proceed in parallel.
