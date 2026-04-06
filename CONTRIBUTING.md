# Contributing to Alcove

Thanks for helping improve Alcove.

## Best First Contributions

Good low-friction contributions include:

- fixing onboarding or docs confusion
- improving test reliability
- tightening setup scripts and local ergonomics
- polishing UI trust cues, status visibility, and artifact workflows

## Local Setup

```bash
./scripts/setup-dev.sh
pytest -q
```

Launch the main runtime with:

```bash
alcove web
```

## Ground Rules

- Keep changes focused and easy to review.
- Prefer small follow-upable PRs over broad refactors.
- Do not commit secrets, local logs, or machine-specific config.
- Preserve existing user worktrees and repo artifacts unless the change is explicitly about them.
- Add or update tests when behavior changes.

## Before Opening a PR

- run `pytest -q`
- update docs if behavior or setup changed
- call out any platform-specific limitations, especially macOS-only paths

## Scope Notes

This repo contains both product code and working roadmap notes. Not every doc is polished public documentation yet, so if something is unclear, opening a docs-focused issue or PR is welcome.
