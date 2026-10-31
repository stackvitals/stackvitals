// Demo data: three made-up repos in the real file shapes (app.json, data.json, flow.json...), written to app/demo/.
// Times are tokens ("NOW-12m", "MON-3") the app turns into dates when it reads a demo file, so the demo never ages.
// Every number shown in two places is worked out once here, so the pages agree with each other.

import { readFileSync } from "node:fs";
import { extendCi } from "./extra-ci.mjs";
import { extendDelivery } from "./extra-delivery.mjs";
import { extendDeps } from "./extra-deps.mjs";
import { extendPeople } from "./extra-people.mjs";
import { extendPortal } from "./extra-portal.mjs";

// Each extra adds the newer report fields to one repo's files (objects, before they are written).
const EXTRAS = [extendCi, extendDelivery, extendDeps, extendPeople, extendPortal];

// Every setting with its default and a few values set, as settings.json reads (made from core/schema.py; a test checks it).
const DEMO_SETTINGS = JSON.parse(readFileSync(new URL("./settings.json", import.meta.url), "utf8"));

// What connectors.json says after a few runs and Test connection checks (connectors/__init__.py and check.py shapes).
const DEMO_CONNECTORS = {
  "payments-api": {
    jira: { name: "Jira", as_of: "NOW-2h", key_expires: "NOW+120d", scope: "project in (PAY)", expiring: false, error: null, rows: { issue: 412, sprint: 9 }, complete: true,
      check: { ok: true, as: null, detail: "Signed in and read an issue from project PAY updated in the last 30 days.", checked_at: "NOW-3d", fix: null } },
    pagerduty: { name: "PagerDuty", as_of: "NOW-2h", key_expires: "NOW+9d", scope: null, expiring: true, error: null, rows: { issue: 23 }, complete: true },
    webhook: { name: "Chat webhooks", check: { ok: false, as: null, detail: "The webhook answered 404: the webhook was deleted or its address is wrong.",
      checked_at: "NOW-1d", fix: "Create a new incoming webhook and put it in the STACKVITALS_WEBHOOK secret (or the team's line in STACKVITALS_TEAM_WEBHOOKS)." } },
  },
  "web-app": {
    linear: { name: "Linear", as_of: "NOW-3h", key_expires: null, scope: null, expiring: false, error: null, rows: { issue: 230, sprint: 6 }, complete: false },
    copilot: { name: "Copilot", as_of: "NOW-3h", key_expires: null, scope: null, expiring: false, error: null, rows: { org_day: 58 }, complete: true },
  },
  mobile: {
    discourse: { name: "Discourse", as_of: "NOW-5h", key_expires: null, scope: null, expiring: false, error: null, rows: { topic: 118 }, complete: true },
  },
};

const W = 12;
const week = (i) => `NOW-${(W - 1 - i) * 7 + 3}d`;
const mon = (i, n = 6) => `MON-${n - 1 - i}`;
// Fixed day for what can't carry a time token (quarter names, table rows), so every build writes the same bytes.
const ANCHOR = Date.parse("2026-10-20T12:00:00Z");
const round = (x, d = 4) => Math.round(x * 10 ** d) / 10 ** d;
const sum = (a) => a.reduce((s, x) => s + x, 0);
const range = (n, f) => Array.from({ length: n }, (_, i) => f(i));
// A small repeatable wobble, so series look measured rather than drawn.
const wob = (i, k = 7, m = 11) => ((i * k) % m) / m - 0.5;

// Queue rows: [number, title, author, step, actor, who, why, days waiting, outsider?]
const REPOS = [
  {
    slug: "payments-api", repo: "acme/payments-api", visibility: "private", updated: "NOW-12m", lang: "Go", eco: "Go", team: ["payments-core", "ledger"],
    firstTry: [0.86, 0.85, 0.87, 0.84, 0.83, 0.85, 0.82, 0.8, 0.81, 0.79, 0.77, 0.78],
    flake: [3, 4, 3, 5, 5, 4, 6, 7, 7, 8, 9, 8], ttg: [12.1, 12.4, 12.0, 12.9, 13.1, 12.8, 13.4, 13.9, 13.5, 14.0, 14.6, 14.2],
    runs: [380, 402, 395, 410, 420, 415, 430, 441, 436, 450, 462, 455], pushes: 412,
    flaky: [
      { id: "TestSettlement/concurrent_refunds", kind: "test", flakes: 14, runs: 96, since: "NOW-36d", state: "flaky", hours: 17.5, msg: "context deadline exceeded" },
      { id: "integration / postgres-15", kind: "job", flakes: 9, runs: 120, since: "NOW-55d", state: "flaky", hours: 11.2 },
      { id: "TestWebhookRetry/timeout", kind: "test", flakes: 6, runs: 96, since: "NOW-22d", state: "flaky", hours: 7.9, msg: "expected 3 retries, got 2" },
      { id: "e2e / checkout-smoke", kind: "job", flakes: 4, runs: 88, since: "NOW-15d", state: "suspect", hours: 4.4 },
      { id: "TestLedger/rounding_eur", kind: "test", flakes: 0, runs: 96, since: "NOW-3d", state: "broken", hours: 0, msg: "want 10.05, got 10.04" },
    ],
    muted: { reason: "fix lands with the next release", by: "maya" },
    slow: [["integration / postgres-15", 9.8], ["e2e / checkout-smoke", 7.1], ["build / docker", 4.2], ["unit / go-test", 3.6], ["lint / golangci", 1.4]],
    opened: [31, 34, 29, 36, 38, 40], merged: [27, 30, 26, 33, 35, 37], open: 37, drafts: 5, closedUnmerged: 9,
    queue: [
      [1851, "Add idempotency keys to refund endpoint", "maya", "review", "reviewer", ["tomasz"], "review asked, not started", 4],
      [1829, "Document EUR rounding rules", "lena-k", "review", "reviewer", ["maya"], "review asked, not started", 11],
      [1846, "Bump pgx to v5.7", "dependabot", "checks", "author", ["dependabot"], "checks failing on a known flake", 6],
      [1833, "Split settlement worker into two queues", "dev-ravi", "changes", "author", ["dev-ravi"], "changes requested, no reply", 9],
      [1855, "Fix typo in webhook docs", "sam-oss", "review", "reviewer", ["lena-k"], "first contribution, waiting for a first review", 2, true],
      [1849, "Bump golang.org/x/net from 0.30.0 to 0.33.0", "dependabot", "review", "reviewer", ["tomasz"], "security update, no reviewer yet", 5],
      [1790, "Prototype: settlement replay tool", "tomasz", "author", "author", ["tomasz"], "draft-like, no push for weeks", 41],
      [1777, "Retry policy for card network timeouts", "dev-ravi", "changes", "author", ["dev-ravi"], "changes requested, no reply", 36],
    ],
    pickup: [6.8, 6.2, 7.1, 6.5, 6.0, 6.4, 5.8, 5.9, 5.5, 5.2, 5.0, 5.1], review: 18.4, merge: 2.2, coding: 20.5, deployH: 5.5,
    deploys: [34, 38, 41, 39, 44, 47], cfr: 0.09, lead: 30.5, recovery: 2.6, ai: 0.31, agentPrs: 6,
    tiers: { freq: "high", lead: "high", cfr: "high", recovery: "high" },
    waiting: [["issue", 2091, 3], ["pr", 1855, 2]], stars: [12, 9, 14, 11, 10, 16, 13, 12, 15, 18, 14, 17], starsTotal: 2140, score: 71, answerH: 9.5, answered1d: 0.72,
    deps: [
      [1849, "golang.org/x/net", "0.30.0", "0.33.0", "minor", true, 130],
      [1846, "github.com/jackc/pgx/v5", "5.6.0", "5.7.1", "minor", false, 144],
      [1858, "github.com/stretchr/testify", "1.9.0", "1.10.0", "minor", false, 52],
      [1861, "google.golang.org/grpc", "1.67.1", "1.68.0", "minor", false, 30],
      [1863, "github.com/aws/aws-sdk-go-v2/service/s3", "1.66.0", "1.66.3", "patch", false, 20],
      [1864, "golang.org/x/crypto", "0.28.0", "0.31.0", "minor", true, 11],
    ],
    bot: "dependabot", depsMerged: 38, depsMergeH: 30, lockfiles: ["go.sum"],
    vulns: [
      ["GHSA-w32m-9786-jp63", ["CVE-2024-45338", "GO-2024-3333"], "golang.org/x/net", "0.30.0", "high", "0.33.0", "go.sum", 9, "called"],
      ["GHSA-v778-237x-gjrc", ["CVE-2024-45337", "GO-2024-3321"], "golang.org/x/crypto", "0.28.0", "critical", "0.31.0", "go.sum", 4, "imported"],
      ["GHSA-xr7q-jx4m-x55m", ["CVE-2024-24786", "GO-2024-2611"], "google.golang.org/protobuf", "1.32.0", "moderate", "1.33.0", "go.sum", 31, "required"],
    ],
    findings: [
      { kind: "red_ci", title: "Flaky checks kept 23 PRs red for 41 h", action: "Fix or quarantine TestSettlement/concurrent_refunds first; it began right after #1842 merged.", hours: 41, n: 23, open_since: "2026-09-18", structural: true },
      { kind: "review_wait", action: "Ask maya or tomasz to pick up #1851 and #1829.", hours: 29, open_since: "2026-10-12" },
      { kind: "outsider_wait", title: "Outside contributors wait 2.4x longer for a first review", action: "Add a triage rotation for outside PRs.", hours: 12, n: 7, open_since: "2026-09-02", snooze: true },
    ],
    tracker: { sources: ["jira"], issues: 412, sprints: 9 },
  },
  {
    slug: "web-app", repo: "acme/web-app", visibility: "private", updated: "NOW-58m", lang: "TypeScript", eco: "npm", team: ["storefront", "checkout"],
    firstTry: [0.85, 0.86, 0.84, 0.87, 0.86, 0.88, 0.87, 0.88, 0.89, 0.87, 0.9, 0.91],
    flake: [5, 5, 6, 4, 4, 4, 3, 3, 3, 3, 2, 2], ttg: [10.2, 9.8, 10.0, 9.6, 9.4, 9.3, 9.1, 9.0, 8.8, 9.1, 8.6, 8.4],
    runs: [560, 575, 590, 600, 612, 608, 620, 633, 640, 655, 661, 670], pushes: 655,
    flaky: [
      { id: "checkout.spec.ts > applies coupon", kind: "test", flakes: 5, runs: 140, since: "NOW-24d", state: "flaky", hours: 3.1, msg: "Timed out 5000ms waiting for expect(locator).toBeVisible()" },
      { id: "playwright / webkit", kind: "job", flakes: 3, runs: 150, since: "NOW-20d", state: "flaky", hours: 2.2 },
      { id: "search.test.tsx > debounces input", kind: "test", flakes: 2, runs: 140, since: "NOW-7d", state: "suspect", hours: 0.9 },
    ],
    muted: { reason: "rewriting the search box this sprint", by: "jules" },
    slow: [["playwright / webkit", 6.4], ["playwright / chromium", 5.9], ["build / next", 3.1], ["unit / vitest", 2.2], ["lint / eslint", 0.9]],
    opened: [52, 55, 58, 54, 60, 63], merged: [49, 52, 55, 51, 58, 61], open: 22, drafts: 3, closedUnmerged: 11,
    queue: [
      [3307, "Migrate settings page to server actions", "jules", "review", "reviewer", ["noor"], "review asked, not started", 5],
      [3318, "Cache product images at the edge", "noor", "merge", "author", ["noor"], "approved, not merged yet", 1],
      [3320, "Bump next from 14.2.15 to 14.2.18", "renovate[bot]", "review", "reviewer", ["jules"], "update waiting for a review", 2],
      [3322, "Dark mode for the order history", "kai", "review", "reviewer", ["jules", "noor"], "in review", 1],
    ],
    pickup: [3.4, 3.1, 3.3, 3.0, 2.9, 3.0, 2.7, 2.6, 2.5, 2.4, 2.3, 2.2], review: 7.6, merge: 0.8, coding: 11.2, deployH: 1.1,
    deploys: [71, 78, 84, 80, 91, 96], cfr: 0.05, lead: 13.8, recovery: 1.2, ai: 0.44, agentPrs: 14,
    tiers: { freq: "elite", lead: "elite", cfr: "elite", recovery: "elite" },
    waiting: [], stars: [6, 5, 8, 7, 9, 6, 7, 8, 10, 9, 11, 12], starsTotal: 860, score: 82, answerH: 4.1, answered1d: 0.88,
    deps: [
      [3320, "next", "14.2.15", "14.2.18", "patch", false, 40],
      [3324, "@playwright/test", "1.48.2", "1.49.0", "minor", false, 18],
      [3326, "cross-spawn", "7.0.3", "7.0.6", "patch", true, 9],
    ],
    bot: "renovate", depsMerged: 61, depsMergeH: 9, lockfiles: ["package-lock.json"],
    vulns: [
      ["GHSA-3xgq-45jj-v275", ["CVE-2024-21538"], "cross-spawn", "7.0.3", "high", "7.0.5", "package-lock.json", 9, null],
      ["GHSA-mwcw-c2x4-8c55", ["CVE-2024-55565"], "nanoid", "3.3.7", "moderate", "3.3.8", "package-lock.json", 22, true],
      ["GHSA-pxg6-pf52-xh8x", ["CVE-2024-47764"], "cookie", "0.6.0", "low", "0.7.0", "package-lock.json", 40, false],
    ],
    findings: [
      { kind: "fix_job", title: "playwright / webkit re-runs cost 2.2 h", action: "Pin the WebKit browser version in CI.", hours: 2.2, n: 6, open_since: "2026-10-04" },
      { kind: "review_wait", action: "Assign a reviewer to #3307.", hours: 5, open_since: "2026-10-19" },
      { kind: "red_ci", title: "Failing checks kept 9 PRs red for 7 h", action: "Quarantine checkout.spec.ts > applies coupon until the coupon fix lands.", hours: 7, n: 9, open_since: "2026-10-01", snooze: true },
    ],
    tracker: { sources: ["linear"], issues: 230, sprints: 6 },
    queueMerge: true,
  },
  {
    slug: "mobile", repo: "acme/mobile", visibility: "public", updated: "NOW-3h", lang: "Kotlin", eco: "Maven", team: ["android"],
    firstTry: [0.81, 0.82, 0.8, 0.83, 0.84, 0.82, 0.83, 0.81, 0.82, 0.84, 0.82, 0.83],
    flake: [4, 4, 5, 4, 3, 5, 4, 5, 4, 4, 5, 4], ttg: [20.1, 20.6, 21.0, 21.4, 21.2, 21.9, 22.0, 21.6, 22.3, 21.8, 22.1, 22.5],
    runs: [150, 148, 152, 140, 138, 135, 130, 128, 126, 122, 120, 118], pushes: 188,
    flaky: [
      { id: "connectedAndroidTest / api-30", kind: "job", flakes: 7, runs: 60, since: "NOW-52d", state: "flaky", hours: 8.8 },
      { id: "LoginViewModelTest.emitsError", kind: "test", flakes: 3, runs: 60, since: "NOW-13d", state: "flaky", hours: 2.4, msg: "kotlinx.coroutines.TimeoutCancellationException" },
    ],
    muted: { reason: "coroutine test rule lands next week", by: "ines" },
    slow: [["connectedAndroidTest / api-30", 18.9], ["assembleRelease", 9.2], ["detekt", 2.8], ["unit", 2.5], ["ktlint", 0.7]],
    opened: [18, 17, 15, 14, 13, 11], merged: [16, 15, 12, 12, 10, 8], open: 19, drafts: 2, closedUnmerged: 6,
    queue: [
      [712, "Offline mode for orders tab", "ines", "review", "reviewer", ["marek"], "review asked, not started", 8],
      [709, "Upgrade AGP to 8.7", "renovate[bot]", "checks", "author", ["renovate[bot]"], "checks failing", 12],
      [701, "Fix crash on rotate in checkout", "first-timer-joe", "review", "reviewer", ["ines", "marek"], "outside contributor, no reply", 15, true],
      [688, "Compose migration: cart screen", "marek", "changes", "author", ["marek"], "changes requested, no reply", 34],
      [672, "Biometric login", "ines", "review", "reviewer", ["marek"], "review asked, not started", 44],
    ],
    pickup: [7.9, 8.2, 8.8, 9.1, 8.9, 9.6, 10.1, 10.4, 10.9, 11.0, 11.6, 11.4], review: 30.2, merge: 6.5, coding: 38.0, deployH: 52.0,
    deploys: [24, 22, 19, 17, 14, 12], cfr: 0.14, lead: 118, recovery: 21.5, ai: 0.12, agentPrs: 1,
    tiers: { freq: "medium", lead: "medium", cfr: "medium", recovery: "medium" },
    waiting: [["pr", 701, 15], ["issue", 698, 6], ["issue", 705, 4], ["issue", 707, 2]], stars: [4, 3, 5, 2, 3, 4, 2, 3, 2, 3, 2, 2], starsTotal: 310, score: 48, answerH: 31, answered1d: 0.41,
    deps: [
      [709, "com.android.tools.build:gradle", "8.6.1", "8.7.0", "minor", false, 288],
      [714, "com.squareup.okio:okio", "3.2.0", "3.4.0", "minor", true, 70],
    ],
    bot: "renovate", depsMerged: 9, depsMergeH: 96, lockfiles: ["gradle.lockfile"],
    vulns: [
      ["GHSA-w33c-445m-f8w7", ["CVE-2023-3635"], "com.squareup.okio:okio", "3.2.0", "moderate", "3.4.0", "gradle.lockfile", 70, null],
    ],
    findings: [
      { kind: "review_wait", title: "Reviews start 28% later than in August", action: "Two reviewers carry 80% of reviews; add a third to CODEOWNERS.", hours: 34, n: 11, open_since: "2026-08-20", structural: true },
      { kind: "fix_job", title: "connectedAndroidTest re-runs cost 8.8 h", action: "Move emulator tests to a nightly job.", hours: 8.8, n: 9, open_since: "2026-09-02" },
      { kind: "outsider_wait", title: "An outside fix waits 15 days for a reply", action: "Reply on #701.", hours: 15, n: 1, open_since: "2026-10-09" },
      { kind: "bump_red", title: "Update PRs sit red for days", action: "Fix the AGP 8.7 build so #709 can merge.", hours: 6, n: 2, open_since: "2026-10-13", snooze: true },
    ],
    forum: true,
  },
];

const SERIOUS = new Set(["critical", "high"]);

// Everything derived once per repo, so app.json facts, Overview and each page read the same numbers.
function derive(r) {
  const last = W - 1;
  const merged90 = sum(r.merged.slice(3)), deploys90 = sum(r.deploys.slice(3)), merged180 = sum(r.merged);
  const queue = r.queue.map(([n, title, author, step, actor, who, why, days, outsider]) => ({ n, title, author, step, actor, who, why, days, outsider: !!outsider }));
  const hanging = queue.filter((q) => q.step === "review" && q.why.startsWith("review asked") && q.days >= 3);
  const stale = queue.filter((q) => q.days > 30).length;
  const p75 = r.pickup[last], p50 = round(p75 * 0.45, 1);
  const failed = Math.round(r.cfr * deploys90);
  const flaky = r.flaky.filter((f) => f.state === "flaky").length, broken = r.flaky.filter((f) => f.state === "broken").length;
  const vulns = r.vulns.map(([id, aliases, pkg, version, severity, fixed, file, age, reach]) => ({ id, aliases, pkg, version, severity, fixed, file, age, reach }));
  const muted = r.flaky[r.flaky.length - 1];
  const findings = r.findings.map((f) => f.kind === "review_wait" && !f.title
    ? { ...f, n: hanging.length, title: `${hanging.length} review ${hanging.length === 1 ? "request" : "requests"} not started after 3 days` } : f);
  return { merged90, deploys90, merged180, queue, hanging, stale, p75, p50, failed, flaky, broken, vulns, muted, findings,
    cycleP75: round(p75 + r.review + r.merge, 1), pickupN: Math.round(merged90 * 0.86) };
}

function decisionsFor(r, d) {
  const snoozed = d.findings.find((f) => f.snooze);
  const mute = { verb: "mute", kind: "test", id: d.muted.id, by: r.muted.by, until: "NOW+5d", reason: r.muted.reason, at: "NOW-9d" };
  if (d.muted.kind === "job") mute.kind = "job";
  const snooze = snoozed ? { verb: "snooze", kind: "finding", id: snoozed.kind, by: "tomasz", until: "NOW+9d", reason: "release week", at: "NOW-5d" } : null;
  return { mute, snooze };
}

function ci(r, d, dec) {
  const tests = [], jobs = [];
  const wf = ".github/workflows/ci.yml";
  for (const f of r.flaky) {
    const decision = f.id === d.muted.id ? dec.mute : null;
    const base = { runs: f.runs, failures: f.state === "broken" ? f.runs : f.flakes, flake_events: f.flakes, flake_rate: round(f.flakes / f.runs),
      rate_low: round(Math.max(0, f.flakes / f.runs - 0.04)), rate_high: round(f.flakes / f.runs + 0.05), state: f.state, since: f.since,
      last_flake: f.flakes ? "NOW-1d" : null, monitors: f.state === "broken" ? ["broken"] : ["pass_on_retry"], labels: f.state === "flaky" ? ["timing"] : [],
      retry_minutes: Math.round(f.hours * 60), prs_affected: range(Math.min(6, f.flakes), (i) => 1800 + i * 7),
      evidence: range(Math.min(4, f.flakes), (i) => ({ run: 11800000 + i * 911, att: 2, kind: i % 2 ? "flip" : "retry" })), decision };
    if (f.kind === "test") tests.push({ id: f.id, suite: "test-results", workflow: wf, message: f.msg || null, owners: ["@acme/core"], ...base });
    else { const [w, job] = f.id.split(" / "); jobs.push({ workflow: `.github/workflows/${w}.yml`, job, top_step: "Run tests", median_s: 300, p95_s: 520, trend: [], ...base }); }
  }
  for (const [name, min] of r.slow) {
    if (r.flaky.some((f) => f.id === name)) { const j = jobs.find((x) => `${x.workflow.split("/").pop().replace(".yml", "")} / ${x.job}` === name); if (j) { j.median_s = min * 60; j.p95_s = Math.round(min * 84); j.trend = range(10, (i) => [`NOW-${10 - i}d`, Math.round(min * 60 * (0.9 + ((i * 7) % 5) / 25))]); } continue; }
    const [w, job] = name.includes(" / ") ? name.split(" / ") : ["ci", name];
    jobs.push({ workflow: `.github/workflows/${w}.yml`, job, runs: 120, failures: 0, flake_events: 0, flake_rate: 0, rate_low: 0, rate_high: 0.03, state: "ok",
      median_s: min * 60, p95_s: Math.round(min * 80), retry_minutes: 0, trend: range(10, (i) => [`NOW-${10 - i}d`, Math.round(min * 60 * (0.92 + ((i * 3) % 4) / 30))]) });
  }
  tests.push({ id: `${r.slug}/smoke::boots`, suite: "test-results", workflow: wf, runs: 96, failures: 0, flake_events: 0, flake_rate: 0, rate_low: 0, rate_high: 0.03, state: "ok" });
  const last = W - 1;
  return {
    schema: 1, window_days: 30, generated: r.updated, runs: sum(r.runs.slice(-4)), rerun_share: round(r.flake[last] / 40), infra_events: 1,
    queue: { median_s: 8, p95_s: 41 }, minutes: { linux: 4210, windows: 0, macos: r.lang === "Kotlin" ? 820 : 0, other: 0 },
    pushes: { pushes: r.pushes, median_s: Math.round(r.ttg[last] * 60), p90_s: Math.round(r.ttg[last] * 95), first_try_share: r.firstTry[last],
      first_try_range: [round(r.firstTry[last] - 0.03), round(r.firstTry[last] + 0.03)], median_range_s: [Math.round(r.ttg[last] * 55), Math.round(r.ttg[last] * 66)],
      // The pushes behind the first-try share, newest first, in the shape push_stats() publishes.
      not_first_try: range(Math.min(15, Math.round(r.pushes * (1 - r.firstTry[last]))), (i) => [(0x7c41e20 + i * 0x2f1b9).toString(16), i % 4 === 3 ? `feature/x-${i}` : "main", [4810000 + i * 37]]),
      not_first_try_total: Math.round(r.pushes * (1 - r.firstTry[last])) },
    weekly: r.firstTry.map((v, i) => ({ week: week(i), job_runs: r.runs[i], flakes: Math.round(r.runs[i] * r.flake[i] / 100), flake_share: r.flake[i], push_median_s: Math.round(r.ttg[i] * 60), first_try_share: v })),
    changes: [
      { metric: "ci.first_try_green", label: "pushes green on the first try", now: r.firstTry[last], base: r.firstTry[last - 4], unit: "share", note: null,
        changed: Math.abs(r.firstTry[last] - r.firstTry[last - 4]) > 0.03, direction: r.firstTry[last] > r.firstTry[last - 4] ? "up" : "down", detectable: 0.05 },
      { metric: "ci.flaky_runs", label: "flaky job runs", now: Math.round(r.runs[last] * r.flake[last] / 100), base: Math.round(r.runs[last - 4] * r.flake[last - 4] / 100), unit: "count", note: null, changed: false, direction: null, detectable: 2.1 },
    ],
    tests, jobs,
    failure_groups: [{ id: "a1", type: "TimeoutError", where: `${r.flaky[0].id}`, message: r.flaky[0].msg || "job exceeded its time limit", failures: r.flaky[0].flakes, tests: 2, runs: r.flaky[0].flakes,
      first: r.flaky[0].since, last: "NOW-1d", prompt: `Investigate a recurring CI failure in ${r.repo}: ${r.flaky[0].id} fails with a timeout, then passes on a re-run.` }],
    slow_tests: r.flaky.filter((f) => f.kind === "test").map((f, i) => ({ id: f.id, median_ms: 2400 - i * 700, p95_ms: 6100 - i * 1200, samples: f.runs, slower: i === 0 ? { pct: 18 } : null,
      trend: range(8, (k) => [`NOW-${8 - k}d`, 2000 + ((k * 37) % 9) * 60]) })),
    new_tests: [{ id: `${r.slug}/refunds::partial`, suite: "test-results", first: "NOW-5d", runs: 14, failures: 0, flake_events: 0, state: "ok" }],
    skipped_tests: [{ id: `${r.slug}/legacy::export_csv`, suite: "test-results", suites: 1, since: "NOW-40d", new: false, days: 40 }],
    coverage: { latest: { pct: 0.74, covered: 7410, lines: 10014, at: "NOW-3h" }, change: 0.012,
      trend: range(30, (i) => [`NOW-${30 - i}d`, round(0.728 + i * 0.0004 + ((i * 13) % 5) / 1000)]),
      prs: [{ pr: d.queue[0].n, pct: 0.92, covered: 46, lines: 50, missed: { "internal/refund/idem.go": [41, 42, 77, 78] }, at: "NOW-6h" }, { pr: d.queue[2].n, pct: 0, covered: 0, lines: 0, missed: {}, at: "NOW-2d" }] },
    has_test_reports: true,
    // One sample comparison (ci/bench.py shape) so Where you stand shows; real ones need the crawl's published files.
    benchmark: r.slug === "web-app" ? { group: "TypeScript, 1k-10k stars", repos: 412, metrics: [
      { name: "Time from push to all checks done", kind: "time", you: 612, typical: 540, place: "slower than about 58%" },
      { name: "Pushes green on the first try", kind: "share", you: 0.81, typical: 0.86, place: "below about 62%" }] } : null,
  };
}

const stage = (h, n) => ({ median_s: h === null ? null : Math.round(h * 3600), p90_s: h === null ? null : Math.round(h * 3600 * 2.6), n });

function flow(r, d) {
  const st = { pickup: stage(d.p50, d.pickupN), review: stage(round(r.review * 0.5, 1), d.pickupN - 3), merge: stage(round(r.merge * 0.5, 1), d.merged90 - 4),
    cycle: stage(round(d.cycleP75 * 0.48, 1), d.merged90) };
  const measure = (metric, v, n, unit) => ({ metric, version: 1, value: v, n, low: v === null ? null : Math.round(v * 0.85), high: v === null ? null : Math.round(v * 1.2), unit, as_of: r.updated, window_days: 90, note: null });
  const outN = Math.max(3, Math.round(d.merged90 * 0.08));
  return { schema: 1, generated: r.updated, window_days: 90, open: r.open, drafts: r.drafts, merged: d.merged90, closed_unmerged: r.closedUnmerged, stages: st,
    merged_without_review: Math.round(d.merged90 * 0.03),
    groups: {
      insider: { merged: d.merged90 - outN, closed_unmerged: r.closedUnmerged - 2, merge_rate: 0.92, merged_without_review: Math.round(d.merged90 * 0.03),
        pickup: st.pickup, review: st.review, merge: st.merge, cycle: st.cycle },
      outsider: { merged: outN, closed_unmerged: 2, merge_rate: round(outN / (outN + 2), 2), merged_without_review: 0,
        pickup: stage(round(d.p50 * 2.4, 1), outN), review: stage(round(r.review * 0.7, 1), outN), merge: stage(round(r.merge * 0.6, 1), outN), cycle: stage(round(d.cycleP75 * 0.9, 1), outN) },
    },
    queue: d.queue.map((q) => ({ n: q.n, title: q.title, author: q.author, outsider: q.outsider, actor: q.actor, who: q.who, why: q.why, since: `NOW-${q.days}d`, step: q.step,
      waiting_s: q.days * 86400, usual_s: q.step === "review" ? Math.round(d.p50 * 3600) : null, stale: q.days > 30, slow: q.days > 3, gaps: [] })),
    stale: d.stale,
    load: [...new Set(d.queue.filter((q) => q.actor === "reviewer").flatMap((q) => q.who))].map((who) => ({ reviewer: who, open_requests: d.queue.filter((q) => q.actor === "reviewer" && q.who.includes(who)).length })),
    monthly: r.opened.map((o, i) => ({ month: mon(i), opened: o, merged: r.merged[i], pickup_median_s: Math.round(d.p50 * (1.25 - i * 0.05) * 3600), cycle_median_s: Math.round(d.cycleP75 * 0.48 * (1.2 - i * 0.04) * 3600) })),
    bots: { open: r.deps.length, closed: r.depsMerged },
    measures: { "flow.pickup_time": measure("flow.pickup_time", st.pickup.median_s, st.pickup.n, "s"), "flow.cycle_time": measure("flow.cycle_time", st.cycle.median_s, st.cycle.n, "s"),
      "flow.open_prs": { metric: "flow.open_prs", version: 1, value: r.open, n: r.open, low: null, high: null, unit: "count", as_of: r.updated, window_days: null, note: null } },
    habits: { scope: "whole repo", merged_prs: d.merged90, include: { tests: 0.64, docs: 0.18, changelog: 0.41 }, size: { median_lines: 86, p75_lines: 210, p90_lines: 520 },
      asks: [{ ask: "tests", share: 0.21, prs: Math.round(d.merged90 * 0.21) }, { ask: "a smaller pull request", share: 0.08, prs: Math.round(d.merged90 * 0.08) }] },
    excluded: 0 };
}

function delivery(r, d) {
  const deps = d.deploys90, phase = (n, p50, p75, band) => ({ n, enough: n >= 10, p50_h: p50, p75_h: p75, low_h: round(p75 * 0.85, 1), high_h: round(p75 * 1.2, 1), linearb_band: band });
  const band = r.tiers.lead === "elite" ? "elite" : r.tiers.lead === "high" ? "good" : "fair";
  const days = Math.min(63, Math.round(deps * 0.55)), perWeek = round(days / 13, 1);
  const releases = range(10, (i) => ({ id: `dep-${i}`, name: r.lang === "Kotlin" ? `v3.${18 + i}.0` : "production", sha: (0x9a3c1f0 + i * 0x1b2d3).toString(16), finished: `NOW-${(10 - i) * (r.lang === "Kotlin" ? 7 : 1) + 1}d` }));
  const incidents = range(d.failed, (i) => ({ number: 2000 + i * 13, source: i % 3 === 2 ? "pull" : "issue", created: `NOW-${(i * 83) % 88 + 2}d`, hours_to_restore: round(r.recovery * (0.5 + ((i * 7) % 10) / 10), 1) }));
  const agMerged = Math.round(d.merged90 / 6.5), slowReview = d.hanging.length + 1;
  const weekly = (n) => range(W, (i) => [week(i), Math.max(0, Math.round(n * (0.6 + wob(i) )))]);
  const assistedN = Math.round(d.merged180 * r.ai), others = d.merged180 - assistedN - r.agentPrs;
  const side = (n, pick, rev, size, failed, flaky, revert) => ({ n, pickup_p75_h: pick, review_p75_h: rev, size_p75: size, ci_n: Math.round(n * 0.9), ci_failed_share: failed, flaky_share: flaky, reverted_share: revert, failed_deploy_share: r.cfr, merge_rate: 0.9, merge_rate_n: n });
  const cmp = (of, gap, verdict) => ({ matched: Math.round(of * 0.8), of, matched_share: 0.8, gap, low: round(gap - 0.06, 2), high: round(gap + 0.06, 2), detectable: 0.08, verdict });
  const teams = Object.fromEntries(r.team.map((t, i) => [t, { n: Math.round(d.merged90 / r.team.length), pickup: { enough: true, p75_h: round(d.p75 * (1 + (i ? 0.2 : -0.1)), 1) }, cycle_to_merge: { enough: true, p75_h: round(d.cycleP75 * (1 + (i ? 0.15 : -0.05)), 1) } }]));
  const invCounts = (n, i) => { const f = Math.round(n * (0.42 - i * 0.01)), x = Math.round(n * 0.24), m = Math.round(n * 0.16), s = Math.round(n * 0.05), dc = Math.round(n * 0.06); return { feature: f, fix: x, maintenance: m, security: s, docs: dc, other: n - f - x - m - s - dc }; };
  const months = r.merged.map((n, i) => ({ month: mon(i), n, counts: invCounts(n, i) }));
  const counts = {}; for (const m of months) for (const [k, v] of Object.entries(m.counts)) counts[k] = (counts[k] || 0) + v;
  const t = r.tracker;
  return {
    schema: 1, generated: r.updated, window_days: 90, since: "NOW-90d", prs: d.merged90,
    agreements: { rules: { review_within_hours: 24, max_pr_lines: 400 }, labels: { review_within_hours: "First review within 24 h", max_pr_lines: "PRs under 400 lines" }, window_days: 14, merged: agMerged,
      counts: { review_within_hours: slowReview, max_pr_lines: 2 },
      exceptions: [...d.hanging.map((q) => ({ pr: q.n, rule: "review_within_hours", value: q.days * 24, limit: 24, open: true, at: r.updated })),
        { pr: d.queue[d.queue.length - 1].n - 3, rule: "review_within_hours", value: 31.5, limit: 24, open: false, at: "NOW-6d" },
        { pr: d.queue[0].n - 7, rule: "max_pr_lines", value: 812, limit: 400, open: false, at: "NOW-4d" }, { pr: d.queue[0].n - 11, rule: "max_pr_lines", value: 455, limit: 400, open: false, at: "NOW-10d" }],
      weekly: { review_within_hours: weekly(slowReview / 2), max_pr_lines: weekly(1) } },
    deploy_source: r.lang === "Kotlin" ? "releases" : "deployments api", deploy_confidence: "high", incident_source: t ? `GitHub issues, reverts and hotfixes, and ${t.sources[0] === "jira" ? "Jira" : "Linear"}` : "GitHub issues, reverts and hotfixes",
    deploy_check: { source: r.lang === "Kotlin" ? "releases" : "deployments api", deployments: deps,
      considered: [{ source: "deployments api", found: r.lang === "Kotlin" ? 0 : deps, used: r.lang !== "Kotlin" }, { source: "releases", found: r.lang === "Kotlin" ? deps : 6, used: r.lang === "Kotlin" }, { source: "deploy workflows", found: r.lang === "Kotlin" ? 0 : deps + 4, used: false }],
      order_reason: null, workflows: [{ name: "CI", path: ".github/workflows/ci.yml", counted: 0, skipped: 0, kind: null, why: "its name doesn't match deploy_workflow", used: false },
        { name: "StackVitals", path: ".github/workflows/stackvitals.yml", counted: 0, skipped: 0, kind: null, why: "its name doesn't match deploy_workflow", used: false }] },
    deployments: releases,
    phases: { coding: phase(d.merged90, round(r.coding * 0.4, 1), r.coding, band), pickup: phase(d.pickupN, d.p50, d.p75, band), review: phase(d.pickupN - 3, round(r.review * 0.5, 1), r.review, band),
      approve: phase(d.pickupN - 3, round(r.review * 0.3, 1), round(r.review * 0.7, 1), band), merge: phase(d.merged90 - 4, round(r.merge * 0.5, 1), r.merge, band),
      deploy: phase(d.merged90 - 6, round(r.deployH * 0.5, 1), r.deployH, band), cycle: phase(d.merged90 - 6, round((d.cycleP75 + r.coding + r.deployH) * 0.45, 1), round(d.cycleP75 + r.coding + r.deployH, 1), band),
      cycle_to_merge: phase(d.merged90, round(d.cycleP75 * 0.48, 1), d.cycleP75, band) },
    outliers: { over_60_days: 1, over_p98: 2 },
    dora: { report: "2023", deployments: deps, deployment_days: days, deployment_days_per_week: perWeek, deployment_days_per_month: round(days / 3, 1), frequency_tier: r.tiers.freq,
      monthly: r.deploys.map((n, i) => ({ month: mon(i), deployments: n })),
      lead_time_hours: r.lead, lead_time_n: d.merged90 - 6, lead_time_tier: r.tiers.lead, lead_time_range_hours: [round(r.lead * 0.85, 1), round(r.lead * 1.2, 1)], lead_time_tier_span: null,
      change_failure_rate: r.cfr, failed_deployments: d.failed, cfr_tier: r.tiers.cfr, cfr_range: [round(Math.max(0, r.cfr - 0.03), 3), round(r.cfr + 0.04, 3)], cfr_tier_span: r.cfr === 0.09 ? ["high", "medium"] : null,
      cfr_fix_chain: null, linkage: { reverts: Math.max(1, d.failed - 3), fix_chain_found: Math.max(1, d.failed - 4), disagree: 0, never_shipped: 0 },
      recovery_hours: r.recovery, recovery_n: d.failed, recovery_tier: r.tiers.recovery, recovery_range_hours: [round(r.recovery * 0.7, 1), round(r.recovery * 1.5, 1)], recovery_tier_span: null,
      // What each number was computed from, in the shape delivery.dora() publishes.
      evidence: { deployments: range(deps, (i) => [(0x9a3c1f0 + i * 0x1b2d3).toString(16), `NOW-${Math.max(1, 90 - Math.floor(i * 90 / deps))}d`]),
        lead_time: range(Math.min(12, d.merged90 - 6), (i) => [d.queue[0].n - 20 - i * 3, releases[i % 10].sha, Math.round(r.lead * 60 * (2.2 - i * 0.15))]),
        lead_time_total: d.merged90 - 6,
        failed: incidents.map((x, i) => [releases[(i * 3) % 10].sha, x.source === "pull" ? "revert" : "issue", x.number]),
        recovery: incidents.map((x, i) => [releases[(i * 3) % 10].sha, x.source === "pull" ? "revert" : "issue", x.number, Math.round(x.hours_to_restore * 60)]) },
      rework_rate: round(Math.max(1, d.failed - 2) / deps, 3), rework_deployments: Math.max(1, d.failed - 2), deployments_n: deps, rework_range: [round(Math.max(1, d.failed - 2) / deps * 0.6, 3), round(Math.max(1, d.failed - 2) / deps * 1.6, 3)] },
    changes: [
      { metric: "delivery.pickup", label: "pickup", now: d.p75, base: r.pickup[W - 5], unit: "h", note: null, changed: Math.abs(d.p75 - r.pickup[W - 5]) > 1, direction: d.p75 > r.pickup[W - 5] ? "up" : "down", detectable: 1.4 },
      { metric: "delivery.deployments", label: "deployments", now: Math.round(r.deploys[5] / 4.3), base: Math.round(r.deploys[4] / 4.3), unit: "count", note: null, changed: false, direction: null, detectable: 1.6 },
      { metric: "delivery.change_failure", label: "deployments that failed", now: r.cfr, base: r.cfr, unit: "share", note: null, changed: false, direction: null, detectable: 0.06 },
    ],
    incidents,
    stuck: { hanging_review: d.hanging.map((q) => ({ pr: q.n, since: `NOW-${q.days}d` })), long_lived: d.queue.filter((q) => q.days > 30).map((q) => ({ pr: q.n, since: `NOW-${q.days}d`, why: q.why })),
      high_interaction: [], red_and_idle: d.queue.filter((q) => q.step === "checks").map((q) => ({ pr: q.n, since: `NOW-${q.days}d`, why: q.why })) },
    by_team: teams, by_owner: {},
    // A monorepo's services (delivery.by_service): the storefront deploys on its own, checkout has no deploy pattern yet.
    by_service: r.slug === "web-app" ? {
      storefront: { prs: 41, n: 41, pickup: { n: 41, enough: true, p50_h: 1.4, p75_h: 3.1 }, cycle_to_merge: { n: 41, enough: true, p50_h: 9.5, p75_h: 22.0 },
        review: { n: 41, enough: true, p50_h: 2.0, p75_h: 5.5 }, deployments: 38,
        dora: { deployment_days_per_week: 3, frequency_tier: "high", lead_time_hours: 26.4, lead_time_tier: "high", change_failure_rate: 0.079, cfr_tier: "medium" } },
      checkout: { prs: 17, n: 17, pickup: { n: 17, enough: true, p50_h: 2.2, p75_h: 6.8 }, cycle_to_merge: { n: 17, enough: true, p50_h: 14.0, p75_h: 41.5 },
        review: { n: 17, enough: true, p50_h: 3.1, p75_h: 9.0 } },
    } : null,
    tracker: t ? { sources: t.sources, issues: t.issues, merged_prs: d.merged90, linked_prs: Math.round(d.merged90 * 0.7), incidents: Math.max(1, d.failed - 5),
      lead_time: { REQUIREMENT: { n: 64, lead_p50_h: 190, lead_p75_h: 410, cycle_p50_h: 52, cycle_p75_h: 120 }, BUG: { n: 71, lead_p50_h: 60, lead_p75_h: 160, cycle_p50_h: 14, cycle_p75_h: 40 }, TASK: { n: 38, lead_p50_h: 96, lead_p75_h: 220, cycle_p50_h: 20, cycle_p75_h: 61 } },
      planning: range(t.sprints, (i) => ({ name: `${t.sources[0] === "jira" ? "PAY Sprint" : "Cycle"} ${30 + i}`, state: i === t.sprints - 1 ? "ACTIVE" : "CLOSED", scope: 24 + (i * 5) % 7, done: 19 + (i * 3) % 5, carried_over: 3 + i % 3, added_after_start: 2 + i % 2, points_scope: 40 + i, points_done: 32 + i })) } : null,
    investment: { since: mon(0), months, n: d.merged180, counts, shares: Object.fromEntries(Object.entries(counts).map(([k, v]) => [k, round(v / d.merged180, 3)])),
      decided_by: { label: Math.round(d.merged180 * 0.38), ...(t ? { issue: Math.round(d.merged180 * 0.22) } : {}), title: Math.round(d.merged180 * 0.25), only: Math.round(d.merged180 * 0.08), other: counts.other }, bots: r.depsMerged },
    epics: t ? { since: mon(0), linked: Math.round(d.merged180 * 0.6), no_epic: Math.round(d.merged180 * 0.12), feature_share: 0.46,
      epics: [["Refund rework", 0.31], ["Card network v2", 0.22], ["Ledger audit", 0.15]].map(([title, share], i) => ({ epic: `${t.sources[0] === "jira" ? "PAY" : "WEB"}-${100 + i * 17}`, title: t.sources[0] === "jira" ? title : ["Checkout redesign", "Search speed", "Accounts"][i], prs: Math.round(d.merged180 * 0.6 * share), share })) } : null,
    ai: { agent_prs: { n: r.agentPrs + 2, merged: r.agentPrs, merged_share: round(r.agentPrs / (r.agentPrs + 2), 2) },
      assisted_prs: { n: assistedN, share: r.ai, tools: { copilot: Math.round(assistedN * 0.6), claude: Math.round(assistedN * 0.4) }, pickup_p75_h: round(d.p75 * 1.1, 1), others_pickup_p75_h: d.p75, size_p75: 240, others_size_p75: 190 },
      ai_reviewed_prs: { n: Math.round(d.merged180 * 0.2) },
      // The agent work ledger (core/agent_ledger.py): each agent, the review load, what open PRs can expect.
      by_agent: r.agentPrs >= 10 ? {
        "copilot agent": { prs: Math.round(r.agentPrs * 0.6), decided: Math.round(r.agentPrs * 0.75), merge_rate: 0.79, review_rounds_p50: 3,
          window: { n: Math.round(r.agentPrs * 0.6), review_p75_h: round(r.review * 1.6, 1), ci_failed_share: 0.24, reverted_share: 0.04 } },
        "claude agent": { prs: Math.round(r.agentPrs * 0.4), decided: Math.round(r.agentPrs * 0.45), merge_rate: 0.88, review_rounds_p50: 2,
          window: { n: Math.round(r.agentPrs * 0.4), review_p75_h: round(r.review * 1.2, 1), ci_failed_share: 0.17, reverted_share: 0.02 } } } : {},
      review_load: { weeks: range(6, (i) => ({ week_end: `NOW-${(5 - i) * 7}d`, opened: { agent: 4 + i * 2, person: 14 + (i % 3) }, merged: { agent: 3 + i, person: 13 + (i % 2) } })),
        waiting: { agent: 9, person: 4 }, reviewers: { n: 7, max_open: 6, agent_share: 0.58 } },
      expected_review: d.queue.slice(0, 4).map((q, i) => ({ pr: q.n, kind: i % 3 === 0 ? "agent" : "person", similar: 14 + i, p50_h: round(r.review * (0.8 + i * 0.15), 1), p75_h: round(r.review * (1.6 + i * 0.2), 1) })),
      outcomes: { window: { agent: side(r.agentPrs, round(d.p75 * 1.4, 1), r.review, 120, 0.22, 0.05, 0.02), assisted: side(assistedN, round(d.p75 * 1.1, 1), r.review, 240, 0.18, 0.06, 0.02), others: side(others, d.p75, r.review, 190, 0.15, 0.05, 0.01) },
        matched: { assisted: { ci_failed: cmp(assistedN, 0.03, "no measurable difference"), reverted: cmp(assistedN, 0.0, "no measurable difference"), merged: cmp(assistedN, -0.01, "no measurable difference") },
          agent: { ci_failed: cmp(Math.max(r.agentPrs, 1), 0.07, r.agentPrs >= 5 ? "higher" : "too few"), merged_by_others: cmp(Math.max(r.agentPrs, 1), 0.12, r.agentPrs >= 5 ? "higher" : "too few") } },
        coverage: { people_prs: d.merged180 - r.agentPrs, marked: assistedN, marked_share: r.ai, authors: 14, authors_marking: 6 },
        monthly: r.merged.map((n, i) => ({ month: mon(i), agent: { n: Math.round(r.agentPrs / 6) }, assisted: { n: Math.round(n * r.ai * (0.8 + i * 0.05)) }, others: { n: n - Math.round(n * r.ai * (0.8 + i * 0.05)) } })) },
      copilot: r.slug === "web-app" ? { org: "acme", window_days: 28, days_kept: 58, first_day: "NOW-58d", monthly_active_users: 23, monthly_active_agent_users: 7, acceptance: 0.31,
        org_prs_by_copilot: 19, org_prs_merged_by_copilot: 14, repo_prs_by_copilot: 9, repo_prs_merged_by_copilot: 7 } : null, baseline: null },
    merge_queue: r.queueMerge ? { prs: 142, merged: 136, window_days: 90, p50_h: 0.6, p90_h: 1.9, removals: { CI_FAILURE: 4, MERGE_CONFLICT: 2 }, failed_runs: 9, runs: 151,
      removed_by_flakes: [{ pr: 3290, at: "NOW-12d", jobs: ["playwright / webkit"] }, { pr: 3301, at: "NOW-6d", jobs: ["playwright / webkit"] }] } : null,
    excluded: 0,
    peers: r.slug === "web-app" ? { group: "TypeScript, 1k-10k stars", repos: 388, metrics: [
      { key: "pickup_p75_hours", name: "Pickup: opened to first maintainer review (P75)", you: 6.2, typical: 9.8, place: "faster than about 61%" },
      { key: "cycle_to_merge_p75_hours", name: "Opened to merged (P75)", you: 41, typical: 52, place: "faster than about 55%" }] } : null,
  };
}

function alerts(r, d) {
  // Day by day over 84 days; the last day is exactly the figure the pages show.
  const daily = (weeks, lastV, n) => range(84, (i) => { const w = Math.min(W - 1, Math.floor(i / 7)); const v = i === 83 ? lastV : round(weeks[w] * (1 + wob(i) / 6), 2); return [`NOW-${84 - i}d`, v, n]; });
  const scale = (k) => r.pickup.map((p) => p * k);
  return { schema: 1, window_days: 28, heads_up: 0.8, min_n: 10, limits: { pickup_p75_hours: 5.0, review_p75_hours: 20.0, cycle_p75_hours: 72.0, change_failure_rate: 0.15 },
    names: { pickup_p75_hours: "pickup time P75 (hours)", review_p75_hours: "review time P75 (hours)", cycle_p75_hours: "cycle time to merge P75 (hours)", change_failure_rate: "change failure rate" },
    series: { pickup_p75_hours: daily(r.pickup, d.p75, 14), review_p75_hours: daily(scale(r.review / d.p75), r.review, 13), cycle_p75_hours: daily(scale(d.cycleP75 / d.p75), d.cycleP75, 13),
      change_failure_rate: range(84, (i) => [`NOW-${84 - i}d`, i === 83 ? r.cfr : round(Math.max(0, r.cfr * (1 + wob(i, 5, 13) / 2)), 3), 12]) } };
}

function community(r, d) {
  const quarter = (k) => { const t = new Date(ANCHOR); t.setUTCMonth(t.getUTCMonth() - 3 * k); return `${t.getUTCFullYear()} Q${Math.floor(t.getUTCMonth() / 3) + 1}`; };
  const km = (median, answered, waiting) => ({ median, low: round(median * 0.7, 1), high: round(median * 1.5, 1), at_least: null, answered, waiting, too_few: false, closed_unanswered: 1 });
  const gained = sum(r.stars);
  const traffic = (k) => range(14, (i) => [`NOW-${14 - i}d`, Math.round(k * (1 + wob(i, 5, 7))), Math.round(k * 0.3)]);
  const pub = r.visibility === "public";
  return { schema: 1, generated: r.updated,
    facts: { first_answer_hours: r.answerH, answered_1d_share: r.answered1d, newcomer_answered_share: round(r.answered1d - 0.08, 2), newcomer_return_rate: pub ? 0.24 : 0.38 },
    score: { score: r.score }, has_bench: false,
    funnel: { newcomers: pub ? 46 : 12, judged: pub ? 38 : 8, returned: pub ? 9 : 3, return_rate: pub ? 0.24 : 0.38, regulars: pub ? 11 : 6, maintainers: pub ? 3 : 5 },
    answers: { days: 90, issues: { items: 40, km: km(r.answerH, 34, r.waiting.filter((w) => w[0] === "issue").length), responders: 4 }, discussions: null },
    waiting: r.waiting.map(([kind, n, days]) => ({ kind, n, days, created: `NOW-${days}d` })), waiting_total: r.waiting.length,
    stars: { weeks: r.stars.map((s, i) => [week(i), s]), stars: r.starsTotal, gained_12w: gained, growth_12w: round(gained / (r.starsTotal - gained), 3) },
    traffic: { days: 14, since: "NOW-14d", views: traffic(pub ? 140 : 40), clones: traffic(pub ? 22 : 9), views_total: (pub ? 140 : 40) * 14, visitors_total: (pub ? 42 : 12) * 14, clones_total: (pub ? 22 : 9) * 14,
      referrers: [["github.com", pub ? 610 : 300], ["google.com", pub ? 410 : 90], ["news.ycombinator.com", pub ? 120 : 0]].filter((x) => x[1]) },
    quarters: [3, 2, 1, 0].map((k, i) => ({ quarter: quarter(k), items: 30 + i * 4, median_hours: k ? round(r.answerH * (1.3 - i * 0.1), 1) : r.answerH, within_1d: k ? round(r.answered1d - 0.1 + i * 0.03, 2) : r.answered1d, newcomers: 8 + i * 2 })),
    cohorts: { months: range(6, (i) => ({ month: mon(i), newcomers: 4 + (i * 3) % 5, back_by_90d: i < 3 ? 1 + i % 2 : null, back_90_180d: i < 1 ? 1 : null })) },
    dependency: { days: 180, bus_factor: pub ? 2 : 4, top_share: pub ? 0.46 : 0.22, people: pub ? 9 : 17, merged: d.merged180, peers: { bus_factor: { typical: 3, low: 2, high: 5 }, top_share: { typical: 0.3, low: 0.2, high: 0.45 } } },
    tenure: { days: 90, newcomers: { n: pub ? 21 : 6, median_h: round(r.answerH * 1.6, 1), answered_1d_share: round(r.answered1d - 0.15, 2) }, regulars: { n: 40, median_h: round(r.answerH * 0.8, 1), answered_1d_share: round(r.answered1d + 0.05, 2) } },
    orgs: pub ? { factor: 2, unknown_share: 0.38, people: 9, merged: d.merged180, orgs: [{ org: "acme", prs: Math.round(d.merged180 * 0.48), share: 0.48 }, { org: "contoso", prs: Math.round(d.merged180 * 0.14), share: 0.14 }] } : null,
    changes: [{ metric: "community.first_answer", label: "first answer to outside contributors", now: r.answerH, base: round(r.answerH * 1.1, 1), unit: "h", note: null, changed: false, direction: null, detectable: 1.8 }],
    context: { governance: pub, security_policy: true, code_of_conduct: pub ? "Contributor Covenant 2.1" : null, funding: pub ? ["GITHUB"] : [], discussions: pub, contributing: true,
      response_policy: { said: "within 2 working days", hours: 48 }, maintainers_listed: pub ? 3 : null, code_owners: pub ? 2 : 5,
      stated: pub ? { capacity: "Two part-time maintainers from the mobile team.", norms: "Bugs first; feature requests are reviewed monthly." } : null },
    forum: r.forum ? { km: km(14, 96, 6), topics: 118, days: 90, anyone_answered: 0.86, solved_share: 0.52 } : null, chat: null };
}

function deps(r, d, dec) {
  const rows = r.deps.map(([pr, pkg, from, to, bump, security, age]) => ({ pr, package: pkg, ecosystem: r.eco, from, to, bump, bot: r.bot, security, age_hours: age }));
  rows.sort((a, b) => b.age_hours - a.age_hours);
  return { schema: 1, generated: r.updated, open: rows, security_overdue: rows.filter((x) => x.security && x.age_hours > 48 && !x.decision),
    merged_90d: r.depsMerged, merge_median_hours: r.depsMergeH, bots: [r.bot], last_opened: `NOW-${Math.max(1, Math.round(Math.min(...rows.map((x) => x.age_hours)) / 24))}d`, quiet_days: 0 };
}

function vulns(r, d) {
  return { schema: 1, generated: r.updated, ref: "main", scanner: "OSV-Scanner 2.7.0", offline: false, files: r.lockfiles, skipped: [],
    open: d.vulns.map((v) => ({ id: v.id, aliases: v.aliases, file: v.file, ecosystem: r.eco, package: v.pkg, version: v.version, severity: v.severity, malware: false, fixed: v.fixed,
      first_seen: `NOW-${v.age}d`, ...(r.eco === "Go" ? {} : { imported: v.reach }) })),
    closed: [{ id: "GHSA-r9px-m959-cxf4" }, { id: "GHSA-c2qf-rxjj-qqgw" }].slice(0, r.eco === "Maven" ? 1 : 2) };
}

function supply(r, d) {
  const go = r.eco === "Go";
  return { schema: 1, generated: r.updated, packages: { Go: 84, npm: 912, Maven: 236 }[r.eco], systems: { [r.eco.toUpperCase()]: { Go: 78, npm: 906, Maven: 230 }[r.eco], ACTIONS: 6 },
    policy: { deny: ["AGPL-3.0-only"], min_scorecard: 5 }, outside_lookups: true,
    licences: { denied: r.eco === "npm" ? [{ name: "pdf-render-lite", version: "2.1.0", licence: "AGPL-3.0-only", system: "NPM" }] : [], accepted: [], unknown: { Go: 2, npm: 7, Maven: 3 }[r.eco] },
    drift: r.eco === "npm" ? [{ name: "fast-csv-stream", from: "MIT", from_quarter: "2026 Q2", to: "BUSL-1.1", to_quarter: "2026 Q3" }] : [],
    scorecards: { checked: 41, projects: 48, drops: [{ project: `github.com/${go ? "jackc/pgx" : r.eco === "npm" ? "nicolo-ribaudo/tc39-proposal" : "square/okio"}`, before: 7.1, after: 5.4, since: "NOW-20d", packages: [r.deps[0][1]] }],
      low: [{ project: "github.com/legacy/left-pad-ng", score: 3.2, packages: ["left-pad-ng"] }], below_policy: [] },
    runtimes: go ? [{ runtime: "go", version: "1.22", file: "go.mod", use: "runs", eol: "2025-02-11", latest: "1.22.12", status: "end of life" }, { runtime: "go", version: "1.23", file: ".github/workflows/ci.yml", use: "tests", eol: null, latest: "1.23.4", status: "supported" }]
      : r.eco === "npm" ? [{ runtime: "nodejs", version: "20", file: ".nvmrc", use: "runs", eol: "2026-04-30", latest: "20.18.1", status: "behind the newest patch" }]
        : [{ runtime: "java", version: "17", file: "build.gradle.kts", use: "runs", eol: "2029-09-30", latest: "17.0.13", status: "supported" }],
    reachability: go ? { scanner: "govulncheck 1.1.3", findings: d.vulns.map((v) => ({ id: v.aliases.find((a) => a.startsWith("GO-")), aliases: [v.id, ...v.aliases], reach: v.reach, module: v.pkg, version: v.version, fixed: v.fixed,
      path: v.reach === "called" ? ["internal/webhook.Parse", "golang.org/x/net/html.Parse"] : [] })), counts: { called: d.vulns.filter((v) => v.reach === "called").length, imported: d.vulns.filter((v) => v.reach === "imported").length, required: d.vulns.filter((v) => v.reach === "required").length } } : null };
}

function insights(r, d, dec) {
  const findings = d.findings.map((f) => ({ ...f, key: f.kind, snooze: undefined, decision: f.snooze ? { verb: "snooze", by: dec.snooze.by, until: dec.snooze.until, reason: dec.snooze.reason, at: dec.snooze.at, kind: "finding", id: f.kind } : null }));
  const open = findings.filter((f) => !f.decision);
  const red = findings.find((f) => f.kind === "red_ci") || { hours: 6, n: 4 };
  const tests = r.flaky.filter((f) => f.kind === "test" && f.state === "flaky");
  return { schema: 1, generated: r.updated, findings,
    opportunity: { hours: round(sum(open.map((f) => f.hours)), 1), findings: open.length, inside_another: 0 },
    track_record: { since: "2026-07-01", top_findings: 5, shrank_by_half: 3, cleared: 2 },
    red_ci: { definition: "Time a ready pull request spent with a failing check on its newest commit, until a new commit, a passing re-run or the merge.", prs: d.merged90, without_checks: 2,
      red_prs: red.n + 8, red_hours_total: round(red.hours * 2.1, 1), rerun_hours_total: red.hours, rerun_waits: red.n,
      open_red: d.queue.filter((q) => q.step === "checks").map((q) => ({ pr: q.n, since: `NOW-${q.days}d`, hours: q.days * 24 })) },
    chains: tests.map((t, i) => ({ test: t.id, hours: t.hours, prs: Math.min(6, t.flakes), pr_list: range(Math.min(6, t.flakes), (k) => 1800 + k * 7), state: t.state, flake_events: t.flakes, runs: t.runs,
      owners: ["@acme/core"], owners_from: "CODEOWNERS line 4", decision: t.id === d.muted.id ? dec.mute : null })) };
}

// The org's portal: the three demo repos plus a few that don't run the suite yet.
function portal(all) {
  const rule = [["codeowners", "bronze"], ["reviews-required", "bronze"], ["readme-and-license", "bronze"], ["owners-valid", "silver"], ["ci-first-try", "silver"], ["first-review", "silver"],
    ["contributing", "silver"], ["first-review-fast", "gold"], ["security-policy", "gold"], ["token-permissions", "gold"]];
  const levelOf = (fails) => { for (const lv of ["bronze", "silver", "gold"]) if (fails.some((i) => rule[i][1] === lv)) return lv === "bronze" ? null : lv === "silver" ? "bronze" : "silver"; return "gold"; };
  const repo = (name, lang, fails, extra = {}) => ({ name: `acme/${name}`, private: extra.private ?? true, archived: false, fork: false, language: lang, runtime: extra.runtime || [],
    owners: { status: extra.owners || "valid" }, score: { level: levelOf(fails), rows: rule.map((_, i) => [i, fails.includes(i) ? 1 : i === 9 && extra.preview ? 3 : 0, fails.includes(i) ? 1 : 0]) },
    modules: extra.modules || null, since: { level: "NOW-40d" }, descriptor: extra.entities ? { present: true, entities: extra.entities, problems: extra.problems || [] } : { present: false }, doc_pages: extra.docs || [] });
  const mods = (r) => ({ ci_first_try: `${Math.round(r.firstTry[W - 1] * 100)}%`, ci_first_try_share: r.firstTry[W - 1] });
  const [pay, web, mob] = all;
  const repos = [
    repo("payments-api", "Go", [8], { modules: mods(pay.r), runtime: ["go 1.22"], docs: ["architecture.md", "runbook.md", "refunds.md"],
      entities: [{ kind: "Component", name: "payments-api", title: "Payments API", description: "Card payments, refunds and settlement", system: "payments", type: "service", lifecycle: "production", owner: "group:payments-core", owner_check: ["pass"], depends_on: ["resource:default/ledger-db"] }] }),
    repo("web-app", "TypeScript", [], { modules: mods(web.r), runtime: ["node 20"], docs: ["getting-started.md", "deploys.md"],
      entities: [{ kind: "Component", name: "web-app", title: "Storefront", description: "The customer-facing web shop", system: "shop", type: "website", lifecycle: "production", owner: "group:storefront", owner_check: ["pass"], depends_on: ["component:default/payments-api"] }] }),
    repo("mobile", "Kotlin", [5, 7], { private: false, modules: mods(mob.r), owners: "weak", docs: ["release.md"],
      entities: [{ kind: "Component", name: "mobile", title: "Android app", system: "shop", type: "mobile-app", lifecycle: "production", owner: "group:android", owner_check: ["fail"] }], problems: ["spec.owner group:android is not in CODEOWNERS"] }),
    repo("ledger", "Go", [6, 8], { runtime: ["go 1.23"], docs: ["schema.md"] }),
    repo("infra-terraform", "HCL", [2, 3], { owners: "weak" }),
    repo("design-system", "TypeScript", [], { private: false, preview: true, docs: ["tokens.md", "components"] }),
    repo("data-pipelines", "Python", [0, 3], { owners: "none", runtime: ["python 3.9"] }),
    repo("old-admin", "PHP", [0, 1, 2], { owners: "none" }),
  ];
  const f = all.map((x) => x.facts);
  const med = (k) => { const v = f.map((x) => x[k]).filter((x) => x !== null && x !== undefined).sort((a, b) => a - b); return v.length ? v[Math.floor(v.length / 2)] : null; };
  const tot = (k) => sum(f.map((x) => x[k] || 0));
  const lead = (k, desc = true) => all.map((x) => ({ repo: x.r.repo, value: x.facts[k] })).filter((x) => x.value).sort((a, b) => (desc ? b.value - a.value : a.value - b.value));
  // Packed as the real file is: each rule named once.
  return { schema: 1, org: "acme", mode: "private", built_at: "NOW-6h", complete: true, repos, packed: true, rule_index: rule,
    result_codes: ["pass", "fail", "exempt", "preview", "not available"], evidence_index: ["passes", "missing or failing"],
    campaigns: [{ title: "Every repo has CODEOWNERS by December", passing: 6, targets: 8, until: "NOW+38d", burn_down: range(10, (i) => [`NOW-${10 - i}d`, Math.max(2, 5 - Math.floor(i / 3))]), failing: ["acme/data-pipelines", "acme/old-admin"] }],
    golden: [{ id: "go-service", title: "New Go service", kind: "repo", private: true, description: "A Go service with CI, CODEOWNERS, a catalog file and StackVitals set up." },
      { id: "security-baseline", title: "Security baseline files", kind: "pr", description: "Adds SECURITY.md, Dependabot settings and pinned workflow permissions." }],
    golden_ready: true,
    org_view: { running: 3, repos: repos.length, medians: { ci_first_try: med("ci_first_try"), pickup_p75_h: med("pickup_p75_h"), review_p75_h: med("review_p75_h"), change_failure_rate: med("change_failure_rate") },
      totals: { ci_flaky: tot("ci_flaky"), ci_broken: tot("ci_broken"), open_prs: tot("open_prs"), stale_prs: tot("stale_prs"), deployments: tot("deployments"), vulns_open: tot("vulns_open"), vulns_serious: tot("vulns_serious") },
      counts: { ci_first_try: 3 }, leaders: { ci_flaky: lead("ci_flaky"), stale_prs: lead("stale_prs"), pickup_p75_h: lead("pickup_p75_h"), newcomers_waiting: lead("newcomers_waiting"), vulns_serious: lead("vulns_serious") } } };
}

// Small summary tables for Explore and the Delivery rows page (jsonl; dates fixed at build time).
function summary(r, d) {
  const iso = (days) => new Date(ANCHOR - days * 864e5).toISOString().replace(/\.\d+Z$/, "Z");
  const prs = range(14, (i) => { const n = d.queue[0].n - 2 - i * 3, days = 2 + i * 6, pick = Math.round(d.p50 * 3600 * (0.4 + ((i * 7) % 10) / 6));
    return { number: n, title: ["Refactor config loading", "Add metrics for retries", "Fix flaky timeout", "Update docs", "Speed up cold start", "Tidy error messages", "Split large handler"][i % 7], author_kind: "person",
      role: i % 6 === 5 ? "outsider" : "insider", status: "MERGED", created_at: iso(days + 2), merged_at: iso(days), pickup_s: pick, additions: 40 + (i * 37) % 300, deletions: 10 + (i * 13) % 90 }; });
  const open = d.queue.map((q) => ({ number: q.n, title: q.title, author_kind: q.author.includes("bot") || q.author === "dependabot" ? "bot" : "person", role: q.outsider ? "outsider" : "insider", status: "OPEN",
    created_at: iso(q.days), merged_at: null, pickup_s: null, additions: 60 + q.n % 400, deletions: 5 + q.n % 70 }));
  const jobs = r.slow.map(([name, min]) => { const f = r.flaky.find((x) => x.id === name); const [w, job] = name.includes(" / ") ? name.split(" / ") : ["ci", name];
    return { workflow: `.github/workflows/${w}.yml`, job, state: f ? f.state : "ok", flake_events: f ? f.flakes : 0, failures: f ? f.flakes : 0, runs: f ? f.runs : 120, flake_rate: f ? round(f.flakes / f.runs) : 0, prs_affected: f ? Math.min(6, f.flakes) : 0, retry_minutes: f ? Math.round(f.hours * 60) : 0 }; });
  const tests = r.flaky.filter((f) => f.kind === "test").map((f) => ({ test_id: f.id, state: f.state, failures: f.state === "broken" ? f.runs : f.flakes, flake_events: f.flakes, runs: f.runs, message: f.msg || null }));
  const dl = prs.map((p) => ({ id: p.number, pull_request_key: p.number, title: p.title, author_name: "someone", merged_date: p.merged_at }));
  const metrics = prs.map((p, i) => ({ id: p.number, pr_pickup_time: Math.round(p.pickup_s / 60), pr_review_time: Math.round(r.review * 60 * (0.3 + (i % 5) / 5)),
    pr_coding_time: Math.round(r.coding * 60 * (0.3 + (i % 4) / 4)), pr_deploy_time: Math.round(r.deployH * 60 * (0.4 + (i % 3) / 3)), pr_cycle_time: Math.round((p.pickup_s / 60) + r.review * 40 + r.coding * 40), pr_merged_date: p.merged_at }));
  const tables = { prs: [...prs, ...open], ci_jobs: jobs, tests, devlake_pull_requests: dl, devlake_project_pr_metrics: metrics };
  const out = { "summary/manifest.json": JSON.stringify({ generated: r.updated, files: Object.fromEntries(Object.entries(tables).map(([k, rows]) => [`${k}.jsonl`, { rows: rows.length, generated: r.updated }])) }) };
  for (const [k, rows] of Object.entries(tables)) out[`summary/${k}.jsonl`] = rows.map((x) => JSON.stringify(x)).join("\n") + "\n";
  return out;
}

function build(r) {
  const d = derive(r);
  const dec = decisionsFor(r, d);
  const serious = d.vulns.filter((v) => SERIOUS.has(v.severity)).length;
  const facts = { ci_first_try: r.firstTry[W - 1], ci_flaky: d.flaky, ci_broken: d.broken, open_prs: r.open, stale_prs: d.stale, pickup_p75_h: d.p75, review_p75_h: r.review, cycle_p75_h: d.cycleP75,
    deployments: d.deploys90, change_failure_rate: r.cfr, newcomers_waiting: r.waiting.length, findings: d.findings.filter((f) => !f.snooze).length, first_review_median_s: Math.round(d.p50 * 3600),
    community_score: r.score, vulns_open: d.vulns.length, vulns_serious: serious, decisions: dec.snooze ? 2 : 1 };
  return { r, d, dec, facts };
}

function files(x, portalJson) {
  const { r, d, dec, facts } = x;
  const mods = [["ci", "data.json", "ci.html"], ["flow", "flow.json", "flow.html"], ["delivery", "delivery.json", "delivery.html"], ["insights", "insights.json", "insights.html"], ["community", "community.json", "community.html"],
    ["portal", "portal.json"], ["alerts", "alerts.json"], ["deps", "deps.json"], ["supply", "supply.json"], ["vulns", "vulns.json"]];
  const state = { [`${dec.mute.kind}:${dec.mute.id}`]: dec.mute, ...(dec.snooze ? { [`finding:${dec.snooze.id}`]: dec.snooze } : {}) };
  return {
    "app.json": { schema: 1, repo: r.repo, default_branch: "main", visibility: r.visibility,
      modules: Object.fromEntries(mods.map(([k, file]) => [k, { updated: k === "portal" ? "NOW-6h" : k === "supply" || k === "vulns" ? "NOW-1d" : r.updated, file }])),
      pages: [], facts,
      links: { repo: `https://github.com/${r.repo}`, workflow: "stackvitals.yml", actions: `https://github.com/${r.repo}/actions/workflows/stackvitals.yml`,
        settings_file: `https://github.com/${r.repo}/blob/main/.github/stackvitals.toml`, edit_settings: `https://github.com/${r.repo}/edit/main/.github/stackvitals.toml`, new_issue: `https://github.com/${r.repo}/issues/new` } },
    "data.json": ci(r, d, dec),
    "flow.json": flow(r, d),
    "delivery.json": delivery(r, d),
    "community.json": community(r, d),
    "deps.json": deps(r, d, dec),
    "vulns.json": vulns(r, d),
    "supply.json": supply(r, d),
    "insights.json": insights(r, d, dec),
    "alerts.json": alerts(r, d),
    "portal.json": portalJson,
    "decisions.json": { state, log: Object.values(state).map((s) => ({ verb: s.verb, kind: s.kind, id: s.id, by: s.by, at: s.at, until: s.until, reason: s.reason, source: s.verb === "mute" ? "comment" : "app" })) },
    "settings.json": DEMO_SETTINGS,
    "connectors.json": { connectors: DEMO_CONNECTORS[r.slug] || {} },
    "health.json": health(r),
  };
}

// What health.json says (core/health.py shape): each step's last run, the connectors, how far back each history goes.
function health(r) {
  const ok = (at, read, complete = true) => ({ kind: "module", last_try: at, last_ok: at, failing_since: null, error: null, complete, read });
  const sources = { "CI Health": ok(r.updated, { runs: 48, requests: 61 }), "Team Flow": ok(r.updated, { prs: 37, points: 12 }),
    Delivery: ok(r.updated, {}), Insights: ok(r.updated, {}) };
  if (r.slug === "web-app") {
    sources.Dependencies = { kind: "module", last_try: "NOW-58m", last_ok: "NOW-1d", failing_since: "NOW-20h", complete: null, read: {},
      error: "OSV could not be reached (ConnectTimeout); the next run tries again." };
    sources["Team Flow"] = ok(r.updated, { prs: 100, points: 40 }, false);
  }
  for (const c of Object.values(DEMO_CONNECTORS[r.slug] || {})) {
    if (c.as_of) sources[c.name] = { kind: "connector", last_try: c.as_of, last_ok: c.error ? null : c.as_of, failing_since: c.error ? c.as_of : null,
      error: c.error, complete: c.complete, read: c.rows };
  }
  const stream = (oldest, files, keeps) => ({ oldest, newest: "NOW-0d", files, bytes: files * 41000, keeps_days: keeps });
  const history = { "ci/days": stream("NOW-179d", 172, 180), "flow/closed": stream(r.slug === "web-app" ? "NOW-38d" : "NOW-399d", r.slug === "web-app" ? 38 : 351, 400) };
  return { as_of: r.updated, sources: Object.fromEntries(Object.entries(sources).sort()), history,
    dropped: r.slug === "payments-api" ? { at: "NOW-2d", retention: { "ci/days": 1 }, size_cap: {} } : null };
}

// Same in every demo repo, so written once (web/src/data/files.ts reads them one folder up).
const SHARED = ["settings.json", "portal.json"];

export function demoFiles() {
  const all = REPOS.map(build);
  const portalJson = portal(all);
  const out = {};
  for (const x of all) {
    const fs = files(x, portalJson);
    for (const extend of EXTRAS) extend(x.r, fs, x.d);
    for (const [name, body] of Object.entries(fs)) out[SHARED.includes(name) ? name : `${x.r.slug}/${name}`] = JSON.stringify(body);
    for (const [name, text] of Object.entries(summary(x.r, x.d))) out[`${x.r.slug}/${name}`] = text;
  }
  return out;
}
