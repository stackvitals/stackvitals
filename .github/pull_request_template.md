## What this changes

<!-- What changes for someone using StackVitals, in a sentence or two. Link the issue if there is one. -->

## How it was checked

- [ ] Tests pass: `uv run --extra dev pytest tests -q`
- [ ] If the web app changed: `cd web && npm run build && npm test`, and the rebuilt `src/stackvitals/web/` is committed
- [ ] If a rule behind a verdict or number changed: its entry in `bench/accuracy/registry.json` and the regenerated
      docs (`python bench/accuracy/summary.py`)
- [ ] If it reaches a new host or needs a new permission: said so below

## Anything reviewers should know

<!-- Trade-offs, follow-ups, or what you weren't sure about. -->
