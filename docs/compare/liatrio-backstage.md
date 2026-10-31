# StackVitals and Liatrio's DORA plugin for Backstage

Liatrio's DORA plugin for Backstage: A Backstage plugin showing DORA metrics per service. Last release May 2025; its chart library is archived.

**Kind:** Open source (Apache 2.0). **How it runs:** A Backstage app, Loki with Promtail, Liatrio's OpenTelemetry collector and its DORA API; a GitHub token with full repo access and an org webhook.

Checked 2026-11-01 from the sources below; tools change, so check them before you rely on this.

## Where Liatrio's DORA plugin for Backstage is better

- Metrics inside Backstage, next to each service in the catalog.
- A standard OpenTelemetry pipeline; weekends and holidays can be left out.

## Where StackVitals differs

- Exports Backstage catalog entities with the repo's level as an annotation, but has no card inside Backstage.
- Finds deployments without GitHub Deployments; the plugin sees only those.
- Nothing to host.

## Measured side by side

- Not measured: no side-by-side run yet.

## Sources

- [Repository](https://github.com/liatrio/backstage-dora-plugin)
- [DORA API](https://github.com/liatrio/liatrio-dora-api)
