# Handoff: Next Steps (Post Event-Stream Slice)

Prepared: April 4, 2026  
Repo: `/Users/sky/Documents/codex/agent-runner`

## Current Baseline

- Browser-first runtime is active via `agent-runner web`.
- Run supervision lifecycle is implemented (`idle`, `starting`, `running`, `stopping`, `succeeded`, `failed`).
- Event polling endpoint exists: `GET /api/events/since?cursor=...&limit=...`.
- Web UI consumes events and keeps `/api/run-status` as fallback polling.
- Mobile layout has been compacted and keeps composer reachable in viewport.

## Objective

Deliver the next UX/stability slice:

1. replace blocking `alert()` UX with inline toasts + loading labels
2. add one end-to-end browser flow test for desktop and mobile
3. smooth refresh behavior with persisted event cursor/session hints
4. complete Tk handoff to thin launcher (`web` runtime only)

---

## Step 1: Inline Toasts + Action Loading States

### Goal

Improve interaction clarity and remove blocking browser alerts.

### Scope

- Replace `window.alert(...)` usage in `render_web_app()` JS.
- Add small toast region in web shell.
- Add per-action loading labels and temporary disabled states.

### Files

- `src/agent_runner/web_ui.py`

### Implementation Notes

1. Add toast host near composer/footer:
   - `id="toast-stack"` container.
   - non-blocking, auto-dismiss (for example 4-6s).
2. Add helper methods in inline JS:
   - `showToast(message, kind = 'info')`
   - optional `clearToasts()`.
3. Replace all `window.alert(...)` calls with `showToast(...)`.
4. Add action labels while in flight:
   - Send: `Send` -> `Sending...`
   - Stop: `Stop` -> `Stopping...`
   - Retry: `Retry Last` -> `Retrying...`
   - Recover: `Recover` -> `Recovering...`
5. Preserve disabled-guard logic already present in `updateControls()`.

### Acceptance Criteria

- No blocking browser alerts in common flows.
- User always sees visible feedback when action starts/fails/succeeds.
- Buttons revert to normal labels after request completion.

### Verification

- Manually test desktop + mobile:
  - create chat
  - send prompt
  - stop/retry/recover error cases
- Confirm no modal alert appears.

---

## Step 2: Browser E2E Flow Test (Desktop + Mobile)

### Goal

Lock user-critical behavior with a single automated browser flow.

### Scope

- Add one repeatable E2E test script that runs:
  - desktop viewport flow
  - mobile viewport flow
- Validate at least:
  - create/select conversation
  - send prompt
  - run status transitions visible
  - retry/recover controls respond correctly

### Suggested Structure

- Add test script under `tests/verification/` or `scripts/`.
- Use Playwright CLI or Playwright Node API.
- Start `agent-runner web --dry-run` inside test setup for deterministic runs.

### Files (suggested)

- `tests/verification/test_web_e2e_flow.md` (or `.py` harness invoking script)
- `scripts/verify-web-e2e.sh` (optional)

### Acceptance Criteria

- One command validates both desktop and mobile flow in CI/dev.
- Test fails on core regressions (missing controls, broken actions, no status updates).

### Verification Command (target)

```bash
./scripts/verify-web-e2e.sh
```

or equivalent `pytest` wrapper.

---

## Step 3: Persist Cursor/Session Hints for Smoother Refresh

### Goal

Reduce unnecessary full refresh work after page reloads.

### Scope

- Persist event cursor in browser storage.
- Restore cursor at bootstrap to avoid replaying from `0`.
- Persist selected conversation id + workspace id (already in memory only).

### Files

- `src/agent_runner/web_ui.py`

### Implementation Notes

1. Add storage keys, for example:
   - `agent_runner_event_cursor`
   - `agent_runner_conversation_id`
   - `agent_runner_workspace_id`
2. On state changes:
   - update storage.
3. On bootstrap:
   - restore cursor and selected conversation if still valid.
4. If restored conversation is missing:
   - gracefully fall back to first available conversation.

### Acceptance Criteria

- Reload keeps the same selected chat when possible.
- Event polling resumes from recent cursor instead of replaying old events.
- No stale/broken selection behavior after deletes or recoveries.

---

## Step 4: Tk -> Thin Launcher Handoff

### Goal

Eliminate split lifecycle logic. Tk should only launch/open the web runtime.

### Scope

- Remove Tk-owned server lifecycle behavior divergence.
- Ensure packaged launcher behavior mirrors `agent-runner web`.

### Files (likely)

- `src/agent_runner/ui.py`
- `src/agent_runner/packaged_entry.py`
- `agent-runner.command`
- packaging scripts under `scripts/` and `packaging/`

### Implementation Notes

1. Define single startup path:
   - start `agent-runner web` with chosen host/port.
   - open browser URL.
2. Keep Tk shell (if retained) informational only:
   - show URL/status
   - no separate server lifecycle logic.
3. Ensure mac app wrapper and CLI produce consistent URLs and bind behavior.

### Acceptance Criteria

- One-click launcher and CLI both rely on same web runtime path.
- No separate companion-server startup codepath remains as source of truth.
- Mobile/desktop browser show identical state from same server process.

---

## Recommended Execution Order

1. Step 1 (toast/loading UX)  
2. Step 3 (cursor/session persistence)  
3. Step 2 (capture with E2E flow test)  
4. Step 4 (Tk handoff, protected by E2E + existing API tests)

Rationale:
- Step 1 and Step 3 stabilize UX mechanics first.
- Step 2 locks behavior before launcher migration.
- Step 4 is highest blast radius; do it last with tests in place.

---

## Risk Notes

- Event cursor persistence must handle invalid or stale cursor values safely.
- Avoid introducing client-side state as source of truth; server status remains canonical.
- Tk handoff can break packaging if launcher assumptions differ across local vs bundled mode.

---

## Done Definition (for this handoff batch)

- Inline toasts and action-loading labels replace alert-based UX.
- Browser E2E flow validates desktop + mobile critical path.
- Event cursor and conversation selection survive reloads cleanly.
- Tk launcher path is reduced to thin wrapper semantics around `agent-runner web`.
