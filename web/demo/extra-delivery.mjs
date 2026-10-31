// Newer delivery report fields for the demo, in the shapes core/delivery.py, releases.py, bugs.py, change_risk.py,
// what_changed.py, flow/survival.py, connectors/ai_spend.py and connectors/sonar.py publish.
const range = (n, f) => Array.from({ length: n }, (_, i) => f(i));
const round = (x, d = 2) => Math.round(x * 10 ** d) / 10 ** d;
const sha = (i) => (0x9a3c1f0 + i * 0x1b2d3).toString(16);

export function extendDelivery(r, files, d) {
  const x = files["delivery.json"];
  if (!x) return;
  const go = r.eco === "Go", web = r.slug === "web-app", kotlin = r.lang === "Kotlin";
  const deps = d.deploys90, pr0 = d.queue[0].n - 40;
  const dora = x.dora;

  // A year of deployments (finished, failed, recovery hours) and each shipped PR's lead time, for the Any dates tab.
  // Kept small for the demo budget: about one or two deployments a week, two PRs each.
  const step = kotlin ? 7 : go ? 3 : 5;
  const depRows = [], prRows = [];
  for (let day = 364; day >= 1; day -= step) {
    const failed = (day * 13) % 17 === 0;
    depRows.push([`NOW-${day}d`, failed, failed ? round(r.recovery * (0.6 + (day % 5) / 5), 1) : null]);
    for (let k = 0; k < 2; k++) prRows.push([`NOW-${day}d`, round(r.lead * (0.4 + ((day + k * 7) % 11) / 8), 1)]);
  }
  x.dora_rows = { deployments: depRows, prs: prRows };

  x.dora_weeks = range(13, (k) => ({ week: `NOW-${(12 - k) * 7 + 3}d`, deployments: Math.max(1, Math.round(deps / 13 + ((k * 5) % 7) - 3)),
    lead_time_hours: round(r.lead * (0.8 + ((k * 3) % 7) / 14), 1), change_failure_rate: k % 4 === 1 ? round(r.cfr * 1.6, 3) : k % 3 === 0 ? 0 : r.cfr,
    recovery_hours: k % 4 === 1 ? round(r.recovery * 1.2, 1) : null }));
  x.deploy_attempts = kotlin ? null : { source: x.deploy_source, attempts: deps + d.failed + 3, succeeded: deps, failed: d.failed, cancelled: 3,
    success_rate: round(deps / (deps + d.failed), 4), median_minutes: go ? 6.5 : 11.2 };
  x.deployments_unreadable = false;
  x.deploy_names = kotlin ? [] : [{ name: "production", n: deps }];
  x.deploy_check.settings = { source: "auto", deploy_workflow: "(?i)deploy|release|publish", production: ["production", "prod", "live"] };
  x.deploy_check.releases = { published: kotlin ? deps : 6, prereleases_skipped: kotlin ? 4 : 1 };
  Object.assign(dora, { deployment_days_per_six_months: Math.round(dora.deployment_days * 2), lead_time_working_hours: round(r.lead * 0.42, 1) });
  dora.linkage = { ...dora.linkage, disagree: 1 };
  for (const c of x.changes) Object.assign(c, { n_now: c.unit === "count" ? null : 9, n_base: c.unit === "count" ? null : 41 });

  // Each deployment with what it shipped; incidents blamed on the ones that failed.
  const incs = x.incidents || [];
  x.deployment_list = range(Math.min(18, deps), (i) => ({ id: `dep-${i}`, name: kotlin ? `v3.${27 - i}.0` : "production", sha: sha(40 - i),
    finished: `NOW-${i * (kotlin ? 7 : 2) + 1}d`, prs: range(kotlin ? 6 : 1 + (i % 3), (k) => pr0 - i * 3 - k),
    authors: kotlin ? 4 : 1 + (i % 2), lead_hours: round(r.lead * (0.6 + (i % 4) / 4), 1), incidents: i % 6 === 2 && incs[i % incs.length] ? [incs[i % incs.length].number] : [] }));
  x.releases = range(8, (i) => ({ tag: kotlin ? `v3.${27 - i}.0` : `v${go ? 2 : 5}.${14 - i}.0`, at: `NOW-${i * 9 + 2}d`, prs: 6 + ((i * 5) % 9),
    fixes: 1 + (i % 3), fix_share: round((1 + (i % 3)) / (6 + ((i * 5) % 9)), 4), reverted: i === 2 ? [pr0 - 31] : [],
    incidents_after: i === 2 ? 1 : 0, settled: i > 1 }));
  x.bugs = { weeks: range(12, (k) => ({ week: `NOW-${(11 - k) * 7 + 3}d`, opened: 3 + ((k * 3) % 5), closed: 2 + ((k * 5) % 6), open: 14 + ((k * 7) % 6) })),
    open: 17, median_open_days: 23, sources: web ? ["github", "linear"] : go ? ["github", "jira"] : ["github"],
    oldest: range(5, (i) => ({ src: "github", id: 1200 + i * 37, days: 210 - i * 33 })) };

  // Change risk: this repo's own backtest; the Kotlin repo's says the score isn't predictive there.
  const bt = { train: 182, test: 78, test_troubled: 11, auc: kotlin ? 0.55 : go ? 0.76 : 0.72, top_fifth_trouble: kotlin ? 0.13 : 0.38, overall_trouble: 0.141 };
  x.change_risk = kotlin ? { backtest: bt, open: null, troubled: 23, note: "Not predictive in this repo: on its newest pull requests it ranked trouble about as well as chance (AUC 0.55), so no score is shown." }
    : { backtest: bt, troubled: 31, note: null, open: d.queue.slice(0, 6).map((q, i) => ({ pr: q.n, risk: round(0.42 - i * 0.06, 4), level: i < 2 ? "high" : i < 4 ? "medium" : "low", base: 0.141,
      reasons: i < 2 ? [`touches ${go ? "internal/ledger/" : "src/checkout/"}, where 31% of PRs needed a fix`, "the author's first change there", "no test changes"] : i < 4 ? ["large change (over 400 lines)"] : [] })) };
  x.what_changed = incs.slice(0, 2).map((inc, i) => ({ incident: { source: inc.source, number: inc.number, created: inc.created, resolved: null, deployment: `dep-${i * 3}` }, window_hours: 72,
    candidates: [{ kind: "deployment", ref: sha(40 - i * 3).slice(0, 7), at: inc.created, why: "the deployment this incident is tied to", deployment: `dep-${i * 3}` },
      { kind: "pull request", ref: `#${pr0 - i * 9}`, title: go ? "Batch ledger writes" : "Cache cart totals", at: inc.created, why: "a revert later undid it" },
      { kind: "dependency", ref: `#${pr0 - i * 9 - 2}`, title: `Bump ${r.deps[0][1]}`, at: inc.created, why: "shipped in that deployment" }] }));
  x.code_survival = { 30: { people: { prs: 64, share: 0.91 }, agents: { prs: 18, share: 0.83 } }, 90: { people: { prs: 41, share: 0.84 }, agents: { prs: 9, share: 0.71 } } };

  // Sonar quality gate and measures, a month apart (only the web app connects SonarCloud).
  x.code_quality = web ? { project: "acme_web-app", day: "NOW-3h", gate: "ERROR", failing: ["new_coverage"],
    measures: { bugs: 4, vulnerabilities: 1, code_smells: 212, coverage: 71.4, duplicated_lines_density: 3.2 },
    month_ago: { bugs: 6, vulnerabilities: 1, code_smells: 198, coverage: 73.0, duplicated_lines_density: 3.4 },
    days: range(30, (k) => ({ day: `NOW-${30 - k}d`, bugs: 6 - Math.floor(k / 12), vulnerabilities: 1, code_smells: 198 + Math.floor(k / 2), coverage: round(73 - k * 0.055, 1) })) } : null;

  // AI spend and the coding tools side by side (only the web app has admin keys).
  if (web) x.ai.spend = { window_days: 30, providers: { anthropic: 412.37, openai: 96.1, cursor: 640 }, total_usd: 1148.47, ai_prs: 38, per_ai_pr_usd: 30.22, cursor_agent_requests: 2210,
    tools: { claude_code: { sessions: 311, lines_added: 18420, commits: 96, prs: 27, acceptance: 0.82, est_usd: 388.5 }, cursor: { agent_requests: 2210, lines_added: 9310 } } };
  const w = x.ai.outcomes.window;
  for (const k of ["agent", "assisted", "others"]) if (w[k]) w[k].merge_rate_n = w[k].n + 4;

  // DORA per team, from the deployments that shipped each team's PRs; and issues done by team.
  for (const [i, t] of Object.values(x.by_team).entries()) t.dora = { deployment_days_per_week: round(dora.deployment_days_per_week * (i ? 0.6 : 0.9), 1),
    lead_time_hours: round(r.lead * (1 + i * 0.2), 1), change_failure_rate: round(r.cfr * (1 + i * 0.4), 3), recovery_hours: round(r.recovery * (1 + i * 0.3), 1) };
  if (x.tracker) x.tracker.by_team = { teams: Object.fromEntries(r.team.map((t, i) => [t, { done: 48 - i * 15 }])), unmatched: 6, by_email: 9, suggested: [] };

  // LinearB-style habits and DevLake's PR cycle panel.
  const n = d.merged90;
  x.sizes = { n, p50: 96, p75: 214, under_100: Math.round(n * 0.52), "100_155": Math.round(n * 0.16), "156_228": Math.round(n * 0.09), over_228: n - Math.round(n * 0.52) - Math.round(n * 0.16) - Math.round(n * 0.09) };
  x.merge_frequency = go ? 1.8 : 1.3;
  x.review_depth = go ? 3.4 : 2.1;
  x.merged_without_review = { n: 3, share: round(3 / n, 4) };
  x.merged_flags = { lightning: [{ pr: pr0 - 4, review_minutes: 2 }, { pr: pr0 - 17, review_minutes: 4 }], without_review: [{ pr: pr0 - 8 }, { pr: pr0 - 22 }, { pr: pr0 - 29 }] };
  x.devlake_pr_cycle = range(3, (i) => ({ month: `MON-${2 - i}`, avg_hours: round(r.lead * (1.1 - i * 0.1), 2), n: 30 + i * 4 }));
  // For finance (core/capex.py): author-weeks by kind of work, six months; the CSV itself isn't shipped with the demo.
  if (x.investment) x.capex = { file: "capex.csv", rows: x.investment.n * 2, months: x.investment.months.map((m, i) => ({ month: m.month, prs: m.n,
    agent_prs: go ? 2 + (i % 3) : i % 2, author_weeks: Object.fromEntries(Object.entries(m.counts).map(([k, v]) => [k, Math.max(1, Math.round(v * 0.8))])),
    feature_share: round((m.counts.feature || 0) / m.n, 4) })) };
}
