# Step-7: Verify End-to-End Behavior

Verification executed on April 4, 2026 (repo: `/Users/sky/Documents/codex/lab/scratchpad/agent-runner`).

## Scope

Validated requested combined behavior set:

1. Launcher closes only the originating terminal session.
2. `Update` badge appears when a new local commit is detected.
3. Clicking `Update` does not interrupt active prompt runs; reload is queued and applied when idle.
4. Tab bar is hidden when only one tab is open.

## Checks Run

1. Combined end-to-end session checks (single test session path):

```bash
pytest -q tests/test_step7_end_to_end_checks.py
```

Result: `2 passed`.

What this explicitly validates in one flow:

- Launcher close script emits AppleScript targeted to only the originating TTY tab/session (`targetTty` + `if tty of t is targetTty then close t`).
- UI tab bar hides for one tab and reappears when multiple tabs are present.
- Commit-head change surfaces update availability.
- Clicking update during an active run queues reload (no interruption), and reload applies immediately after run completion.

2. Targeted behavior tests:

```bash
pytest -q tests/test_update_signal.py tests/test_ui_reload_behavior.py tests/test_ui_tab_bar_visibility.py
```

Result: `8 passed`.

3. Regression sweep:

```bash
pytest -q
```

Result: `43 passed`.

## Behavior Mapping To Requirements

1. Launch-close behavior: pass
- Script starts UI process, confirms process is alive, then calls close logic for the originating TTY only.

2. Commit-triggered `Update` badge: pass
- Commit head change detection is covered by `tests/test_update_signal.py`.

3. Safe reload semantics (non-interrupting): pass
- Reload queuing and deferred reload on run completion are covered by `tests/test_ui_reload_behavior.py`.

4. Single-tab tab-bar hiding: pass
- Visibility toggling for one-tab state is covered by `tests/test_ui_tab_bar_visibility.py`.

## Verification Notes For Handoff

1. This step now includes an explicit one-session integration check (`tests/test_step7_end_to_end_checks.py`) so the requested behaviors are proven together, not only as isolated unit checks.
2. The launcher close-scope verification is captured via PTY execution with stubbed `osascript`, which validates the exact AppleScript contract used in macOS Terminal close behavior.
3. Reload safety remains non-interrupting by construction and verification: update click while active run sets queue state only, then queued reload is executed after `finish_workspace_run`.
