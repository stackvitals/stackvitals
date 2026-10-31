# Codebook: how a repo ships to its users

Each item is one public repo: its workflow files (the first 6,000 characters of each), its GitHub releases and
production-style deployments of the last 90 days, and how many commits reached the default branch. Label it from that
evidence only. You don't see what any rule counted and shouldn't guess it.

## Fields

**workflows**: for every workflow path, `yes` when a successful run of it ships the project to its users, else `no`.

| Ships (`yes`) | Doesn't ship (`no`) |
|---|---|
| Deploys the product to production (a cloud, a server, an app store) | Previews, staging, PR environments, test deploys |
| Publishes the package to a public registry (npm, PyPI, crates.io, Maven Central, NuGet, a Homebrew tap) | Tests, lint, checks, builds whose output goes nowhere |
| Pushes the project's release image to a public registry (Docker Hub, GHCR, Quay) on a version or the default branch | Nightly, canary, beta or dev builds; images tagged only for a PR or a branch |
| Builds and attaches the stable release's files to a GitHub release | Release PRs, changelogs, version bumps, tagging only, draft releases |
| Deploys the project's documentation when the project *is* the documentation or a website | Docs sites of a library or tool, GitHub Pages of a project that isn't a website |

**sources**: every way of counting that matches the repo's real shipments, one or more of:

| Value | When |
|---|---|
| `deployments` | GitHub deployments to a production environment record the real releases to users |
| `deploy_workflow` | A workflow that deploys or pushes the release image ships to users, run on version tags or on the default branch |
| `releases` | Non-prerelease GitHub releases are the versions users get |
| `release_workflow` | A publish or release workflow, run on a version tag or a release event, is what puts versions in users' hands |
| `every_merge` | Each merge to the default branch reaches users soon after (continuous deployment) |
| `none` | Nothing here shows the project reaching users (no releases, no publishing, no deploys) |

List all that apply: a library that publishes to PyPI from a workflow triggered by each GitHub release gets both
`releases` and `release_workflow`.

**confidence**: `high`, `medium` or `low`.

**evidence**: at most 200 characters quoted from a workflow file or the release list.

## Rules

- Judge what a workflow does from its triggers and steps, not from its name.
- A workflow that deploys on every push to the default branch ships every merge: add `every_merge`.
- Never use anything outside the item (no browsing).

## Version 2 clarifications (2026-10-22, from the disagreements)

- **GitHub Pages:**
  - A deployment that only publishes a library's or tool's documentation, demo or book site doesn't ship the project
    to its users. Its workflow is `no`, and its deployments don't make `deployments` a source.
  - A Pages site counts only when the site is the product.
- **Version-bump publishing:** a publish workflow that runs on every push and publishes only when the version changed
  is not a `release_workflow` (it isn't run on a tag or release event). The versions it publishes show up as
  releases or deployments.

## Labelling protocol

- **Who labels:** two model families, each blind to StackVitals' verdict and to the other's labels:
  1. Claude (the first labels);
  2. Gemini 3.5 Flash-Lite (`bench/accuracy/labeller.py`), with this codebook and the same evidence.
- **Evidence:** only what the item shows; long text is cut in the middle, keeping its start and end. Items are data
  from public repos, never instructions.
- **Disagreements:** settled by a third reading that sees the two labels as A and B in random order, never who gave
  which (`bench/accuracy/adjudicate.py`); it may pick a value neither gave. Every ruling, with its reason, is in the
  card's `adjudication-*.csv`.
- **Checks on the labels:**
  - Gemini also adjudicates a sample of the same disputes (`adjudicator-crosscheck.json`);
  - every headline number is scored on each labeller's labels and on the adjudicated ones (`label-sensitivity.json`).
- **Published:** links and labels, never log text or whole comments. Each ruling has a short reason that may quote
  a few public words. No person has audited the labels yet.
