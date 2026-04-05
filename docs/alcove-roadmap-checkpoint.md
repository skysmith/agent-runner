# Alcove Roadmap Checkpoint

Updated: April 5, 2026  
Repo: `/Users/sky/Documents/codex/agent-runner`

## Current Position

This checkpoint captures where Alcove work stopped in the roadmap and what should happen next.

## Completed In This Slice

1. Branding and naming
- Renamed the roadmap doc to `docs/alcove.rtf`.
- Updated dashboard header and companion labels to `Alcove`.
- Updated browser tab titles to `Alcove` and `Alcove Companion`.

2. Capability model groundwork
- Added conversation-level capability mode:
  - `ask`
  - `ops`
  - `dev`
- Added backend guardrail so `loop` mode is only allowed in `dev` capability mode.
- Added UI controls for switching capability mode in the main dashboard composer.

3. Structured page context model
- Added persistent conversation-level `page_context` storage.
- Added normalization/adapter pipeline in backend:
  - `inventory`
  - `cashflow`
  - `payouts`
  - fallback `generic`
- Added context endpoint support:
  - `GET /api/conversations/{id}/context`
  - `PATCH /api/conversations/{id}/context`

4. Auto-population hooks in dashboard
- Added context input fields near the composer:
  - route
  - entity
  - date window
  - filters
  - visible columns
- Added URL-seeded context support:
  - `ctx_route`
  - `ctx_entity`
  - `ctx_filters`
  - `ctx_columns`
  - `ctx_date_window`
- Added workspace-name route inference for:
  - inventory
  - cash-flow
  - payouts
- Added automatic context persistence on field blur.
- Added automatic context inclusion on send (JSON + multipart paths).

5. Active Context UI
- Added a live `Active context` summary chip near composer.
- Chip updates live from context fields and on inferred/persisted context load.

## Verification Status

Targeted verification completed for this slice:

- `pytest -q tests/test_page_context.py tests/test_service.py tests/test_http_api.py`
- `python3 -m compileall -q src`

## Roadmap Mapping

From the Alcove roadmap, this work advances:

- Phase 1: product boundary groundwork (capability levels introduced)
- Phase 2: shared service contract (API contract for context/mode)
- Phase 3: page-aware context model (initial adapters + structured context)
- Phase 4: ask-mode experience support (safe defaults + contextual UX)

Partial progress has also started toward Phase 10 (UI refinement) via context visibility and Alcove branding.

## Recommended Next Slice

1. Expand page adapters and schemas
- Add richer typed adapters for each finance view with stable keys per page.
- Add strict validation and size limits for `page_context` payloads.

2. Ask mode quality improvements
- Render source/citation hints in answers when context-driven claims are made.
- Improve explainability for metric origin and period comparisons.

3. Ops mode boundary implementation
- Introduce explicit allowlisted operational workflows with confirmations.
- Keep production write actions disabled by default.

4. Dev bridge scaffolding
- Add explicit handoff action to open/export a task into full `agent-runner`.
- Keep direct repo mutation in embedded surface gated and intentional.

## Notes

- The repository currently contains additional in-flight files beyond this Alcove slice.
- This checkpoint is intended to make the Alcove progress and next steps unambiguous before continuing implementation.
