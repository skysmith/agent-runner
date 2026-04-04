# Step-2: Define Simple Usability Layout

## Goal
Define a minimal, sleek, "just works" single-screen layout for `agent-runner` using the design bible principles (calm, typography-first, lightly segmented, low-friction).

## Screen Structure (Wireframe Level)

```
+----------------------------------------------------------------------------------+
| agent-runner  🤖                                                                 |
| Simple Codex Runner                                                              |
+----------------------------------------------------------------------------------+
| Prompt                                                                           |
| [ Multiline paragraph input (primary focus, plain-language request)           ] |
| [                                                                            ]  |
| [                                                                            ]  |
| [ Run ]                                                                         |
+---------------------------------------------+------------------------------------+
| Status                                      | What Changed                       |
| State: Idle / Running / Reviewing / Done    | - 10:31 Updated src/...           |
| Current step: step-2                        | - 10:28 Added docs/...            |
| Last run: 10:31 AM                          | - 10:25 Check: pytest passed      |
| Checks: 2 passed, 0 failed                  |                                    |
| Artifacts: .agent-runner/run-...            | (show latest 5 entries)           |
+---------------------------------------------+------------------------------------+
```

## Named Sections
1. `App Header`
- Title: `agent-runner`
- Fun emoji branding for icon direction and identity continuity.
- One-line subtitle: "Simple Codex Runner."

2. `Prompt Panel` (Primary)
- Paragraph-style multiline prompt area (6-10 visible lines).
- Placeholder text: "Describe what you want in plain language."
- Single primary action: `Run`.
- No advanced options required to run.

3. `Status Panel` (Always Visible)
- `State` (Idle, Running, Reviewing, Done, Needs Attention).
- `Current step`.
- `Last run`.
- `Checks` summary.
- `Artifacts` path for transparency.

4. `What Changed Panel` (Compact Breakdown)
- Reverse-chronological list of concise change entries.
- Each entry: timestamp + one-line summary.
- Show last 5 items by default.

## Primary User Flow (One Obvious Path)
1. User opens `agent-runner`.
2. Cursor is already in the paragraph prompt input.
3. User enters request text.
4. User clicks `Run` (or presses Cmd/Ctrl+Enter).
5. User watches `Status` update live.
6. User reads `What Changed` for concrete output summary.

## No-Training "Just Works" Rules
- No setup wizard before first run.
- No required advanced controls for main flow.
- One primary button only (`Run`) in the main action area.
- Clear empty-state and status language in plain English.
- Thin dividers and typography hierarchy over heavy card UI.
- Neutral palette dominance with sparse semantic accents:
  - `#f5f5f3`, `#fcfcfa`, `#dddcd7`, `#2d2c29`
  - success accent `#3f644b`, caution accent `#a66a3f`

## Step-2 Done Criteria Mapping
- Wireframe-level layout documented with named sections: complete.
- Primary flow is one obvious path (`enter prompt -> run -> view status/changes`): complete.
- No advanced controls required for main flow: complete.
