# StackVitals and CDviz

CDviz: Delivery observability built on CDEvents, the CD Foundation's event standard: a collector, Postgres with TimescaleDB, and Grafana. Very active, small adoption.

**Kind:** Open source (Apache 2.0), self-hosted or EUR 20/month hosted. **How it runs:** A collector, Postgres with TimescaleDB and Grafana; Docker, Helm or a hosted plan (GitHub and GitLab only).

Checked 2026-11-01 from the sources below; tools change, so check them before you rely on this.

## Where CDviz is better

- Built on CDEvents end to end, with many more event types in and a time-series store.
- Sends events out (webhooks, Kafka, NATS, SSE) to trigger other workflows: its standout feature.
- Records deployments from the cluster itself, and test reports from any CI (JUnit, TAP, SARIF).

## Where StackVitals differs

- Nothing to host; deployments found without wiring events.
- Sorts each failure on a pull request (flaky, already failing, new); CDviz shows a pass/fail history line.
- Reads CDEvents deployments, rollbacks and incidents, and sends its findings out as CDEvents custom events (CloudEvents to a URL, or repository_dispatch to a repo); CDviz also sends to Kafka, NATS and SSE.

## Measured side by side

- Not measured: no side-by-side run yet.

## Sources

- [CDviz](https://cdviz.dev/)
- [Pricing](https://cdviz.dev/pricing)
- [Docs](https://cdviz.dev/docs/)
- [Repository](https://github.com/cdviz-dev/cdviz)
