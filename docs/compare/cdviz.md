# StackVitals and CDviz

CDviz: Delivery observability built on CDEvents, the CD Foundation's event standard: a collector, Postgres with TimescaleDB, and Grafana. Very active, small adoption.

**Kind:** Open source (Apache 2.0), self-hosted or EUR 20/month hosted. **How it runs:** A collector, Postgres with TimescaleDB and Grafana; Docker, Helm or a hosted plan (GitHub and GitLab only).

Checked 2026-11-01 from the sources below; tools change, so check them before you rely on this.

## Where CDviz is better

- Speaks CDEvents in and out, so Argo CD, Kubernetes, Jenkins and Harbor feed it with no glue.
- Sends events out (webhooks, Kafka, NATS, SSE) to trigger other workflows: its standout feature.
- Records deployments from the cluster itself, and test reports from any CI (JUnit, TAP, SARIF).

## Where StackVitals differs

- Nothing to host; deployments found without wiring events.
- Sorts each failure on a pull request (flaky, already failing, new); CDviz shows a pass/fail history line.
- Alerts, re-runs and issues act on findings, but not as CDEvents yet.

## Measured side by side

- Not measured: no side-by-side run yet.

## Sources

- [CDviz](https://cdviz.dev/)
- [Pricing](https://cdviz.dev/pricing)
- [Docs](https://cdviz.dev/docs/)
- [Repository](https://github.com/cdviz-dev/cdviz)
