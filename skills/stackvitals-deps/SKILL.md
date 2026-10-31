---
name: stackvitals-deps
description: Use before adding a new dependency, when choosing between packages, when reviewing a Dependabot or Renovate update, or when asked which dependencies in a lockfile need attention. Answers with StackVitals Dependency Steward's evidence from crawled repos.
---

# Dependencies: decide with evidence, not popularity

Needs the StackVitals MCP server with every tool (`pip install stackvitals`, then in Claude Code `claude mcp add stackvitals -- uvx stackvitals serve --tools all`): `stackvitals serve --tools all` (the default 11 leave some of the tools below out).

## Steps

1. **One package:** call `check_package` with its name (and ecosystem when ambiguous); CLI:
   `stackvitals deps check pypi:<name>` (or `npm:<name>`). It answers use, monitor or investigate (or no verdict when the
   evidence is thin), with every line behind it: how upgrades went across crawled repos (merged, failed CI against those
   repos' usual rate, reverted), maintainer activity, releases and known vulnerabilities. Quote the warning lines too, not
   only the good ones (in `--json`, read all of `lines`).
2. **Choosing between packages:** check both in one call (CLI: `stackvitals deps check pypi:a pypi:b`) and compare their
   lines side by side. Point out when one has far less evidence behind its verdict, or no maintainer line at all.
3. **A lockfile:** call `scan_lockfile` with its path (CLI: `stackvitals deps scan path/to/lockfile`) and start with the
   packages it ranks first.
4. **Licences and the projects behind the packages:** call `supply_chain` with the repo. It reads the weekly SBOM page:
   packages against the repo's licence rule (`[deps.licenses] deny`), licence changes between quarters, and OpenSSF
   Scorecard drops of the projects behind them. A package offering an allowed licence choice ("MIT OR GPL-3.0") is fine.
5. **An update PR that fails CI:** run `stackvitals insights owner/repo`. Its dependency finding compares the update with
   the same update across crawled repos: if it fails far more often there too, pin it or wait; if not, look at this repo's
   own checks first.

## Notes

- Evidence needs enough repos: when it says "not enough upgrade evidence", say so instead of guessing.
