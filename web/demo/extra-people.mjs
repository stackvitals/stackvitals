// Newer report fields for the demo: Team Flow's knowledge map, releases, baselines and gaps; Insights' red-check detail;
// Community's benchmark parts and traffic; the weekly pulse. Shapes follow flow/build.py, core/insights.py, community/*.
const AREAS = {
  "payments-api": [["internal/ledger", 61, "mira-k", 0.82, 41], ["internal/webhook", 44, "dev-oss", 0.48, 2], ["cmd/server", 23, "mira-k", 0.55, 41], ["internal/cards", 19, "tomas-r", 0.9, 3], ["docs", 8, "dev-oss", 0.5, 2]],
  "web-app": [["src/checkout", 72, "ana-li", 0.44, 1], ["src/storefront", 58, "kwame-o", 0.71, 0], ["src/search", 21, "jun-park", 0.86, 36], ["e2e", 17, "ana-li", 0.41, 1], [".github/workflows", 6, "kwame-o", 0.83, 0]],
  mobile: [["app/src/main", 49, null, 0.52, 1], ["feature/payments", 22, null, 0.77, 12], ["core/network", 14, null, 0.93, 48], ["buildSrc", 5, null, 0.6, 4]],
};

export function extendPeople(r, files, d) {
  const fl = files["flow.json"], ins = files["insights.json"], cm = files["community.json"];
  const pub = r.visibility === "public";
  const areas = AREAS[r.slug] || [];
  fl.knowledge = {
    areas: areas.map(([area, prs, owner, share, quiet]) => ({ area, prs, owner, share, single_owner: share >= 0.7 && prs >= 3, owner_quiet_days: quiet })),
    hotspots: areas.slice(0, 4).map(([area, prs]) => ({ area, prs_90d: Math.round(prs * 0.45), prs })).sort((a, b) => b.prs_90d - a.prs_90d),
  };
  // Per-folder habits (flow/preflight.py's folder_habits): folders with 10+ merged PRs, so the planned-PR check narrows.
  if (fl.habits) fl.habits.folders = areas.filter(([, prs]) => prs >= 10).map(([area, prs], i) => {
    const r2 = (x) => Math.round(x * 10000) / 10000, reviewed = Math.round(prs * 0.6);
    return { area, merged_prs: prs, include: { tests: r2(0.87 - i * 0.14), changelog: r2(i === 1 ? 0.12 : 0.62 - i * 0.05), docs: r2(0.08 + i * 0.07) },
      size: { median_lines: 64 + i * 22, p75_lines: 150 + i * 40, p90_lines: 380 + i * 90 },
      reviewed_prs: reviewed, asks: reviewed >= 10 ? [{ ask: i % 2 ? "docs" : "tests", share: r2(Math.round(reviewed * 0.24) / reviewed), prs: Math.round(reviewed * 0.24) }] : [] };
  });
  // The whole repo has at least as many merged PRs as its folders (some touch two).
  if (fl.habits) fl.habits.merged_prs = Math.max(fl.habits.merged_prs, Math.round(areas.reduce((s, a) => s + a[1], 0) * 0.85));
  // Kotlin ships releases; the others record deployments, so release numbers come from their tags too.
  fl.delivery = r.slug === "web-app" ? { source: "merges", releases: 0, per_week: 9.4, lead_time_median_s: null, change_fail: null, recovery_median_s: null }
    : { source: "releases", releases: pub ? 13 : 24, per_week: pub ? 1.01 : 1.87, lead_time_median_s: pub ? 302400 : 97200,
      change_fail: { failed: pub ? 2 : 3, of: pub ? 13 : 24, rate: pub ? 0.1538 : 0.125, proxy: true }, recovery_median_s: pub ? 259200 : 64800 };
  fl.baselines = { pickup: Math.round(d.p75 * 3600), merge: Math.round(r.merge * 3600), author: Math.round(r.review * 0.6 * 3600) };
  fl.load = (fl.load || []).map((x, i) => ({ ...x, oldest_since: `NOW-${2 + i * 3}d` }));
  fl.queue = (fl.queue || []).map((q, i) => (i === 0 ? { ...q, gaps: [{ what: "tests", why: `87% of merged PRs in ${areas[0]?.[0] || "this folder"} include test files` }] }
    : i === 2 ? { ...q, gaps: [{ what: "size", why: "912 lines; 90% of merged PRs in the whole repo have at most 640" }] } : q));
  fl.excluded = r.slug === "web-app" ? 2 : 0;

  const red = ins.red_ci;
  if (red) {
    const tests = (r.flaky || []).filter((t) => t.kind === "test").slice(0, 3).map((t) => t.id);
    const prList = (k) => Array.from({ length: k }, (_, i) => 1790 + i * 9);
    red.cycle_hours = { red: { median: Math.round(d.cycleP75 * 1.4 * 10) / 10, n: red.red_prs }, clear: { median: Math.round(d.cycleP75 * 0.7 * 10) / 10, n: red.prs - red.red_prs } };
    red.measures = { "insight.red_ci_share": { metric: "insight.red_ci_share", version: 1, value: red.red_prs / red.prs, n: red.prs, low: Math.max(0, red.red_prs / red.prs - 0.06), high: red.red_prs / red.prs + 0.07, unit: "share", as_of: r.updated, window_days: 90, note: null } };
    red.rerun_jobs = [{ workflow: "CI", job: r.eco === "Go" ? "test (1.23)" : r.eco === "npm" ? "e2e (chromium)" : "connectedAndroidTest", hours: Math.round(red.rerun_hours_total * 0.6 * 10) / 10, prs: Math.max(2, red.rerun_waits - 2), runs: [] },
      { workflow: "CI", job: "lint", hours: Math.round(red.rerun_hours_total * 0.15 * 10) / 10, prs: 2, runs: [] }];
    red.rerun_tests = tests.map((t, i) => ({ test: t, hours: Math.round(red.rerun_hours_total * (0.4 - i * 0.12) * 10) / 10, prs: 4 - i, pr_list: prList(4 - i), runs: [] }));
    red.top = prList(3).map((pr, i) => ({ pr, hours: Math.round(d.cycleP75 * (1.6 - i * 0.3) * 10) / 10, waits: [{ ended_by: "rerun" }, ...(i ? [] : [{ ended_by: "push" }])] }));
  }

  cm.has_bench = true;
  cm.score = { score: r.score, group: pub ? "Kotlin, 1k-10k stars" : r.eco === "Go" ? "Go, all sizes" : "TypeScript, all sizes", repos: pub ? 318 : 1204, built_at: "NOW-6d",
    facts: [{ key: "first_answer_hours", name: "First answer to outside PRs", kind: "hours", you: r.answerH, typical: Math.round(r.answerH * 1.7 * 10) / 10, better_than: Math.min(95, r.score + 6) },
      { key: "newcomer_answered_share", name: "Newcomers answered within 2 weeks", kind: "share", you: cm.facts.newcomer_answered_share, typical: 0.71, better_than: Math.max(5, r.score - 6) }],
    left_out: ["newcomer_return_rate"] };
  cm.lever = { newcomers: 48213, repos: 3912, by_answer: [["within 1 day", 0.312], ["1-3 days", 0.268], ["3-14 days", 0.214], ["over 14 days", 0.171], ["no answer", 0.094]]
    .map(([bucket, returned], i) => ({ bucket, newcomers: [21004, 9120, 8210, 4410, 5469][i], returned })),
    by_outcome: [{ outcome: "merged", newcomers: 30120, returned: 0.331 }, { outcome: "closed unmerged", newcomers: 12544, returned: 0.142 }, { outcome: "still open", newcomers: 5549, returned: 0.088 }] };
  cm.answers = { ...cm.answers, left_out: pub ? { accounts: 1, items: 14 } : null };
  if (cm.traffic) cm.traffic.referrers_day = "NOW-1d";

  // Weekly pulse (core/pulse.py): counts only; the private repos have a digest issue with answers.
  if (!pub) {
    const wk = (i) => { const t = new Date(Date.UTC(2026, 9, 26) - (7 - i) * 7 * 86400000); return t.toISOString().slice(0, 10); };
    files["pulse.json"] = { weeks: Array.from({ length: 8 }, (_, i) => ({ week: wk(i), flow: { yes: 4 + (i % 3), no: 2, mixed: 1 }, friction: { yes: 3 + (i % 2), no: 3 - (i % 2), mixed: 1 },
      satisfaction: { yes: 5, no: 1, mixed: i % 2 } })), beside: { flow: "pickup", friction: "first_try", satisfaction: "deployments" }, min_answers: 5 };
  } else files["pulse.json"] = { weeks: [], beside: { flow: "pickup", friction: "first_try", satisfaction: "deployments" }, min_answers: 5 };
}
