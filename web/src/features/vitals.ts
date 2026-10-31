// What Overview and CI Health read from the files: trend metrics, the per-area conditions and the decision queue.
import { inForce } from "../data/files";
import { ago, count, day, dateLabel, hours, pct, secs } from "../data/format";
import type { AlertsJson, AppJson, CiJson, CiItem, CommunityJson, DecisionsJson, DeliveryJson, DepsJson, FlowJson, InsightsJson, PortalJson, VulnsJson } from "../data/types";
import { target } from "../data/write";
import { points, type Metric } from "../charts/metric";
import type { IconName } from "../ui/icons";

export interface VitalFiles {
  ci?: CiJson | null; flow?: FlowJson | null; delivery?: DeliveryJson | null; community?: CommunityJson | null; deps?: DepsJson | null;
  portal?: PortalJson | null; insights?: InsightsJson | null; decisions?: DecisionsJson | null; alerts?: AlertsJson | null; vulns?: VulnsJson | null;
}

export const jobId = (j: CiItem) => `${String(j.workflow || "?").split("/").pop()} / ${j.job}`;

// CI's weekly trends as metrics.
export function ciMetrics(ci: CiJson | null | undefined): Metric[] {
  const w = ci?.weekly || [];
  const pick = (f: (x: (typeof w)[number]) => number | null | undefined) => w.filter((x) => f(x) !== null && f(x) !== undefined)
    .map((x) => ({ label: dateLabel(x.week), value: f(x) as number, n: x.job_runs }));
  return [
    { id: "first_try", name: "First-try green", sub: "Pushes green without a re-run", kind: "share", better: "up", period: "week", points: pick((x) => x.first_try_share),
      meaning: (v) => `${Math.round(v * 100)} of every 100 pushes passed every check without a re-run.`,
      info: { title: "First-try green", body: "The share of pushes whose checks all passed without anyone re-running a job. Re-runs hide flaky tests; this number does not.",
        facts: ci?.pushes ? [["Pushes", String(ci.pushes.pushes)], ["Likely range", ci.pushes.first_try_range ? `${pct(ci.pushes.first_try_range[0])} to ${pct(ci.pushes.first_try_range[1])}` : "–"]] : [], doc: "methods.md" } },
    { id: "flake_share", name: "Flaky job runs", sub: "Failed, then passed on the same code", kind: "percent", better: "down", period: "week", points: pick((x) => x.flake_share),
      meaning: (v, p) => `${v.toFixed(1)}% of ${p.n ?? "the"} job runs that week failed and then passed with no code change.`,
      info: { title: "Flaky job runs", body: "A flake is a job or test that failed and then passed on the same commit. This line is the share of job runs where that happened.", doc: "methods.md" } },
    { id: "push_median", name: "Time to green", sub: "Push until all checks finish", kind: "secs", better: "down", period: "week", points: pick((x) => x.push_median_s),
      meaning: (v) => `Half of all pushes had every check finished within ${secs(v)}.`,
      info: { title: "Time to green", body: "The median time from a push until every check on it finished, by week.", doc: "methods.md" } },
    { id: "job_runs", name: "Job runs", sub: "CI jobs run each week", kind: "count", better: null, period: "week", points: pick((x) => x.job_runs),
      meaning: (v) => `${Math.round(v)} job runs that week.`,
      info: { title: "Job runs", body: "How many CI jobs ran each week, re-runs included. Neither up nor down is better; it shows how busy CI was." } },
  ];
}

export function overviewMetrics(f: VitalFiles): Metric[] {
  const ci = ciMetrics(f.ci);
  const out: Metric[] = [ci[0]!, ci[2]!];
  const monthly = f.flow?.monthly || [];
  out.push({ id: "opened", name: "Pull requests opened", sub: "By month", kind: "count", better: null, period: "month",
    points: monthly.map((m) => ({ label: dateLabel(m.month), value: m.opened ?? 0 })), meaning: (v) => `${Math.round(v)} pull requests opened that month.` });
  out.push({ id: "merged", name: "Pull requests merged", sub: "By month", kind: "count", better: "up", period: "month",
    points: monthly.filter((m) => m.merged !== undefined).map((m) => ({ label: dateLabel(m.month), value: m.merged! })), meaning: (v) => `${Math.round(v)} pull requests merged that month.` });
  out.push({ id: "deploys", name: "Deployments", sub: "To production, by month", kind: "count", better: "up", period: "month",
    points: (f.delivery?.dora?.monthly || []).map((m) => ({ label: dateLabel(m.month), value: m.deployments })),
    meaning: (v) => `${Math.round(v)} deployments that month.`,
    info: { title: "Deployments", body: "Deployments and releases StackVitals found, by month. DORA's deploy frequency is read from these.", doc: "dora-guide.md" } });
  const series = f.alerts?.series || {};
  if (series.pickup_p75_hours) out.push({ id: "pickup", name: "Review pickup", sub: "3 in 4 reviews start within", kind: "hours", better: "down", period: "day",
    points: points(series.pickup_p75_hours), meaning: (v) => `3 in 4 review requests were picked up within ${hours(v)}.`,
    info: { title: "Review pickup", body: "Hours from a pull request asking for review until someone starts (75th percentile), day by day.", doc: "methods.md" } });
  if (series.review_p75_hours) out.push({ id: "review", name: "Time in review", sub: "3 in 4 reviews finish within", kind: "hours", better: "down", period: "day",
    points: points(series.review_p75_hours), meaning: (v) => `3 in 4 pull requests were approved within ${hours(v)} of their first review.` });
  out.push({ id: "stars", name: "Stars", sub: "New stars by week", kind: "count", better: "up", period: "week",
    points: (f.community?.stars?.weeks || []).map(([w, n]) => ({ label: dateLabel(w), value: n })), meaning: (v) => `${Math.round(v)} new stars that week.` });
  return out.filter((m) => m.points.length > 0);
}

export interface QueueItem { kind: "ci" | "prs" | "deps" | "community"; tone: "bad" | "watch"; title: string; href: string; external?: boolean; what: string; meta?: string;
  decide?: { kind: string; id: string; verbs: string[] }; cmd?: string }

// Everything waiting for a person: new flakes nobody decided on, stuck reviews, security updates, newcomers.
export function queue(f: VitalFiles, app: AppJson): QueueItem[] {
  const out: QueueItem[] = [];
  const decided = f.decisions?.state || {};
  for (const t of f.ci?.tests || []) {
    if ((t.state === "flaky" || t.state === "broken") && !inForce(decided[`test:${t.id}`])) {
      out.push({ kind: "ci", tone: "bad", title: t.id!, href: `#/ci/test/${encodeURIComponent(t.id!)}`, what: `Test ${t.state === "flaky" ? "is flaky" : "keeps failing"}`,
        meta: `${t.flake_events || t.failures} of ${t.runs} runs${t.since ? `, since ${day(t.since)}` : ""}`,
        decide: { kind: "test", id: t.id!, verbs: t.state === "flaky" ? ["quarantine", "mute", "acknowledge"] : ["mute", "quarantine", "acknowledge"] },
        cmd: `/stackvitals ${t.state === "flaky" ? "quarantine" : "mute"} ${target("test", t.id!)} because ` });
    }
  }
  for (const j of f.ci?.jobs || []) {
    const id = jobId(j);
    if (j.state === "flaky" && !inForce(decided[`job:${id}`])) {
      out.push({ kind: "ci", tone: "bad", title: id, href: `#/ci/job/${encodeURIComponent(id)}`, what: "Job is flaky",
        meta: `${j.flake_events} of ${j.runs} runs, ${Math.round(j.retry_minutes || 0)} min lost to re-runs`,
        decide: { kind: "job", id, verbs: ["mute", "acknowledge"] }, cmd: `/stackvitals mute ${target("job", id)} for 14d because ` });
    }
  }
  for (const s of f.delivery?.stuck?.hanging_review || []) {
    out.push({ kind: "prs", tone: "watch", title: `#${s.pr} waits for its review`, href: `https://github.com/${app.repo}/pull/${s.pr}`, external: true,
      what: "Review not started", meta: `asked ${ago(s.since)}` });
  }
  for (const u of f.deps?.security_overdue || []) {
    out.push({ kind: "deps", tone: "bad", title: `${u.package} ${u.from || ""} to ${u.to || ""}`, href: `https://github.com/${app.repo}/pull/${u.pr}`, external: true,
      what: "Security update waiting", meta: `#${u.pr}, open ${hours(u.age_hours)}`,
      decide: { kind: "package", id: u.package, verbs: ["accept"] }, cmd: `/stackvitals accept ${target("package", u.package)} for 30d because ` });
  }
  for (const w of f.community?.waiting || []) {
    out.push({ kind: "community", tone: "watch", title: `${w.kind === "issue" ? "Issue" : "Pull request"} #${w.n}`,
      href: `https://github.com/${app.repo}/${w.kind === "issue" ? "issues" : "pull"}/${w.n}`, external: true,
      what: "A newcomer waits for a first answer", meta: count(w.days, "day") });
  }
  return out;
}

export type AreaTone = "good" | "ok" | "bad" | "off";
export interface Area { id: string; name: string; tone: AreaTone; word: string; value: string; note: string; trace: number[]; alarm?: string | null }

const WORD: Record<AreaTone, string> = { good: "Clear", ok: "Fair", bad: "Unsettled", off: "Not set up" };
export const AREA_ICON: Record<AreaTone, IconName> = { good: "sun", ok: "fair", bad: "rain", off: "off" };

// One weather-style reading per area, from the same facts the old monitor wall showed.
export function areas(f: VitalFiles, todo: QueueItem[]): Area[] {
  const waiting = (k: QueueItem["kind"]) => todo.filter((t) => t.kind === k).length;
  const out: Area[] = [];
  const add = (a: Omit<Area, "word">) => out.push({ ...a, word: WORD[a.tone] });
  const ci = f.ci;
  if (ci) {
    const items = [...(ci.tests || []), ...(ci.jobs || [])];
    const flaky = items.filter((i) => i.state === "flaky").length, broken = items.filter((i) => i.state === "broken").length;
    const share = ci.pushes?.first_try_share;
    const n = waiting("ci");
    add({ id: "ci", name: "CI Health", tone: broken || n ? "bad" : (share ?? 0) >= 0.88 && !flaky ? "good" : "ok",
      value: share === null || share === undefined ? "–" : pct(share), trace: (ci.weekly || []).map((w) => w.first_try_share ?? 0),
      note: `green on the first try over ${ci.window_days ?? 30} days; ${flaky} flaky, ${broken} failing every run${ci.pushes ? `; ${count(ci.pushes.pushes, "push", "pushes")}` : "; too few pushes yet"}`,
      alarm: n ? `${n} undecided` : null });
  } else add({ id: "ci", name: "CI Health", tone: "off", value: "–", note: "Add ci to the workflow's modules", trace: [] });
  if (f.flow) {
    const n = waiting("prs");
    add({ id: "prs", name: "Pull Requests", tone: n ? "bad" : f.flow.stale ? "ok" : "good", value: String(f.flow.open ?? "–"),
      trace: (f.flow.monthly || []).map((m) => m.opened ?? 0),
      note: `open now; ${(f.flow.queue || []).length} waiting on someone, ${f.flow.stale ? `${f.flow.stale} stale` : "none stale"}`,
      alarm: n ? `${n} ${n === 1 ? "review" : "reviews"} not started` : null });
  } else add({ id: "prs", name: "Pull Requests", tone: "off", value: "–", note: "Add flow to the workflow's modules", trace: [] });
  if (f.delivery) {
    const d = f.delivery, p = d.phases?.pickup, cfr = d.dora?.change_failure_rate;
    const series = (f.alerts?.series?.pickup_p75_hours || []).map((x) => x[1] ?? 0);
    add({ id: "delivery", name: "Delivery", tone: cfr !== null && cfr !== undefined && cfr > 0.15 ? "bad" : (d.dora?.deployments ?? 0) > 0 ? "good" : "ok",
      value: String(d.dora?.deployments ?? 0), trace: series.length ? series : (d.dora?.monthly || []).map((m) => m.deployments),
      note: `deployments in ${d.window_days ?? 90} days; pickup ${p?.p75_h !== null && p?.p75_h !== undefined ? `3 in 4 within ${hours(p.p75_h)}` : "not measured yet"}${p?.n !== undefined ? ` (n = ${p.n})` : ""}` +
        `${d.ai?.assisted_prs?.share !== null && d.ai?.assisted_prs?.share !== undefined ? `; ${pct(d.ai.assisted_prs.share)} with AI help` : ""}` });
  } else add({ id: "delivery", name: "Delivery", tone: "off", value: "–", note: "Add flow to the workflow's modules", trace: [] });
  if (f.community) {
    const c = f.community, n = waiting("community");
    add({ id: "community", name: "Community", tone: n > 3 ? "bad" : n ? "ok" : "good", value: String(c.waiting_total ?? 0),
      trace: (c.stars?.weeks || []).map((w) => w[1]),
      note: `newcomers waiting; ${c.stars?.stars ?? 0} stars${c.score ? `, score ${c.score.score}/100` : ""}`, alarm: n ? `${n} waiting` : null });
  } else add({ id: "community", name: "Community", tone: "off", value: "–", note: "Add community to the workflow's modules", trace: [] });
  if (f.deps || f.vulns) {
    // Set up when either the update-bot history or the vulnerability scan wrote its file.
    const n = waiting("deps"), d = f.deps, v = f.vulns?.open || [];
    const serious = v.filter((x) => x.malware || ["critical", "high"].includes(x.severity || "")).length;
    const vNote = f.vulns ? `${v.length} known ${v.length === 1 ? "vulnerability" : "vulnerabilities"}${serious ? `, ${serious} serious` : ""}` : "";
    if (d) add({ id: "deps", name: "Dependencies", tone: n || serious ? "bad" : (d.open || []).length ? "ok" : "good", value: String((d.open || []).length), trace: [],
      note: `update PRs open${d.merge_median_hours !== null && d.merge_median_hours !== undefined ? `; merge in ${hours(d.merge_median_hours)}` : ""}${d.security_overdue?.length ? "" : "; no security update overdue"}${vNote ? `; ${vNote}` : ""}`,
      alarm: n ? `${n} security overdue` : null });
    else add({ id: "deps", name: "Dependencies", tone: serious ? "bad" : v.length ? "ok" : "good", value: String(v.length), trace: [],
      note: `known vulnerabilities${serious ? `; ${serious} critical or high` : ""}; no update bot history yet`, alarm: serious ? `${serious} serious` : null });
  } else add({ id: "deps", name: "Dependencies", tone: "off", value: "–", note: "Add deps to the workflow's modules", trace: [] });
  if (f.portal) {
    const repos = f.portal.repos || [];
    add({ id: "portal", name: "Portal", tone: "good", value: String(repos.length), trace: [],
      note: `repos in the catalog; ${repos.filter((r) => r.owners?.status === "valid").length} with valid owners, ${repos.filter((r) => !r.score?.level).length} below bronze` });
  }
  return out;
}

export function overall(list: Area[]): string {
  const on = list.filter((a) => a.tone !== "off");
  if (!on.length) return "No readings yet";
  const bad = on.filter((a) => a.tone === "bad").length, ok = on.filter((a) => a.tone === "ok").length;
  return bad === 0 && ok <= 1 ? "Healthy" : bad <= 1 ? "Mostly healthy" : "Unsettled";
}

// The area a finding belongs to, for its "Open" button.
export const FINDING_AREA: Record<string, string> = { red_ci: "ci", fix_job: "ci", fix_test: "ci", review_wait: "prs", stale_review: "prs",
  incident: "delivery", outsider_wait: "community", bump_red: "deps" };
