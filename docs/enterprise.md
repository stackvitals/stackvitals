# Enterprise controls

StackVitals has no server and no account: it runs in your GitHub Actions with your tokens and keeps everything in your
repos. So the controls an enterprise asks a vendor for are GitHub's own, applied to StackVitals like to any workflow.

| What you need | Where it comes from | What to set |
|---|---|---|
| Single sign-on | Your GitHub organization's SAML or OIDC SSO | Nothing extra: people reach the app and the data through GitHub. A personal token a person pastes into the app must be SSO-authorized like any other. |
| Who can see what | Repository permissions | The data branch and the app have the repo's visibility. Private repos' pages stay private (Enterprise Cloud private Pages) or aren't published at all (`pages: artifact`). The Portal leaves private repos out of every page a public portal repo writes. |
| Who can change what | Repository roles | Settings changes need write access to the repo, decisions triage access, golden paths write access to the portal repo and to the target repo; the workflow starts only for owners, members and collaborators ([threat-model.md](threat-model.md)). |
| Audit log | GitHub's audit log, plus StackVitals' own | Every decision and settings change is appended to `decisions/log.ndjson` on the data branch with who, when, why and from where; the app's Activity page shows it. GitHub's audit log records the workflow runs and token use. |
| Data residency | Where your GitHub data lives | StackVitals' history is files in your repo, so it stays wherever your GitHub Enterprise data resides. What leaves the repo, and how to keep it all inside GitHub, is on [privacy.md](privacy.md). |
| Secrets | GitHub Actions secrets | Keys live in your repo's or org's secrets and reach only their own service's host ([privacy.md](privacy.md)). |
| Supply chain | Pinned actions, signed releases | Every action StackVitals' own workflows use is pinned to a commit; pin the StackVitals Action itself to a release's commit SHA rather than `@v0`. The release workflow signs each release with Sigstore and adds an SBOM and build provenance ([SECURITY.md](../SECURITY.md)). |
| Uptime and support | GitHub Actions' availability | There is no StackVitals service to go down: a missed run is caught up by the next one. There is no paid SLA; report problems as issues, and security problems privately ([SECURITY.md](../SECURITY.md)). |
| Certifications (SOC 2, ISO 27001) | GitHub's | StackVitals has no service of its own, so GitHub's certifications cover where the data lives. By default the dependency check sends package names to deps.dev and the registries; `[deps] outside_lookups = false` stops that ([privacy.md](privacy.md)). The code is open to review. |

## Rate limits on Enterprise Cloud

The workflow token allows 15,000 requests an hour on Enterprise Cloud (1,000 elsewhere). The busiest public repos need
under 40% of the smaller limit for CI Health ([bench/accuracy/platform](../bench/accuracy/platform/README.md)).
