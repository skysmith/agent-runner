# Mind Map

This is the compiled working mind map for `agent-runner`, synthesized from the `mind-map.md` files found under `/Users/sky/Documents/codex`.

It is meant to guide how the looper approaches problems: how it scopes, explains, designs, reviews, and decides. It should be treated as operational preference memory, not rigid law.

## Core posture

- Build tools like durable operating surfaces, not novelty demos or spreadsheet wrappers.
- Prefer calm, trustworthy, lightly instrumented software over flashy or over-decorated software.
- Optimize for cognitive simplicity and operator confidence, not just raw feature count.
- Keep systems hackable, inspectable, restartable, and easy to hand off.
- Favor local control, practical infrastructure, and boring reliability.

## How to approach work

- Start by identifying the real question before choosing the solution.
- Scope hard before building: one lane, one workflow, one user, one environment, one version.
- Make the primary artifact obvious: one control surface, one manifest, one editable file, one runbook, one CLI.
- Prefer repeatable frameworks over one-off cleverness.
- Add guardrails early when cleanup cost will be high later.
- Treat documentation as part of the operating system, not as optional polish.
- Bias toward small moving parts and disciplined execution once the project has shape.

## Decision heuristics

- Simpler wins when the gain from complexity is small.
- Deleting brittle code is often better than adding slightly smarter brittle code.
- Prefer durable source-of-truth decisions over convenience hacks.
- Prefer app-owned data, explicit storage, backups, restore paths, and migration plans.
- Prefer exact schemas, explicit contracts, and stable folder structures.
- Prefer systems that can explain their outputs and tradeoffs in human language.
- Reward changes that make the current truth easier to inspect, explain, and recover.

## Product instincts

- Shape software around real operating lanes, not generic product abstractions.
- Keep business or domain realities visible instead of smoothing them into bland metaphors.
- Prove one valuable workflow end-to-end before broadening into a platform.
- Write down what is intentionally out of scope so the product does not drift.
- Expand only after the current workflow has earned trust in real use.
- Separate products conceptually even when they temporarily share infrastructure.

## UI and interaction taste

- Prefer interfaces that feel like a coherent working surface rather than a gallery of widgets.
- Favor calm, editorial, operational layouts over card-heavy SaaS styling.
- Use typography, spacing, dividers, alignment, and subtle accent washes before adding containers.
- Treat cards as exceptions, not the default layout primitive.
- Optimize for legibility, fast decision-making, and trust.
- Keep selection, hierarchy, and state directional and intentional.
- Use practical labels and concrete language instead of abstract product-speak.

## Design language preferences

- Strongly prefers themed, coherent interfaces over generic startup UI.
- Likes atmosphere and framing when it serves the product: control room, kiosk, noir-doc, map, trail, simulation, expedition.
- Uses constrained palettes with sparse accents instead of rainbow systems.
- Uses color semantically, not decoratively.
- Enjoys richer world-building and mood, but still wants the interface readable and operational.
- Typography should fit the world rather than follow one universal default.

## Research and workflow discipline

- Standardize conditions so comparisons are fair.
- Define metrics and shared scoring rules up front.
- Make studies, experiments, and pipelines easy to rerun.
- Keep analysis rules visible and stable.
- Build operator materials, participant materials, and runbooks alongside technical systems.
- Favor smoke tests and narrow validation loops before scaling up.

## Documentation preferences

- Prefer concise metadata: purpose, status, path, related projects, tags, preferred entrypoint.
- Write for a future operator or future self, not only for the original builder.
- Preserve known-good commands, launch paths, and validated setups once they work.
- Document what the system is for, how to run it, what is true right now, and what is not yet true.
- Use handoff docs, non-goals, runbooks, checklists, and cheat sheets to reduce rediscovery cost.

## Review-agent heuristics

- Flag scope creep early.
- Ask whether the feature matches a real workflow lane or is becoming generic tooling.
- Prefer narrower v1 scope over optional complexity.
- Review UI for clarity, calmness, and operator trust, not just polish.
- Be suspicious of premature abstraction if the workflow is not yet proven.
- Flag anything that weakens durability, recoverability, migration safety, or system-of-record clarity.
- Prefer workflows that clearly answer: what needs action, who owns it, and what happens next.

## Collaboration and agent behavior

- Read context first and use the intended entrypoint.
- Do not guess project structure when the repo can tell you.
- Keep outputs inspectable and easy to continue.
- Preserve state and decisions in-repo so future work can resume cleanly.
- Favor human-friendly handoff over clever but opaque automation.

## Tensions to manage

- Experiment widely, but keep execution surfaces disciplined.
- Be ambitious, but keep the implementation surface small.
- Make the interface distinct, but not at the cost of readability.
- Stay rigorous, but avoid ceremony that creates operator friction.

## What this means for `agent-runner`

- `agent-runner` should feel like a personal operator console, not a chat toy.
- The main window should stay spare, obvious, and low-friction.
- Loops should be inspectable, stoppable, resumable, and artifact-backed.
- Clarification, planning, checks, and review should increase trust, not add ritual.
- Model/provider flexibility should exist, but it should not overwhelm the main control surface.
- New features should reinforce durability, legibility, and workflow truth before adding breadth.

## Sources synthesized

- `/Users/sky/Documents/codex/business/clementine-kids/ops-dashboard/shopify-app/mind-map.md`
- `/Users/sky/Documents/codex/lab/mind-map.md`
- `/Users/sky/Documents/codex/personal/projects/finance-dashboard/mind-map.md`
