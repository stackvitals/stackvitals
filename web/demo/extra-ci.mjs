// Newer CI report fields for the demo, in the shapes ci/analyze.py, ci/cost.py and ci/action.py write: when flaking began,
// likely causes, outages and runner trouble, cost by runner, test impact, quarantine and tickets (the last three on the data branch).

const CAUSE = { "context deadline exceeded": "timing", "expected 3 retries, got 2": "async wait", "want 10.05, got 10.04": "floating point" };
const sha = (i) => (0x5e1a9c3 + i * 0x31f7).toString(16).padStart(7, "0") + "d41c2e09b7";
// The data branch's ci/ files are one folder for all demo repos, so each repo adds its own entries to what the others wrote.
const branch = { tickets: {}, quarantine: [] };

export function extendCi(r, files, d) {
  const ci = files["data.json"];
  if (!ci) return;
  let n = 0;
  for (const item of [...(ci.tests || []), ...(ci.jobs || [])]) {
    if (!item.flake_events) continue;
    const i = n++;
    item.flake = CAUSE[item.message] || (item.job ? (i % 2 ? "infrastructure" : "network") : "timing");
    if (item.runs) {
      // The first flake after a clean stretch: clear when enough runs came before it.
      const before = i === 0 ? 61 : i === 1 ? 4 : 38, after = item.runs - before;
      item.began = { first: item.since || "NOW-30d", runs_before: before, runs_after: Math.max(after, item.flake_events), flakes: item.flake_events,
        p: before >= 20 ? 0.0012 : 0.41, clear: before >= 20, landed: before >= 20 ? [sha(i), sha(i + 7)] : [] };
    }
    if (item.job) item.flake_steps = ["Run tests", "Start services"].slice(0, 1 + (i % 2));
    if (item.decision && ["mute", "acknowledge"].includes(item.decision.verb)) item.muted_until = item.decision.until || "9999-12-31";
    if (item.job) item.variants = {};
    else item.variants = r.eco === "npm" ? { "node 20": Math.ceil(item.flake_events * 0.7), "node 22": Math.floor(item.flake_events * 0.3) }
      : r.eco === "Go" ? { "ubuntu-latest": item.flake_events } : { "api 34": Math.ceil(item.flake_events / 2), "api 30": Math.floor(item.flake_events / 2) };
  }
  ci.test_outages = r.slug === "web-app" ? 2 : 0;
  ci.infra_events = r.slug === "mobile" ? 3 : 1;
  ci.pr_edit_workflows = r.slug === "web-app" ? [".github/workflows/pr-title.yml"] : [];
  for (const g of ci.failure_groups || []) g.top_tests = (ci.tests || []).filter((t) => t.flake_events).slice(0, 3).map((t) => t.id);

  // What CI cost (ci/cost.py report), with the flaky tests' share.
  const linux = ci.minutes?.linux || 4000, mac = ci.minutes?.macos || 0, priv = r.visibility === "private";
  const usd = (m, p) => Math.round(m * p * 100) / 100;
  const flaky = (ci.tests || []).filter((t) => t.state === "flaky");
  ci.cost = { days: 30, private: priv, minutes: linux + mac, usd: priv ? usd(linux, 0.008) + usd(mac, 0.08) : 0, private_usd: usd(linux, 0.008) + usd(mac, 0.08),
    rerun_minutes: Math.round(linux * 0.06), rerun_usd: priv ? usd(linux * 0.06, 0.008) : 0, self_hosted_minutes: r.slug === "payments-api" ? 640 : 0,
    by_runner: { linux, ...(mac ? { macos: mac } : {}), ...(r.slug === "payments-api" ? { "self-hosted": 640, "linux larger": 310 } : {}) },
    workflows: [{ workflow: "CI", minutes: Math.round(linux * 0.82), usd: priv ? usd(linux * 0.82, 0.008) : 0 }, { workflow: "StackVitals", minutes: Math.round(linux * 0.04), usd: priv ? usd(linux * 0.04, 0.008) : 0 },
      { workflow: "Release", minutes: Math.round(linux * 0.14) + mac, usd: priv ? usd(linux * 0.14, 0.008) + usd(mac, 0.08) : 0 }],
    jobs: (ci.jobs || []).filter((j) => j.median_s).slice(0, 6).map((j) => ({ workflow: "CI", job: j.job, minutes: Math.round((j.median_s / 60) * (j.runs || 100)), usd: priv ? usd((j.median_s / 60) * (j.runs || 100), 0.008) : 0 })),
    prices_read: "2026-10-29",
    tests: flaky.map((t) => ({ id: t.id, suite: t.suite, minutes: Math.round(t.flake_events * 9.5 * 10) / 10, usd: priv ? usd(t.flake_events * 9.5, 0.008) : 0, flakes: t.flake_events, prs: (t.prs_affected || []).length })) };

  // Test impact replayed on past PRs (ci/impact.py backtest); mobile has no real PR failure to replay yet.
  ci.impact = r.slug === "mobile" ? { prs: 64, failures: 0, caught: 0, recall: null, skipped_share: null }
    : { prs: r.slug === "web-app" ? 118 : 86, failures: r.slug === "web-app" ? 23 : 14, caught: r.slug === "web-app" ? 21 : 13, recall: r.slug === "web-app" ? 0.913 : 0.9286, skipped_share: r.slug === "web-app" ? 0.64 : 0.57 };
  if (r.slug === "web-app") files["../ci/impact.json"] = { backtest: ci.impact, learned: {
    "src/checkout": { "src/checkout/cart.test.ts": 6, "src/checkout/pay.test.ts": 3, "e2e/checkout.spec.ts": 2 },
    "src/search": { "src/search/rank.test.ts": 4 }, "src/api": { "src/api/client.test.ts": 3, "src/checkout/pay.test.ts": 1 }, "": { "src/app.test.ts": 2 } } };

  // The quarantine list and flaky-test tickets on the data branch (ci/quarantine.json, ci/tickets.json).
  branch.quarantine.push(...flaky.filter((t) => t.flake_events >= 3).map((t) => t.id));
  flaky.forEach((t, i) => { branch.tickets[t.id] = r.slug === "payments-api" ? { tracker: "jira", key: `PAY-${412 + i}`, id: `${10412 + i}`, open: true }
    : { tracker: "linear", key: `${r.slug === "web-app" ? "WEB" : "AND"}-${88 + i}`, id: `linear:${r.slug}-${i}`, open: true }; });
  const fixed = (ci.tests || []).find((t) => t.state === "fixed");
  if (fixed) branch.tickets[fixed.id] = { tracker: "jira", key: "PAY-398", id: "10398", open: false };
  files["../ci/quarantine.json"] = [...branch.quarantine].sort();
  files["../ci/tickets.json"] = { ...branch.tickets };
}
