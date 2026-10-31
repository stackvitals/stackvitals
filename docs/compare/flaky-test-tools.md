# StackVitals and Trunk Flaky Tests and BuildPulse

Trunk Flaky Tests and BuildPulse: Flaky-test services: they read JUnit reports from CI, detect flaky tests and quarantine them. Trunk is free up to 5 committers on private repos (data in the US); BuildPulse starts at $99 a month.

**Kind:** SaaS. **How it runs:** Hosted; an uploader in your CI sends test results to the service.

Checked 2026-11-01 from the sources below; tools change, so check them before you rely on this.

## Where Trunk Flaky Tests and BuildPulse is better

- Test-level detection across every CI, with quarantine that keeps CI green.
- Tickets in Jira, Linear or GitHub; Trunk adds a merge queue; support.

## Where StackVitals differs

- Free at any size; results stay in your repo.
- Sorts each failure on a pull request against main's history (already failing on main, new, flaky), and quarantine is opt-in too.
- Delivery, pull request flow and dependencies in the same Action.

## Measured side by side

- Not measured: no side-by-side run yet.

## Sources

- [Trunk pricing](https://trunk.io/pricing)
- [Trunk docs](https://docs.trunk.io/flaky-tests)
- [BuildPulse pricing](https://buildpulse.io/pricing)
