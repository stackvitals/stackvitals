# Contributing

Thanks for helping. StackVitals is small enough that one person can read any part of it in an afternoon; please
keep it that way. Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), git and Node 22 (a few tests check the app's scripts).

Clone the repo, then from its folder:

```
uv run --extra dev pytest tests -q
```

The tests need no token and no network. [docs/architecture.md](docs/architecture.md) explains how the parts fit.

**The web app** is TypeScript in `web/`, built into `src/stackvitals/web/app/`, and the built files are committed
(they ship in the package). After changing it:

```
cd web
npm ci
npm run build
npm test
```

Commit `web/` and the rebuilt `src/stackvitals/web/` together; a test fails when the build is out of date.
[web/README.md](web/README.md) explains its layout and the browser tests (`npm run e2e`).

## What a good change looks like

- **A bug:** a failing test first, then the fix. Task-sized tests go in `tests/local/`; a test that guards a real
  bug or finding for a whole flow goes in the `tests/test_flow_<area>.py` file for that area.
- **A new rule or a changed one** (anything that decides a verdict or a number people see): add or update its entry in
  [bench/accuracy/registry.json](bench/accuracy/registry.json) with what it was tuned on, what it was checked on and
  the bar, check it on public data the rule never saw, then run `python bench/accuracy/summary.py` to regenerate
  [docs/accuracy.md](docs/accuracy.md) and [docs/rules.md](docs/rules.md). A change that makes a number look better
  without held-out evidence won't be merged; a change that publishes a loss will.
- **A new setting:** add it to `src/stackvitals/core/schema.py`; [docs/settings.md](docs/settings.md) is generated
  from it and a test checks they match.
- **Anything that reaches a new host or needs a new permission:** say so in the pull request. The privacy page lists
  every outside host and a test fails if code can reach one it doesn't name ([docs/privacy.md](docs/privacy.md)).
- **A new action in a workflow:** pin it to a commit with the version in a comment; a test fails otherwise.

## Style

- Code reads like the code around it. Comments are short, plain and say why, not what.
- Copy people see is plain English: what happened, how many, since when, and what to do. No unexplained jargon, and
  never a number without its sample size.
- Each test says what real bug or finding it guards; the `tests/test_flow_*.py` files stay few and test whole flows.

## Pull requests

- Branch names: `type/short-topic` (`fix/flake-window`). Commit messages follow
  [Conventional Commits](https://www.conventionalcommits.org/): `fix(ci): Keep the failing step when a job is re-run`.
- The Tests workflow runs on every pull request. A maintainer reviews within a week; if it has been longer, comment
  to ask.
- By contributing you agree your work is released under the [Apache License 2.0](LICENSE).

## Security problems

Never in a public issue: see [SECURITY.md](SECURITY.md).
