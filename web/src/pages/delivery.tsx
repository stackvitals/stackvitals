// Delivery: DORA as DevLake counts it (with tiers and ranges), the 90-day trends against the alert limits, deployments and
// what counts as one, the cycle-time phases with the pull requests behind each, and in-depth tabs (incidents, teams,
// AI-assisted work, issues and sprints, the merge queue).
import "./delivery.css";
import { useEffect, useState } from "preact/hooks";
import type { PageProps } from "../app/routes";
import { navigate, withQuery, type Route } from "../app/router";
import { MetricHero, Watchlist, metricItem, trendTones, useRange } from "../charts/MetricHero";
import type { Metric } from "../charts/metric";
import { useFiles } from "../data/files";
import { EvidenceLink } from "../features/Evidence";
import { count, dateLabel, day, hours, pct, short, type Kind } from "../data/format";
import type { AppJson, CiChange, DeliveryJson, Num } from "../data/types";
import { Button } from "../ui/Button";
import { DOCS, EmptyState, InfoButton, PageSkeleton, Pill, Skeleton, StatePill } from "../ui/bits";
import { SegmentedControl } from "../ui/controls";
import { Icon } from "../ui/icons";
import { Card, Columns, Page, Section, Stat, Stats } from "../ui/Page";
import { Table } from "../ui/Table";
import { Facts, Framed, Mark, Panel, SubHead } from "./delivery/blocks";
import { OtherSources } from "./delivery/sources";

type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
type D = Omit<DeliveryJson, "dora" | "phases" | "ai"> & R;
type Alerts = { series?: Record<string, [string, Num, number?][]>; limits?: Record<string, Num>; min_n?: number };

const SOURCES: R = { "deployments api": "GitHub's Deployments API", releases: "GitHub releases", "deploy workflows": "deploy workflow runs", "release workflows": "release workflow runs", merges: "every merged pull request (your setting)" };
const NAMES: R = { coding: "Coding", pickup: "Pickup", review: "Review", approve: "Approve", merge: "Merge", deploy: "Deploy", cycle: "Cycle time", cycle_to_merge: "Cycle time to merge" };
const HELP: R = { coding: "first commit to opened", pickup: "ready to the first comment or review by someone else", review: "that first answer to merge",
  approve: "first answer to first approval", merge: "approval to merge", deploy: "merge to the deployment that shipped it", cycle: "coding, pickup, review and deploy", cycle_to_merge: "coding, pickup and review" };
const METRIC: R = { pickup: "pr_pickup_time", review: "pr_review_time", coding: "pr_coding_time", deploy: "pr_deploy_time", cycle: "pr_cycle_time" };
const ORDER = ["elite", "high", "medium", "low"];
const gh = (app: AppJson, p: string) => `https://github.com/${app.repo}${p}`;
const ext = { target: "_blank", rel: "noopener noreferrer" };
const SET = <a href="#/settings?module=delivery">Settings</a>;

// LinearB's PR habits (size buckets, merge frequency, review depth), PRs merged without a real review, and DevLake's PR cycle panel.
const BUCKETS: [string, string][] = [["under_100", "under 100 lines"], ["100_155", "100 to 155"], ["156_228", "156 to 228"], ["over_228", "over 228"]];
function Habits({ d, app }: { d: D; app: AppJson }) {
  const sz = d.sizes as R | undefined, fl = d.merged_flags as R | undefined, cyc = (d.devlake_pr_cycle || []) as R[];
  if (!sz?.n && d.merge_frequency == null && !cyc.length) return null;
  const prs = (xs: R[]) => xs.slice(0, 6).map((x, i) => <>{i ? ", " : ""}<a href={gh(app, `/pull/${x.pr}`)} {...ext}>#{x.pr}</a></>);
  return <>
    <SubHead title="Habits" note="LinearB's measures over the same pull requests" />
    <Stats>
      <Stat label="Size, median" value={sz?.p50 != null ? `${sz.p50} lines` : "–"} note={sz?.n ? BUCKETS.map(([k, l]) => `${l}: ${sz[k] ?? 0}`).join("; ") : null} />
      <Stat label="Merge frequency" value={d.merge_frequency != null ? `${d.merge_frequency} a week` : "–"} note="merged PRs per author per week" />
      <Stat label="Review depth" value={d.review_depth ?? "–"} note="comments and reviews from others per pull request" />
      <Stat label="Merged without a review" value={fl?.without_review?.length ?? 0} note={fl?.without_review?.length ? prs(fl.without_review) : "none"} />
      <Stat label="Lightning reviews" value={fl?.lightning?.length ?? 0} note={fl?.lightning?.length ? <>reviewed in under 20 minutes: {prs(fl.lightning)}</> : "none"} />
    </Stats>
    {cyc.length ? <Framed title="DevLake's PR cycle time panel" note="mean, merged pull requests, by month"><Table name="devlake-pr-cycle" search={false} caption="DevLake's PR cycle time panel" rows={cyc} columns={[
      { key: "month", label: "Month", primary: true, render: (x: R) => dateLabel(x.month) }, { key: "avg_hours", label: "Mean cycle time", num: true, render: (x: R) => hours(x.avg_hours) },
      { key: "n", label: "PRs", num: true }]} /></Framed> : null}
  </>;
}

// A dimension line naming the window the numbers below cover.
function Dim({ children }: { children: preact.ComponentChildren }) {
  return <p class="sv-dimline dl-dim" aria-hidden="true"><span>{children}</span></p>;
}

// The cycle-time phases at their medians, laid end to end like a schematic.
const STRIP = ["coding", "pickup", "review", "deploy"];
function PhaseStrip({ phases }: { phases: R[] }) {
  const ps = STRIP.map((k) => phases.find((p) => p.k === k)).filter((p): p is R => !!p && p.enough && p.p50_h != null);
  if (ps.length < 2) return null;
  const total = ps.reduce((s, p) => s + p.p50_h, 0), cyc = phases.find((p) => p.k === "cycle");
  let at = 0;
  return <figure class="dl-strip" role="img" aria-label={`Phase medians end to end: ${ps.map((p) => `${NAMES[p.k]} ${hours(p.p50_h)}`).join(", ")}; ${hours(total)} in all.`}>
    <figcaption class="sv-dim">Phase medians, laid end to end</figcaption>
    {ps.map((p, i) => { const a = (at / total) * 100, w = (p.p50_h / total) * 100; at += p.p50_h;
      return <div class="dl-strip-row" style={`--a:${a}%;--w:${w}%;--i:${i}`}><span class="dl-strip-k">{NAMES[p.k]}</span><span class="dl-strip-t"><i /></span><span class="dl-strip-v num">{hours(p.p50_h)}</span></div>; })}
    <div class="dl-strip-row dl-strip-sum"><span class="sv-dimline dl-dim"><span>{hours(total)} end to end{cyc?.enough ? `; cycle time P50 ${hours(cyc.p50_h)}` : ""}</span></span></div>
  </figure>;
}

// An in-depth tab with nothing to show says what fills it.
function Off({ title, to, label, doc, children }: { title: string; to?: string; label?: string; doc?: string; children?: preact.ComponentChildren }) {
  return <Card><EmptyState icon="clock" title={title} action={to ? <Button variant="tinted" href={to}>{label}</Button> : doc ? <Button variant="plain" href={DOCS + doc} iconEnd="external">How it works</Button> : null}>{children}</EmptyState></Card>;
}

// A tier the range doesn't settle says what else it could be.
function Tier({ t, span }: { t?: string | null; span?: string[] | null }) {
  if (!t) return <span class="muted">not enough data</span>;
  let more = "";
  if (span) {
    const [a, b] = span.map((x) => ORDER.indexOf(x)).sort();
    more = b! - a! > 1 ? `could be anywhere from ${ORDER[a!]} to ${ORDER[b!]}` : `could be ${span.find((x) => x !== t) || span[1]}`;
  }
  return <><StatePill value={t} />{more ? <span class="muted"> ({more})</span> : null}</>;
}
const likely = (r: Num[] | null | undefined, f: (v: Num) => string) => (r ? `, likely ${f(r[0])} to ${f(r[1])}` : "");

// This week against the four before: what moved beyond noise and what held.
function ThisWeek({ changes }: { changes?: CiChange[] }) {
  const run = (changes || []).filter((c) => !c.note && !c.shown_with && c.now != null);
  if (!run.length) return <Card><p class="blk-note">Too few pull requests or deployments this week to compare with the four weeks before.</p></Card>;
  const fmt = (c: CiChange, v: number) => (c.unit === "share" ? pct(v) : c.unit === "h" ? hours(v) : c.unit === "count" ? String(+(+v).toFixed(1)) : `${+(+v).toFixed(1)} ${c.unit}`);
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  const smallest = (c: CiChange) => (c.detectable ? (c.unit === "share" ? `${Math.round(c.detectable * 100)} points` : `${c.detectable >= 3 ? Math.round(c.detectable) : c.detectable.toFixed(1)}×`) : "–");
  return <Table name="this-week" search={false} rows={run.map((c) => ({ ...c, id: c.label }))} columns={[
    { key: "label", label: "Measure", primary: true, raw: (c) => cap(c.label) },
    { key: "now", label: "This week", num: true, raw: (c) => c.now, render: (c) => fmt(c, c.now) },
    { key: "base", label: "Four weeks before", num: true, raw: (c) => c.base, render: (c) => (c.base == null ? "–" : fmt(c, c.base)) },
    { key: "changed", label: "Reading", raw: (c) => (c.changed ? (c.direction === "up" ? "Rose" : "Fell") : "Steady"),
      render: (c) => (c.changed ? <Mark tone="accent">{c.direction === "up" ? "Rose" : "Fell"}</Mark> : <Mark tone="neutral">Steady, within noise</Mark>) },
    { key: "n", label: "Pull requests", num: true, raw: (c) => (c as R).n_now ?? null, render: (c) => ((c as R).n_now != null ? `${(c as R).n_now} vs ${(c as R).n_base ?? 0}` : "–") },
    { key: "detectable", label: "Smallest change that shows", num: true, raw: (c) => c.detectable ?? null, render: smallest }]} />;
}

function Rows({ app, phase }: { app: AppJson; phase: string }) {
  const f = useFiles<{ metrics: R[]; prs: R[] }>({ metrics: "table:devlake_project_pr_metrics", prs: "table:devlake_pull_requests" });
  if (!f.ready) return <PageSkeleton />;
  const byId = Object.fromEntries((f.prs || []).map((p) => [p.id, p]));
  const col = METRIC[phase];
  const rows = (f.metrics || []).map((m) => ({ ...m, pr: byId[m.id] || {}, value: col && m[col] != null ? m[col] / 60 : null })).filter((r) => r.value !== null) as R[];
  return <Page title={`${NAMES[phase] || phase}: the pull requests behind it`} subtitle={`${HELP[phase] || ""}. Every merged pull request in the data, longest first; the page's P75 leaves LinearB's outliers out.`}
    toolbar={<Button variant="plain" icon="left" href="#/delivery">Delivery</Button>}>
    <Section title="Pull requests" description="Longest first. Search, filter or download.">
      {f.metrics ? <Table name={`delivery-${phase}`} caption={`${NAMES[phase] || phase} by pull request`} rows={rows} initialSort={{ key: "value", desc: true }} columns={[
        { key: "pr", label: "Pull request", primary: true, raw: (r) => r.pr.pull_request_key, render: (r) => <><a href={r.pr.url || gh(app, `/pull/${r.pr.pull_request_key}`)} {...ext}>#{r.pr.pull_request_key}</a> {short(r.pr.title || "", 70)}</> },
        { key: "author", label: "Author", raw: (r) => r.pr.author_name },
        { key: "value", label: NAMES[phase] || phase, num: true, render: (r) => hours(r.value) },
        { key: "pr_merged_date", label: "Merged", render: (r) => day(r.pr_merged_date) }]} />
        : <Card><EmptyState icon="search" title="The rows aren't published here.">On public repos they sit beside the app; for a private repo open it with <code>stackvitals ui</code>.</EmptyState></Card>}
    </Section>
  </Page>;
}

// AI, issues and the merge queue load with their tab only.
type More = typeof import("./delivery/more");
let more: Promise<More> | null = null;
function Lazy({ name, ...p }: { name: "AI" | "Issues" | "Queue" | "Risk" | "Changed" | "Bugs" | "Releases" | "Deploys" | "Range" | "Quality" } & R) {
  const [m, setM] = useState<More | null>(null);
  useEffect(() => { (more ||= import("./delivery/more")).then(setM); }, []);
  if (!m) return <Skeleton lines={4} />;
  const C = m[name] as (x: R) => preact.JSX.Element;
  return <C {...p} />;
}

const teamCols = (label: string) => [{ key: "team", label, primary: true }, { key: "n", label: "PRs", num: true },
  { key: "pickup", label: "Pickup P75", num: true, raw: (t: R) => t.pickup?.p75_h, render: (t: R) => (t.pickup?.enough ? hours(t.pickup.p75_h) : "–") },
  { key: "cycle", label: "Cycle time to merge P75", num: true, raw: (t: R) => t.cycle_to_merge?.p75_h, render: (t: R) => (t.cycle_to_merge?.enough ? hours(t.cycle_to_merge.p75_h) : "–") }];

// DORA per team, from the deployments that shipped each team's PRs (shown when the team has any).
const teamDora = [
  { key: "dd", label: "Deploy days a week", num: true, raw: (t: R) => t.dora?.deployment_days_per_week, render: (t: R) => (t.dora ? String(t.dora.deployment_days_per_week ?? "–") : "–") },
  { key: "lt", label: "Lead time", num: true, raw: (t: R) => t.dora?.lead_time_hours, render: (t: R) => (t.dora?.lead_time_hours != null ? hours(t.dora.lead_time_hours) : "–") },
  { key: "cfr", label: "Change fail rate", num: true, raw: (t: R) => t.dora?.change_failure_rate, render: (t: R) => (t.dora?.change_failure_rate != null ? pct(t.dora.change_failure_rate) : "–") },
  { key: "rec", label: "Recovery", num: true, raw: (t: R) => t.dora?.recovery_hours, render: (t: R) => (t.dora?.recovery_hours != null ? hours(t.dora.recovery_hours) : "–") }];

export default function Delivery({ app, route }: PageProps) {
  if (app && route.rest[0] === "rows") return <Rows app={app} phase={route.query.get("phase") || "cycle"} />;
  return <Main app={app} route={route} />;
}

function Main({ app, route }: { app: AppJson | null; route: Route }) {
  const f = useFiles<{ d: D; alerts: Alerts }>({ d: "delivery.json", alerts: "alerts.json" });
  const [ranges, setRange] = useRange();
  const [pick, setPick] = useState<string | null>(null);
  if (!app) return <Page title="Delivery"><EmptyState icon="setup" title="No StackVitals data here yet" action={<Button variant="filled" href="#/setup">Set it up</Button>} /></Page>;
  if (!f.ready) return <PageSkeleton />;
  const d = f.d;
  if (!d) return <Page title="Delivery" subtitle="DORA measures from deploys and releases, and where pull request time goes.">
    <EmptyState icon="delivery" title="Delivery hasn't run here yet." action={<Button variant="filled" href="#/settings" icon="settings">Turn it on</Button>}>It runs with Team Flow on the schedule.</EmptyState></Page>;
  const dora: R = d.dora || {}, al = f.alerts, series = al?.series || {}, limits = al?.limits || {}, minN = al?.min_n ?? 10;
  const daily = (id: string, key: string, name: string, kind: Kind, unit: string): Metric => {
    const lim = limits[key];
    return { id, name, sub: `Each day over the 28 before; blank under ${minN} ${unit}`, kind, better: "down", period: "day",
      points: (series[key] || []).filter(([, y, n]) => y != null && (n ?? 0) >= minN).map(([t, y, n]) => ({ label: dateLabel(t), value: y as number, n })),
      meaning: (v) => `${kind === "share" ? pct(v) : hours(v)} over the 28 days before${lim != null ? `; the alert fires above ${kind === "share" ? pct(lim) : hours(lim)}` : ""}.`,
      info: { title: name, body: `Worked out each day over the 28 days before it. Days with fewer than ${minN} ${unit} are left out, as the alert rule ignores them.`,
        facts: lim != null ? [["Alert limit", kind === "share" ? pct(lim) : hours(lim)]] : [], doc: "dora-guide.md" } };
  };
  const metrics = [
    { id: "deploys", name: "Deployments", sub: "By month", kind: "count", better: "up", period: "month", points: (dora.monthly || []).map((m: R) => ({ label: dateLabel(m.month), value: m.deployments })),
      meaning: (v: number) => `${count(Math.round(v), "deployment")} that month.`, info: { title: "Deployments", body: "Deployments StackVitals found, by month. DORA's deployment frequency is read from these.", doc: "dora-guide.md" } } as Metric,
    daily("pickup", "pickup_p75_hours", "Pickup, P75", "hours", "PRs"), daily("review", "review_p75_hours", "Review, P75", "hours", "PRs"),
    daily("cycle", "cycle_p75_hours", "Cycle time to merge, P75", "hours", "PRs"), daily("cfr", "change_failure_rate", "Change fail rate", "share", "deployments"),
    ...([["lead_time_hours", "Lead time", "hours", "down"], ["change_failure_rate", "Change fail rate", "share", "down"],
      ["recovery_hours", "Recovery", "hours", "down"], ["deployments", "Deployments", "count", "up"]] as const).map(([key, name, kind, better]) => ({
      id: `week-${key}`, name, sub: "By week, as DORA counts the window", kind, better, period: "week",
      points: (d.dora_weeks || []).filter((w: R) => w[key] != null).map((w: R) => ({ label: dateLabel(w.week), value: w[key] })),
      meaning: (v: number) => `${kind === "share" ? pct(v) : kind === "hours" ? hours(v) : count(Math.round(v), "deployment")} that week.`,
      info: { title: `${name} by week`, body: "Each Monday-to-Monday week counted with DevLake's DORA rules, as the window's number is.", doc: "dora-guide.md" } }) as Metric),
  ].filter((m) => m.points.length);
  const metric = metrics.find((m) => m.id === pick) || metrics[0];
  const TABS = [["incidents", "Incidents"], ["range", "Any dates"], ["quality", "Code quality"], ["deploys", "Deployments"], ["teams", d.by_service ? "By team and service" : "By team"],
    ["ai", "AI-assisted work"], ["risk", "Change risk"], ["issues", "Issues and sprints"], ["bugs", "Bugs"], ["releases", "Releases"], ["queue", "Merge queue"]];
  const q = route.query.get("tab") || "";
  const tab = TABS.some(([k]) => k === q) ? q : "incidents";
  const fix = dora.cfr_fix_chain != null && dora.cfr_fix_chain !== dora.change_failure_rate
    ? `; by each revert's fix chain: ${pct(dora.cfr_fix_chain)}${dora.linkage?.never_shipped ? ` (${dora.linkage.never_shipped} reverted before any deployment shipped them)` : ""}` : "";
  const chk: R | undefined = d.deploy_check;
  const others = (chk?.workflows || []).filter((w: R) => !w.kind);
  const checkRows = chk ? [
    ...(chk.considered || []).map((x: R) => ({ what: SOURCES[x.source] || x.source, n: x.found, said: x.used ? "counted" : "passed over" })),
    ...(chk.workflows || []).filter((w: R) => w.kind && (!w.used || w.skipped)).map((w: R) => ({ what: w.name || w.path, n: w.used ? w.skipped : "",
      said: w.used ? "runs skipped: failed, or not a release or the default branch" : `passed over: ${SOURCES[chk.source] || chk.source || "nothing"} is used` })),
    ...(others.length > 5 ? [{ what: `${others.length} other workflows`, n: "", said: "names don't match deploy_workflow" }] : others.map((w: R) => ({ what: w.name || w.path, n: "", said: w.why }))),
    ...(chk.environments || []).filter((e: R) => !e.counted).map((e: R) => ({ what: `environment ${e.name}`, n: e.deployments, said: `not counted (${e.as})` }))] : [];
  const phases: R[] = Object.entries(d.phases || {}).map(([k, v]) => ({ k, ...(v as R) }));
  const ag = d.agreements as R | null;
  return <Page title="Delivery" subtitle={`Last ${d.window_days} days. Deployments from ${SOURCES[d.deploy_source] || d.deploy_source || "nowhere yet"}${d.deploy_confidence ? ` (${d.deploy_confidence} confidence)` : ""}. DORA is counted as DevLake's dashboard counts it (${dora.report || "2023"} report).${d.incident_source ? ` Incidents from ${d.incident_source}.` : ""}`}
    toolbar={app.modules?.delivery?.page ? <Button variant="plain" href={app.modules.delivery.page} iconEnd="external">Printable page</Button> : null}>
    {d.deployments_unreadable ? <div class="note note-watch"><Icon name="warn" /><span>GitHub's Deployments API couldn't be read with the workflow's token (add <code>deployments: read</code>), so deployments come from releases or workflows.</span></div> : null}
    {d.deploy_confidence === "low" ? <div class="note note-watch"><Icon name="warn" /><span>Deployments are guessed from workflow names. If those don't put code in front of users, choose the source in {SET}.</span></div> : null}

    {metric ? <Section title="Trends" description="Deployments by month and the 90-day review trends. Drag across the chart, or pick a row to chart it.">
      <Columns ratio="lead">
        <Card><MetricHero metric={metric} ranges={ranges} setRange={setRange} /></Card>
        <Watchlist label="Delivery trends" items={metrics.map((m) => metricItem(m, ranges[m.period] || 12))} selected={metric.id} onSelect={setPick} tones={trendTones(metrics, ranges)} />
      </Columns>
      {al ? null : <p class="muted small">The 90-day trend appears after the first scheduled run with this version.</p>}
    </Section> : null}

    <Section title="DORA" description="The four keys plus rework, each with its tier and likely range."
      info={<InfoButton info={{ title: "DORA tiers", body: "Each measure is placed in DORA's elite, high, medium or low band. When the likely range crosses a band edge, the other possible tier is named too. Change fail rate ties a failure to the last deployment before it, as DevLake does.", doc: "dora-guide.md" }} />}>
      <Dim>last {d.window_days} days, DevLake's rules</Dim>
      <Stats>
        <Stat label="Deployment frequency" value={dora.frequency_tier && dora.deployment_days_per_week != null ? `${dora.deployment_days_per_week} days a week` : `${dora.deployments ?? 0} in ${d.window_days} days`} note={<><Tier t={dora.frequency_tier} />{dora.deployment_days != null ? <><br />{dora.deployment_days} days with a deployment; {dora.deployment_days_per_month ?? "–"} a month{dora.deployment_days_per_six_months != null ? `, ${dora.deployment_days_per_six_months} in six months` : ""}</> : null}<br /><EvidenceLink kind="deployments" ev={dora.evidence} repo={app.repo} /></>} />
        <Stat label="Change lead time" value={hours(dora.lead_time_hours)} note={<><Tier t={dora.lead_time_tier} span={dora.lead_time_tier_span} /><br />n = {dora.lead_time_n ?? 0}{likely(dora.lead_time_range_hours, hours)}{dora.lead_time_working_hours != null ? <><br />{hours(dora.lead_time_working_hours)} in working hours, by your working calendar</> : null}<br /><EvidenceLink kind="lead_time" ev={dora.evidence} repo={app.repo} /></>} />
        <Stat label="Change fail rate" value={pct(dora.change_failure_rate)} note={<><Tier t={dora.cfr_tier} span={dora.cfr_tier_span} /><br />{dora.failed_deployments ?? 0} failed{likely(dora.cfr_range, pct)}{fix}{dora.linkage ? <><br /><span class="muted small">{dora.linkage.reverts ?? 0} reverts, {dora.linkage.fix_chain_found ?? 0} traced through their fix chain{dora.linkage.disagree ? `, ${dora.linkage.disagree} where time order and the fix chain blame different deployments` : ""}</span></> : null}<br /><EvidenceLink kind="failed" ev={dora.evidence} repo={app.repo} /></>} />
        <Stat label="Failed deployment recovery" value={hours(dora.recovery_hours)} note={<><Tier t={dora.recovery_tier} span={dora.recovery_tier_span} /><br />n = {dora.recovery_n ?? 0}{likely(dora.recovery_range_hours, hours)}<br /><EvidenceLink kind="recovery" ev={dora.evidence} repo={app.repo} /></>} />
        <Stat label="Deployment rework rate" value={pct(dora.rework_rate)} info={<InfoButton info={{ title: "Rework rate", body: "Deployments that shipped a revert or a hotfix, over all deployments." }} />}
          note={dora.rework_deployments === undefined ? "not measured yet" : `${dora.rework_deployments} of ${dora.deployments_n ?? 0} shipped a fix${likely(dora.rework_range, pct)}`} />
      </Stats>
      <Framed title="This week" note="against the four weeks before; a change counts only beyond the usual noise"><ThisWeek changes={d.changes} /></Framed>
    </Section>

    <Section title="Deployments" description="The latest ones, and what StackVitals counts as a deployment." action={<Button size="sm" variant="plain" href="#/settings?module=delivery" iconEnd="right">Change the source</Button>}>
      <div class={chk ? "blk-grid dl-deps" : ""}>
        <Framed title="Latest deployments" note="newest first"><Table name="deployments" caption="Latest deployments" search={false} rows={[...(d.deployments || [])].reverse()} columns={[
          { key: "name", label: "What", primary: true, raw: (x: R) => short(x.name || x.id, 50) },
          { key: "sha", label: "Commit", nowrap: true, render: (x: R) => <a class="mono-soft" href={gh(app, `/commit/${x.sha}`)} {...ext}>{String(x.sha || "").slice(0, 7)}</a> },
          { key: "finished", label: "Finished", nowrap: true, render: (x: R) => day(x.finished) }]}
          empty={<Card><EmptyState icon="delivery" title="No deployments found.">Tell StackVitals where deployments come from in {SET}.</EmptyState></Card>} /></Framed>
        {chk ? <Framed title="What counts as a deployment" note="each source and workflow StackVitals looked at"><Table name="deploy-check" caption="What counts as a deployment" search={false} rows={checkRows}
          columns={[{ key: "what", label: "What", primary: true }, { key: "n", label: "How many", num: true },
            { key: "said", label: "Counted?", render: (x: R) => (x.said === "counted" ? <Mark tone="good">Counted</Mark> : <span>{x.said.charAt(0).toUpperCase() + x.said.slice(1)}</span>) }]} /></Framed> : null}
      </div>
      {chk ? <Panel title="How the source was chosen" class="dl-chk"><Facts rows={[
        chk.order_reason ? ["Why this source", `${chk.order_reason}.`] : null,
        chk.settings ? ["Source setting", <code>{chk.settings.source}</code>] : null,
        chk.settings ? ["Deploy workflow", <code>{chk.settings.deploy_workflow}</code>] : null,
        chk.settings ? ["Production environments", (chk.settings.production || []).join(", ") || "none"] : null,
        chk.releases ? ["Releases", `${chk.releases.published} published${chk.releases.prereleases_skipped ? `, ${chk.releases.prereleases_skipped} pre-releases left out` : ""}`] : null,
        d.deploy_names?.length ? ["Counted by name", d.deploy_names.map((x: R) => `${x.name || "unnamed"} (${x.n})`).join(", ")] : null]} /></Panel> : null}
    </Section>

    <Section title="Where pull request time goes" description={`${d.prs ?? 0} merged pull requests by people; ${d.outliers?.over_60_days || 0} over 60 days and ${d.outliers?.over_p98 || 0} past the 98th percentile left out${d.excluded ? `, ${d.excluded} excluded by the team` : ""}.`}>
      <PhaseStrip phases={phases} />
      <Framed title="Cycle time phases" note="P50 and P75 of merged pull requests; each phase opens its pull requests"><Table name="phases" caption="Cycle time phases" search={false} rows={phases} columns={[
        { key: "k", label: "Phase", primary: true, raw: (p) => NAMES[p.k] || p.k, render: (p) => <><b>{NAMES[p.k] || p.k}</b><div class="muted small">{HELP[p.k]}</div></> },
        { key: "p50_h", label: "P50", num: true, render: (p) => (p.enough ? hours(p.p50_h) : <span class="muted">fewer than 10</span>) },
        { key: "p75_h", label: "P75", num: true, render: (p) => (p.enough ? hours(p.p75_h) : "–") },
        { key: "n", label: "PRs", num: true },
        { key: "linearb_band", label: "LinearB band", render: (p) => (p.linearb_band ? <Pill tone={p.linearb_band === "elite" || p.linearb_band === "good" ? "good" : p.linearb_band === "fair" ? "watch" : "bad"}>{p.linearb_band.charAt(0).toUpperCase() + p.linearb_band.slice(1)}</Pill> : "–") },
        { key: "rows", label: "Pull requests", nowrap: true, raw: () => "", render: (p) => (METRIC[p.k] && app.summary !== null ? <Button size="sm" variant="tinted" href={`#/delivery/rows?phase=${p.k}`}>The PRs</Button> : <EvidenceLink kind="phase" ev={{ phase: p.evidence }} repo={app.repo} />) }]} /></Framed>
      <Habits d={d} app={app} />
    </Section>

    <Section title="Other sources" class="dl-other" description="Deployments from tools GitHub can't see, delivery for code on Bitbucket, Azure DevOps or GitLab, and one view across several repos."
      info={<InfoButton info={{ title: "Other sources", body: "Recorded deployments and incidents land on the data branch and count from the next run. The delivery commands run from your machine, read-only.", doc: "connectors.md" }} />}>
      <OtherSources app={app} />
    </Section>

    <Section title="In depth" description="Incidents, teams, AI-assisted work and more. Where the work went has its own page."
      action={<Button size="sm" variant="plain" href="#/investment" iconEnd="right">Investment</Button>}>
      <div class="dl-tabs"><SegmentedControl label="Show" scroll value={tab} onChange={(v) => navigate(withQuery(route, "tab", v === "incidents" ? null : v))}
        options={TABS.map(([k, l]) => ({ value: k!, label: <>{l}{k === "incidents" ? <span class="seg-count num">{(d.incidents || []).length}</span> : null}</> }))} /></div>
      <div class="dl-panel" key={tab}>
        {tab === "incidents" && d.deploy_attempts ? <Stats>
          <Stat label="Deploy attempts" value={d.deploy_attempts.attempts} note="in the window" />
          <Stat label="Failed" value={d.deploy_attempts.failed} note={d.deploy_attempts.cancelled ? `${d.deploy_attempts.cancelled} more cancelled` : "none cancelled"} />
          <Stat label="Succeeded" value={pct(d.deploy_attempts.success_rate)} note="of attempts that finished" />
          <Stat label="A successful deploy, median" value={d.deploy_attempts.median_minutes != null ? `${d.deploy_attempts.median_minutes} min` : "–"} />
        </Stats> : null}
        {tab === "incidents" ? <Framed title="Incidents" note="issues labelled as incidents, reverts, hotfixes and recorded ones"><Table name="incidents" caption="Incidents" rows={d.incidents || []} columns={[
          { key: "number", label: "Item", primary: true, render: (i: R) => (String(i.url || "").startsWith("https://") ? <a href={i.url} {...ext}>{i.number}</a>
            : <a href={gh(app, `/${i.source === "issue" ? "issues" : "pull"}/${i.number}`)} {...ext}>#{i.number}</a>) },
          { key: "source", label: "From", filter: true, raw: (i: R) => ({ issue: "Issue", pull: "Pull request", pr: "Pull request", revert: "Revert", hotfix: "Hotfix", recorded: "Recorded" } as R)[i.source] || String(i.source || "–").replace(/^./, (c) => c.toUpperCase()) },
          { key: "created", label: "Began", render: (i: R) => day(i.created) }, { key: "hours_to_restore", label: "Restored after", num: true, render: (i: R) => hours(i.hours_to_restore) }]}
          empty={<Card><EmptyState icon="check" title="No incidents in this window.">Issues labelled as incidents, reverts and hotfix pull requests count here.</EmptyState></Card>} /></Framed> : null}
        {tab === "incidents" && d.what_changed?.length ? <Lazy name="Changed" timelines={d.what_changed} repo={app?.repo} /> : null}
        {tab === "teams" ? <>
          {Object.keys(d.by_team || {}).length ? <Framed title="By team" note="your teams in Settings"><Table name="by-team" caption="By team (your settings)" rows={Object.entries(d.by_team).map(([team, v]) => ({ team, ...(v as R) }))} columns={[...teamCols("Team"), ...(Object.values(d.by_team).some((v) => (v as R).dora) ? teamDora : [])]} /></Framed>
            : <Card><EmptyState icon="community" title="No teams set." action={<Button variant="tinted" href="#/settings?module=people">Name your teams</Button>}>Name your teams in Settings to see cycle time per team.</EmptyState></Card>}
          {Object.keys(d.by_service || {}).length ? <><Framed title="By service" note="your [services] paths; a pull request touching two counts in both">
            <Table name="by-service" caption="By service" rows={Object.entries(d.by_service).map(([team, v]) => ({ team, ...(v as R) }))} columns={[...teamCols("Service"),
              { key: "deployments", label: "Deployments", num: true, render: (t: R) => (t.dora ? t.deployments : "–") },
              { key: "lead", label: "Lead time", num: true, raw: (t: R) => t.dora?.lead_time_hours, render: (t: R) => (t.dora ? hours(t.dora.lead_time_hours) : "–") },
              { key: "cfr", label: "Change failure", num: true, raw: (t: R) => t.dora?.change_failure_rate, render: (t: R) => (t.dora && t.dora.change_failure_rate != null ? `${Math.round(t.dora.change_failure_rate * 100)}%` : "–") }]} /></Framed>
            {Object.values(d.by_service).some((s) => !(s as R).dora) ? <p class="blk-note">DORA shows for a service once it has a deploy pattern telling its deployments apart.</p> : null}</> : null}
          {Object.keys(d.by_owner || {}).length ? <Framed title="By owning team" note="from CODEOWNERS"><Table name="by-owner" caption="By owning team" rows={Object.entries(d.by_owner).map(([team, v]) => ({ team, ...(v as R) }))} columns={teamCols("Owners")} /></Framed> : null}
        </> : null}
        {tab === "ai" ? (d.ai?.outcomes === undefined ? <Off title="Not measured yet." to="#/connections" label="Connect AI tools">The next run with this version fills it in. Copilot reports and AI spend (Anthropic, OpenAI, Cursor) are added from Connections.</Off> : <Lazy name="AI" ai={d.ai} survival={d.code_survival} />) : null}
        {tab === "issues" ? (d.tracker ? <Lazy name="Issues" t={d.tracker} /> : <Off title="No issue tracker connected." to="#/connections" label="Connect Jira or Linear">
          Connect Jira or Linear to see lead and cycle time by issue type, sprints and cycles, and tracker incidents in DORA.</Off>) : null}
        {tab === "risk" ? (d.change_risk ? <Lazy name="Risk" r={d.change_risk} repo={app?.repo} /> : <Off title="Not measured yet.">The next run with this version scores open pull requests, once this repo's own backtest shows the score works here.</Off>) : null}
        {tab === "quality" ? (d.code_quality ? <Lazy name="Quality" q={d.code_quality} /> : <Off title="No SonarQube or SonarCloud project connected." to="#/connections" label="Connect SonarQube" doc="connectors.md#code-quality-sonarqube-or-sonarcloud">
          Name the Sonar project to read its quality gate, bugs, vulnerabilities, code smells, coverage and duplication once a day. A public SonarCloud project needs no key.</Off>) : null}
        {tab === "range" ? (d.dora_rows?.deployments?.length ? <Lazy name="Range" rows={d.dora_rows} /> : <Off title={d.dora_rows ? "No deployments in the last year." : "Not measured yet."}>
          {d.dora_rows ? <>Tell StackVitals where deployments come from in {SET}, then pick any dates here.</> : "The next scheduled run with this version keeps a year of deployments, so DORA can be read for any dates."}</Off>) : null}
        {tab === "deploys" ? (d.deployment_list?.length ? <Lazy name="Deploys" rows={d.deployment_list} repo={app.repo} /> : <Off title="No deployments in the window." to="#/settings?module=delivery" label="Choose the source">
          Each deployment lists the pull requests it shipped, their authors, lead time and the incidents tied to it. Deployments come from GitHub's Deployments API, releases or deploy workflows, or from any tool with <code>stackvitals record</code>.</Off>) : null}
        {tab === "releases" ? (d.releases?.length ? <Lazy name="Releases" rows={d.releases} repo={app.repo} /> : <Off title="No releases to compare yet.">
          Publish GitHub releases (two or more) to see what each shipped, the share that were fixes, and the reverts and incidents that followed it.</Off>) : null}
        {tab === "bugs" ? (d.bugs ? <Lazy name="Bugs" b={d.bugs} repo={app.repo} /> : <Off title="No bugs found." to="#/settings?module=delivery" label="Name the bug labels">
          Issues with a bug label, and Jira or Linear bugs when connected, fill the weekly backlog: opened, closed and still open.</Off>) : null}
        {tab === "queue" ? (d.merge_queue ? <Lazy name="Queue" app={app} q={d.merge_queue} /> : <Off title="This repo doesn't use a merge queue." doc="modules.md">
          With GitHub's merge queue on, this shows how long pull requests wait in it and which removals a flaky job caused.</Off>) : null}
      </div>
    </Section>

    {d.peers || ag ? <Section title="Elsewhere" description="Related readings on other pages.">
      <Panel title="See also"><Facts rows={[
        d.peers ? ["Similar public repos", <>Compared with {d.peers.population || "similar public repos"} on the {app.modules?.delivery?.page ? <a href={app.modules.delivery.page} {...ext}>printable page</a> : "printable page"}.</>] : null,
        ag ? ["Working agreements", <><Mark tone={(ag.exceptions || []).length ? "watch" : "good"}>{count((ag.exceptions || []).length, "exception")}</Mark> <a href="#/prs">See them on Pull Requests</a></>] : null]} /></Panel>
    </Section> : null}
  </Page>;
}
