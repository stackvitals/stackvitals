---
name: stackvitals-portal
description: Use when asked who owns a repo or service in an org, which repos have no or weak owners, how repos score against the org's standards, or how an org-wide campaign is going. Answers with StackVitals Portal.
---

# Portal: what an org owns, and who owns it

Needs the StackVitals MCP server with every tool: `stackvitals serve --tools all` (the default 11 leave some of the tools below out).

## Steps

1. **The org's catalog:** call `org_catalog` with the org (CLI: `stackvitals portal report <org>`). Report how many repos
   have valid, weak or no owners, with the reasons (CODEOWNERS errors, empty teams, a catch-all owner). Its `catalog`
   lists what repos' `catalog-info.yaml` files declare (kind, type, lifecycle, owner, system, depends on); quote
   `owner_check` where CODEOWNERS disagrees with the declared owner, and the file `problems`.
2. **One repo:** call `repo_scorecard` with owner/name for its level (gold, silver, bronze, or below bronze) and the rules
   it fails. CLI: `stackvitals portal report <org> --json`, then that repo's `score`: its `results` marked `fail` carry the
   evidence, and rules marked not available say why (often a token that can't read admin settings).
3. **Ownership gaps:** call `owners_health` (CLI: the same `--json`, each repo's `owners`: status, reasons, suggested and
   suggested_from) and list the active repos without valid owners first, with the suggested owners and where each
   suggestion came from.

## Notes

- Private repos only appear for tokens that can read them; never paste private repo names into a public place.
- The org's `.github` repo holds shared settings and is not judged.
