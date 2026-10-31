// Newer report fields for the demo: the Sonar connector, and Portal's per-repo facts, catalog APIs and campaign days.
export function extendPortal(r, files, d) {
  if (r.slug === "web-app") {
    const sonar = { name: "SonarQube", as_of: "NOW-58m", key_expires: null, scope: "acme_web-app", expiring: false, error: null, rows: { quality: 30 }, complete: true,
      check: { ok: true, as: null, detail: "Read the quality gate of acme_web-app on SonarCloud: OK.", checked_at: "NOW-2d", fix: null } };
    files["connectors.json"].connectors.sonar = sonar;
    files["health.json"].sources.SonarQube = { kind: "connector", last_try: sonar.as_of, last_ok: sonar.as_of, failing_since: null, error: null, complete: true, read: sonar.rows };
  }
  const p = files["portal.json"];
  // The three repos share one portal object: fill it once.
  if (!p || p.extended) return;
  p.extended = true;
  const facts = {
    "acme/payments-api": { protected: true, docs: { readme: true, license: true, contributing: true, code_of_conduct: false, org_defaults: [] },
      reviews: null, ci: null, openssf: null, properties: { tier: "critical", team: "payments-core" }, files: { "SECURITY.md": { present: false } },
      owners: { status: "valid", file: ".github/CODEOWNERS", reasons: [], owners: ["@acme/payments-core", "@acme/ledger"] } },
    "acme/web-app": { protected: true, docs: { readme: true, license: true, contributing: true, code_of_conduct: true, org_defaults: ["code_of_conduct"] },
      properties: { tier: "high", team: "storefront" }, files: { "SECURITY.md": { present: true, "contains:security@acme.dev": true } },
      owners: { status: "valid", file: "CODEOWNERS", reasons: [], owners: ["@acme/storefront", "@acme/checkout"] } },
    "acme/mobile": { protected: null, docs: { readme: true, license: true, contributing: false, code_of_conduct: true, org_defaults: [] },
      openssf: { date: "NOW-5d", checks: { "Branch-Protection": -1, "Code-Review": 8, Maintained: 10, "Pinned-Dependencies": 3, "Token-Permissions": 0, Vulnerabilities: 7, "Security-Policy": 10 } },
      files: { "SECURITY.md": { present: true, "contains:security@acme.dev": false } },
      owners: { status: "weak", file: "CODEOWNERS", reasons: ["no catch-all line (* or /): files outside the listed paths have no owner"], owners: ["@acme/android"] } },
    "acme/ledger": { protected: true, docs: { readme: true, license: true, contributing: null, code_of_conduct: null, org_defaults: [] }, ci: { first_try_share: 0.83, pushes: 41, median_s: 412 },
      reviews: { first_review_median_s: 15120, prs: 23 }, owners: { status: "valid", file: ".github/CODEOWNERS", reasons: [], owners: ["@acme/ledger"] } },
    "acme/infra-terraform": { protected: false, rules: [], docs: { readme: false, license: true, contributing: null, code_of_conduct: null, org_defaults: [] },
      ci: { first_try_share: 0.64, pushes: 25, median_s: 188 }, owners: { status: "weak", file: "CODEOWNERS", reasons: ["2 errors in CODEOWNERS (GitHub's own check)"], owners: ["@acme/platform"] } },
    "acme/design-system": { protected: true, rules: ["pull_request", "required_status_checks"], docs: { readme: true, license: true, contributing: true, code_of_conduct: true, org_defaults: [] },
      openssf: { date: "NOW-3d", checks: { "Branch-Protection": 8, "Code-Review": 10, Maintained: 10, "Pinned-Dependencies": 9, "Token-Permissions": 10, Vulnerabilities: 10, "Security-Policy": 10 } } },
    "acme/data-pipelines": { protected: false, docs: { readme: true, license: false, contributing: null, code_of_conduct: null, org_defaults: [] }, ci: { first_try_share: 0.71, pushes: 14, median_s: 960 },
      owners: { status: "none", file: null, reasons: ["no CODEOWNERS file"], owners: [], suggested: ["mira-k", "devops-sam"], suggested_from: "recent reviews" } },
    "acme/old-admin": { protected: null, docs: { readme: false, license: false, contributing: null, code_of_conduct: null, org_defaults: [] }, error: "ReadTimeout",
      owners: { status: "none", file: null, reasons: ["no CODEOWNERS file"], owners: [], suggested: ["j-oakes"], suggested_from: "recent commits" } },
  };
  const ents = { "acme/payments-api": { provides_apis: ["api:default/payments-v2"], consumes_apis: ["api:default/card-network"], tags: ["go", "pci"] },
    "acme/web-app": { consumes_apis: ["api:default/payments-v2", "api:default/search"], tags: ["typescript", "frontend"] }, "acme/mobile": { consumes_apis: ["api:default/payments-v2"], tags: ["android"] } };
  for (const repo of p.repos) {
    Object.assign(repo, { checked: "NOW-6h" }, facts[repo.name] || {});
    // Published Scorecard rules can't be read on private repos.
    if (repo.score) repo.score.not_available = repo.private ? 1 : 0;
    for (const e of repo.descriptor?.entities || []) Object.assign(e, ents[repo.name] || {});
  }
  for (const c of p.campaigns || []) c.days_left = 38;
}
