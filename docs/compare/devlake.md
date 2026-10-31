# StackVitals and Apache DevLake

Apache DevLake: A data platform that collects DevOps data from about 50 tools into one model and shows it in Grafana, with DORA's five metrics. An Apache top-level project, very active in 2026.

**Kind:** Open source (Apache 2.0), self-hosted. **How it runs:** Four containers: MySQL or Postgres, the DevLake server, a config UI and Grafana (Docker Compose or Helm).

Checked 2026-11-01 from the sources below; tools change, so check them before you rely on this.

## Where Apache DevLake is better

- Many more sources (Jenkins, Bamboo, Azure Pipelines, Opsgenie, Rootly and more) joined in one model.
- Real SQL on a real database, dozens of editable Grafana dashboards and team rollups.
- Raw API answers are kept, so metrics can be recomputed after a setting changes without fetching again.
- An ASF project, with the governance that brings.

## Where StackVitals differs

- Nothing to host: one Action, history on a branch of your repo.
- Finds the deployment source without setup; DevLake needs a job-name pattern or GitHub Deployments.
- Flaky-test triage on pull requests, which DevLake doesn't do.

## Measured side by side

- Same 5 repos and 90 days: DevLake pulled 9.2 GB of images and took 7,771 s (2 h 10 min) to collect at its 900 requests an hour; StackVitals took 584 s with a `pip install`. ([evidence](../../bench/accuracy/devlake/README.md))
- DORA tiers on those 5 repos: the same for deployment frequency and lead time on 5 of 5 (after a bug the side-by-side found in StackVitals was fixed). Five repos is too few to generalise from. ([evidence](../../bench/accuracy/devlake/README.md))
- Deployment source with no setup, 60 public repos: StackVitals right on 53 (78-94%), DevLake's default pattern on 9, a pattern a user would write on 22. Labels by two model families, not people. ([evidence](../../bench/accuracy/dora/README.md))
- Not measured: change failure rate and recovery time, since neither tool found an incident on the 5 repos.

## Sources

- [DevLake docs: introduction](https://devlake.apache.org/docs/Overview/Introduction)
- [DevLake docs: architecture](https://devlake.apache.org/docs/Overview/Architecture)
- [DevLake docs: DORA](https://devlake.apache.org/docs/DORA)
- [DevLake docs: metrics](https://devlake.apache.org/docs/Metrics)
- [Repository](https://github.com/apache/devlake)
