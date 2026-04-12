# Alcove Unified Studio Roadmap

Updated: April 7, 2026  
Repo: `/Users/sky/Documents/codex/lab/scratchpad/agent-runner-fresh-onboarding`

## Product summary

Alcove should evolve into a **family of artifact studios** built on the same workspace, conversation, preview, publish, and handoff infrastructure.

The guiding product idea is:

- the left pane is control
- the right pane is the live artifact
- the workspace is the durable unit of memory and execution

Alcove is strongest when the artifact is visible.

## Product families

Alcove now has two closely related patterns.

### 1. Finance Drawer

The original embedded, page-aware assistant surface.

- lives inside an existing product
- understands route, filters, entities, and visible data
- starts in safe ask mode
- grows into ops mode and a dev bridge
- proves Alcove can live inside another operating environment

### 2. Studio modes

Workspace-driven creation surfaces where the artifact is visible beside the conversation.

Initial studio roadmap:

- `studio_game`
- `studio_web`
- `studio_data`
- `studio_docs`

These should all reuse the same platform ideas rather than becoming separate products with separate architectures.

## Current implementation status

The roadmap has now moved from naming-only direction into a real baseline implementation.

- public Studio creation now covers:
  - `studio_game`
  - `studio_web`
  - `studio_data`
  - `studio_docs`
- the browser shell now treats one durable chat as the default unit per workspace
- workspaces can be imported from folders, renamed, and removed from Alcove without touching repo files on disk
- Studio workspaces share preview/publish metadata and a common right-pane shell
- the packaged macOS app now includes a menu-bar helper, native speech-to-text, and folder import from Finder, the Dock icon, and the toolbar icon
- public web binds now require a password, so remote-serving defaults are harder to misuse

That means several roadmap items have moved from “define this pattern” into “polish and unify this pattern.”

## Shared Studio Platform

Every studio workspace should share a common contract.

### Workspace contract

- one durable thread per workspace
- `Clear Chat` resets context without deleting the artifact
- explicit workspace kind
- artifact metadata
- preview metadata
- publish/export metadata
- template/import origin
- simple mode vs advanced mode

### Common maturity sequence

Each studio should follow the same product rhythm:

1. create or import artifact
2. preview it live
3. request changes in natural language
4. inspect what changed
5. publish, share, or export when appropriate

### Public workspace kinds

Conceptually standardize on:

- `finance_drawer`
- `studio_game`
- `studio_web`
- `studio_data`
- `studio_docs`

Every studio should declare:

- artifact type
- preview model
- publish/export model
- safe default capability boundary
- whether it is read-only, derived-write, or full dev-edit capable

## Studio roadmap

### Game Studio

The first flagship studio.

- child-friendly by default
- template-first plus blank start
- managed preview
- one-click publish
- strong “play, tweak, remix” loop

Why first:

- most differentiated
- most demoable
- best fit for the artifact-visible model

### Web Studio

The second flagship studio.

- chat on the left, live site/app preview on the right
- ideal for landing pages, small apps, UI iteration, and previewable repo work
- should reuse most of the Game Studio preview/publish scaffolding

Status:

- baseline shipped
- now needs polish, stronger share/export surfaces, and clearer preview failure handling

Why second:

- biggest practical audience
- strongest everyday developer use case after games

### Data Studio

Spreadsheet/database understanding first.

- start read-only
- right pane can be table, query, chart, or derived result view
- destructive edits are out of v1
- derived views and exports are in
- trust cues must be stronger than in Game/Web Studio

Requirements:

- show what changed
- distinguish source from derived data
- preserve undo or re-run story
- default to non-destructive output

Status:

- workspace kind and baseline Studio shell shipped
- trust cues, derived-output clarity, and export rules still need maturation

### Docs Studio

Rendered docs and publishing workflows.

- markdown/docs preview beside the conversation
- strong fit for landing pages, tutorials, guides, and docs sites
- publish/export is more important than runtime interactivity
- should benefit from preview/publish infrastructure already built for Web Studio

Status:

- workspace kind and baseline Studio shell shipped
- publish/export expectations and docs-specific polish are still roadmap work

## Finance Drawer roadmap

Finance Drawer remains strategically important and should coexist with Studio work.

It should continue along the existing progression:

1. ask mode
2. database intelligence
3. ops mode
4. dev bridge
5. persistence, safety, and UI refinement

Finance Drawer is not overwritten by Studio work. It is the contextual embedded branch of the same Alcove platform.

## Recommended delivery order

1. Finance Drawer completion to a stable ask/ops/dev-bridge baseline
2. Game Studio as the first full Studio-mode product
3. Web Studio as the next broad developer studio
4. Shared Studio Platform extraction and cleanup
5. Data Studio read-only and safe transformation phase
6. Docs Studio once preview/publish/export flows are mature

This order is intentional:

- Game Studio proves the artifact-visible studio pattern in the strongest possible form
- Web Studio expands that pattern to the broadest developer audience
- Data Studio waits until trust, preview, and export patterns are mature enough
- Docs Studio benefits from the same preview/publish platform built for Web Studio

## Guardrails

To avoid product drift:

- do not let Alcove become a generic chat wrapper
- do not treat every studio as a separate app architecture
- keep the workspace as the core unit
- keep artifact visibility central to the value proposition
- keep Finance Drawer contextual and safe
- prefer strong defaults and explicit publish/export actions over ambiguous automation

## Success criteria

The roadmap is working when:

- product docs clearly distinguish umbrella Alcove from its studio modes
- Finance Drawer remains part of the platform story
- each studio has a one-sentence value proposition
- each studio has a clear right-pane artifact
- each studio has an explicit preview/publish/export stance
- naming is consistent across docs
- no studio is described as a generic assistant sidebar

The bigger product win is not “AI inside the app.” The bigger win is: **the app can work beside the thing being built and understand it in context.**
