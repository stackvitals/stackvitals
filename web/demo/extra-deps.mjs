// Newer report fields for the demo: security.json (probes, facts, weekly score) and supply.json's licence counts and
// runtime release dates, in the shapes security/probes.py, deps/supply.py and deps/runtimes.py write.
const PROBES = [
  ["hasDangerousWorkflowUntrustedCheckout", "critical", "S", "A pull_request_target or workflow_run workflow checks out the pull request's code with secrets in reach.",
    "Use pull_request for untrusted code, or check it out only after a maintainer's label or approval gate."],
  ["hasDangerousWorkflowScriptInjection", "critical", "S", "Text an outsider writes (a title, a body, a branch name) is pasted into a run: script.",
    "Pass it through env: (FOO: ${{ github.event.issue.title }}) and use \"$FOO\" in the script."],
  ["topLevelPermissions", "high", "S", "A workflow's token gets write access it may not need.",
    "Add `permissions: contents: read` at the top and grant writes only on the jobs that need them."],
  ["pinsDependencies", "medium", "M", "An action used by tag, or a script piped from the internet, can change under you (as tj-actions/changed-files did).",
    "Pin each action to its full commit (uses: owner/action@<40-character sha> # v4) and download scripts before running them."],
  ["branchProtectionLevel", "high", "S", "The default branch can be force-pushed or merged into without review or checks.",
    "Add a ruleset on the default branch: block force pushes and deletion, require a review and the CI checks."],
  ["securityPolicyPresent", "medium", "S", "No SECURITY.md tells people how to report a vulnerability privately.",
    "Add SECURITY.md with a contact and a disclosure timeline, and turn on private vulnerability reporting."],
  ["releasesAreSigned", "high", "M", "Recent releases carry no signature or provenance file to check them against.",
    "Sign release assets with Sigstore (actions/attest-build-provenance) or publish .intoto.jsonl provenance."],
  ["hasSBOM", "medium", "S", "No SBOM in the repo or the release assets.", "Attach an SPDX or CycloneDX SBOM to each release (anchore/sbom-action)."],
  ["sastToolConfigured", "medium", "S", "No code scanning (CodeQL, Semgrep, SonarCloud) runs on pull requests.",
    "Turn on CodeQL's default setup in the repo's Security settings, or add a Semgrep workflow."],
  ["hasBinaryArtifacts", "high", "S", "Compiled files are committed, so nobody can review what they do.", "Build them in CI instead and remove them from the repo."],
  ["fuzzed", "medium", "M", "No fuzzing setup was found.", "Add ClusterFuzzLite, Go native fuzz tests, or join OSS-Fuzz."],
  ["hasOpenSSFBadge", "low", "M", "No OpenSSF Best Practices badge.", "Fill in the questionnaire at bestpractices.dev."],
  ["packagedWithAutomatedWorkflow", "medium", "S", "Releases aren't published by a workflow, so their build can't be traced.",
    "Publish from a workflow (with trusted publishing on PyPI and npm)."],
];
const WEIGHT = { critical: 10, high: 7.5, medium: 5, low: 2.5 };
const tiers = (states) => ["no force pushes or deletion", "reviews required", "status checks required", "two reviewers and code owners",
  "stale reviews dismissed, admins included"].map((rule, i) => ({ tier: i + 1, rule, state: states[i] }));
const levelOf = (t) => { let n = 0; for (const x of t) { if (x.state !== "met") break; n += 1; } return n; };

// Per repo: what the checks read. web-app has the extensionless executable found by its header.
const FACTS = {
  "payments-api": {
    workflows: { sast: [".github/workflows/codeql.yml"], publish: [".github/workflows/release.yml"], files: 4 },
    tree: { binaries: [], sbom_files: [], fuzzing: ["internal/ledger/ledger_fuzz_test.go"] },
    branch: { tiers: tiers(["met", "met", "met", "missing", "unknown"]), readable: true },
    policy: { file: "acme/payments-api:SECURITY.md", contact: true, disclosure: true, private_reporting: true },
    releases: { releases: 5, signed: ["v2.14.0", "v2.13.2", "v2.13.1"], sbom: ["v2.14.0"] }, oss_fuzz: false, badge: null,
  },
  "web-app": {
    workflows: { sast: [], publish: [], files: 5 },
    tree: { binaries: ["tools/bin/imagemin", "vendor/legacy/sass.dll"], sbom_files: [], fuzzing: [] },
    branch: { tiers: tiers(["met", "met", "unknown", "unknown", "unknown"]), readable: true },
    policy: { file: "acme/.github:SECURITY.md", contact: true, disclosure: false, private_reporting: false },
    releases: { releases: 0, signed: [], sbom: [] }, oss_fuzz: false, badge: null,
  },
  mobile: {
    workflows: { sast: [".github/workflows/codeql.yml"], publish: [".github/workflows/publish.yml"], files: 3 },
    tree: { binaries: [], sbom_files: ["sbom.cdx.json"], fuzzing: [] },
    branch: { tiers: tiers(["met", "met", "met", "met", "missing"]), readable: true },
    policy: { file: "acme/mobile:SECURITY.md", contact: true, disclosure: true, private_reporting: true },
    releases: { releases: 5, signed: [], sbom: ["v3.27.0", "v3.26.0"] }, oss_fuzz: false, badge: "passing",
  },
};

// Workflow findings that fail a probe, per repo.
const FOUND = {
  "payments-api": { pinsDependencies: [{ path: ".github/workflows/release.yml", job: "publish", detail: "goreleaser/goreleaser-action@v6 is used by tag" }] },
  "web-app": {
    hasDangerousWorkflowScriptInjection: [{ path: ".github/workflows/preview.yml", job: "comment", detail: "${{ github.event.pull_request.title }} pasted into run:" }],
    topLevelPermissions: [{ path: ".github/workflows/ci.yml", detail: "no top-level permissions: the token gets the repo's default write access" }],
    pinsDependencies: [{ path: ".github/workflows/ci.yml", job: "test", detail: "actions/setup-node@v4 is used by tag" }, { path: "Dockerfile", detail: "FROM node:20-alpine has no digest" }],
  },
  mobile: {},
};

function verdict(probe, f, found) {
  const b = f.branch, rel = f.releases, t = f.tree, w = f.workflows;
  const state = {
    branchProtectionLevel: b.readable ? (levelOf(b.tiers) >= 2 ? "pass" : "fail") : "unknown",
    securityPolicyPresent: f.policy.file ? "pass" : "fail",
    releasesAreSigned: rel.releases ? (rel.signed.length ? "pass" : "fail") : "unknown",
    hasSBOM: t.sbom_files.length || rel.sbom.length ? "pass" : "fail",
    sastToolConfigured: w.sast.length ? "pass" : "fail",
    hasBinaryArtifacts: t.binaries.length ? "fail" : "pass",
    fuzzed: t.fuzzing.length || f.oss_fuzz ? "pass" : "fail",
    hasOpenSSFBadge: f.badge ? "pass" : "fail",
    packagedWithAutomatedWorkflow: rel.releases ? (w.publish.length ? "pass" : "fail") : "unknown",
  };
  return state[probe] || (found[probe] ? "fail" : "pass");
}

function security(r) {
  const f = structuredClone(FACTS[r.slug]);
  f.branch.level = levelOf(f.branch.tiers);
  const found = FOUND[r.slug] || {};
  const probes = PROBES.map(([probe, risk, effort, why, fix]) => ({ probe, risk, effort, result: verdict(probe, f, found), why, fix,
    findings: found[probe] || [], guarded: probe === "hasDangerousWorkflowUntrustedCheckout" && r.slug === "payments-api"
      ? [{ probe, path: ".github/workflows/label.yml", guarded: "runs only after the safe-to-test label" }] : [] }));
  const known = probes.filter((p) => p.result !== "unknown");
  const total = known.reduce((a, p) => a + WEIGHT[p.risk], 0);
  const score = Math.round((100 * known.filter((p) => p.result === "pass").reduce((a, p) => a + WEIGHT[p.risk], 0)) / total) / 10;
  // Twelve weeks of scores, ending on this week's.
  const history = Array.from({ length: 12 }, (_, i) => [`NOW-${(11 - i) * 7}d`, i === 11 ? score : Math.round((score - (11 - i) * (r.slug === "web-app" ? -0.08 : 0.12)) * 10) / 10]);
  return { schema: 1, generated: "NOW-2d", score, probes, facts: f, history, weakened: r.slug === "web-app" };
}

const LICENCES = {
  Go: { "BSD-3-Clause": 31, "Apache-2.0": 24, MIT: 19, "MPL-2.0": 2 },
  npm: { MIT: 702, "ISC": 96, "Apache-2.0": 48, "BSD-3-Clause": 23, "BSD-2-Clause": 17, "BlueOak-1.0.0": 6, "AGPL-3.0-only": 1, "BUSL-1.1": 1 },
  Maven: { "Apache-2.0": 188, MIT: 21, "EPL-2.0": 12, "BSD-3-Clause": 6 },
};
const RELEASED = { "1.22.12": "2025-02-04", "1.23.4": "2024-12-03", "20.18.1": "2024-11-20", "17.0.13": "2024-10-15" };

export function extendDeps(r, files) {
  files["security.json"] = security(r);
  files["app.json"].modules.security = { updated: "NOW-2d", file: "security.json" };
  const s = files["supply.json"];
  s.licences.by_licence = LICENCES[r.eco];
  for (const x of s.runtimes || []) x.latest_date = RELEASED[x.latest] || null;
}
