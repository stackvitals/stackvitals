# StackVitals and Middleware

Middleware: An open-source DORA app (middlewarehq/middleware) with its own web UI. Last release 0.3.1 in May 2025; a few fixes in 2026.

**Kind:** Open source (Apache 2.0), self-hosted. **How it runs:** One Docker image with Postgres and Redis inside, left running.

Checked 2026-11-01 from the sources below; tools change, so check them before you rely on this.

## Where Middleware is better

- A ready-made interactive app with team and repo filters, nothing to build.
- One place syncs many repos with one personal token.
- GitLab as well as GitHub.

## Where StackVitals differs

- Nothing left running, and the workflow's own token is enough.
- Reads GitHub's Deployments API as well as merges; Middleware counts workflow runs or merges.
- Flaky-test triage, PR comments and alerts, which Middleware doesn't do.

## Measured side by side

- Same 5 repos: Middleware's image is 1.36 GB and it used 1.09 GB of memory; it read the repos in 319 s, faster than StackVitals' 584 s. ([evidence](../../bench/accuracy/middleware/README.md))
- Lead time on the 96 pull requests both counted: 95 agree within 10%; the one that doesn't was rebased weeks after the work began. ([evidence](../../bench/accuracy/middleware/README.md))
- Asked for 90 days, Middleware returned about 31 to 36 days on 4 of the 5 repos. ([evidence](../../bench/accuracy/middleware/README.md))
- Not measured: change failure rate and recovery time, since no repo had a revert or incident in the window.

## Sources

- [Repository and README](https://github.com/middlewarehq/middleware)
- [Docs](https://docs.middlewarehq.com/)
