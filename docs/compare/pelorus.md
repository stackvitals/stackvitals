# StackVitals and Pelorus

Pelorus: A Red Hat community project measuring DORA's four metrics with Prometheus exporters and Grafana. Not archived, but its last release was in June 2024 and its main branch says the next version isn't active.

**Kind:** Open source (Apache 2.0), on OpenShift. **How it runs:** OpenShift 4.7 or later, through its operator; Prometheus and Grafana.

Checked 2026-11-01 from the sources below; tools change, so check them before you rely on this.

## Where Pelorus is better

- True production deploy times from labelled OpenShift objects, not from CI.
- Failures from ServiceNow, PagerDuty or Jira; any git host.

## Where StackVitals differs

- Runs anywhere GitHub Actions runs; no cluster.
- Pull request flow and flaky-test triage, which Pelorus doesn't do.
- Maintained, with releases in 2026.

## Measured side by side

- Not measured: no side-by-side run yet.

## Sources

- [Repository](https://github.com/dora-metrics/pelorus)
- [Docs](https://pelorus.readthedocs.io/en/latest/)
