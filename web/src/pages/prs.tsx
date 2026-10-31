// Pull Requests: review flow by month as a scrub chart, who acts next on each open one (with "only mine"), stuck ones,
// working-agreement exceptions, the review stages for insiders and outside contributors, and merge habits.
import "./prs.css";
import { useEffect, useState } from "preact/hooks";
import type { PageProps } from "../app/routes";
import { MetricHero, Watchlist, metricItem, trendTones, useRange } from "../charts/MetricHero";
import { BarChart } from "../charts/BarChart";
import type { Metric } from "../charts/metric";
import { useFiles } from "../data/files";
import { count, dateLabel, day, hours, pct, secs, short } from "../data/format";
import { prefs } from "../data/store";
import type { DeliveryJson, FlowJson, Num } from "../data/types";
import { Decide } from "../features/Decide";
import { Button } from "../ui/Button";
import { EmptyState, InfoButton, PageSkeleton, Skeleton } from "../ui/bits";
import { TextInput } from "../ui/controls";
import { Card, Columns, Page, Section, Stat, Stats } from "../ui/Page";
import { Table } from "../ui/Table";
import { Facts, Framed, Mark, Panel } from "./delivery/blocks";
import { AutoNote, Preflight, Triage } from "./prs/parts";
// Loose shape for the optional sections read straight from flow.json.
type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

interface Stage { median_s?: Num; p90_s?: Num; n?: number }
interface QItem { n: number; title: string; author?: string; outsider?: boolean; actor?: string; who?: string[]; why?: string; since?: string; waiting_s?: Num; usual_s?: Num; stale?: boolean; gaps?: { what: string; why: string }[] }
interface Group { merged?: number; closed_unmerged?: number; merge_rate?: Num; merged_without_review?: number; pickup?: Stage; review?: Stage; merge?: Stage; cycle?: Stage }
type Flow = Omit<FlowJson, "queue" | "monthly"> & {
  drafts?: number; closed_unmerged?: number; merged_without_review?: number; stages?: Record<string, Stage>; queue?: QItem[];
  monthly?: { month: string; opened?: number; merged?: number; pickup_median_s?: Num; cycle_median_s?: Num }[];
  load?: { reviewer: string; open_requests: number; oldest_since?: string }[]; baselines?: Record<string, Num>; bots?: { open?: number; closed?: number }; excluded?: number;
  knowledge?: R; delivery?: R; measures?: Record<string, { low?: Num; high?: Num }>; groups?: Record<string, Group>;
  habits?: { scope?: string; merged_prs?: number; include?: Record<string, Num>; size?: { median_lines?: Num; p75_lines?: Num; p90_lines?: Num }; asks?: { ask: string; share: number; prs: number }[] };
};
interface Agreements { labels: Record<string, string>; counts: Record<string, number>; window_days?: number; merged?: number;
  exceptions: { pr: number; rule: string; value?: number | boolean | null; open?: boolean }[]; weekly?: Record<string, [string, number, number?][]> }
type Del = Omit<DeliveryJson, "stuck"> & { stuck?: Record<string, { pr: number; since?: string; why?: string; hours?: number }[]>; agreements?: Agreements | null };

const UNITS: Record<string, string> = { review_within_hours: " h", merge_within_days: " days", max_pr_lines: " lines" };
const STUCK: Record<string, string> = { hanging_review: "Review asked, not started for 3+ days", long_lived: "Ready for more than 30 days",
  high_interaction: "10+ comments or reviews", red_and_idle: "Failing checks nobody acted on for a day" };
// Who holds the next move, in plain words.
const ACTOR: Record<string, string> = { author: "Author", reviewer: "Reviewer", maintainer: "Maintainer", merger: "Whoever merges" };
const STAGE: Record<string, string> = { pickup: "Waiting for first review", review: "First to final review", merge: "Approved to merged", cycle: "Ready to merge" };

// The knowledge map, releases and local commands load with their sections only.
type More = typeof import("./prs/more");
let more: Promise<More> | null = null;
function Lazy({ name, ...p }: { name: "Knowledge" | "Releases" } & R) {
  const [m, setM] = useState<More | null>(null);
  useEffect(() => { (more ||= import("./prs/more")).then(setM); }, []);
  if (!m) return <Skeleton lines={4} />;
  const C = m[name] as (x: R) => preact.JSX.Element;
  return <C {...p} />;
}
// Sheet design only: a dimension line naming the window the numbers below cover.
function Dim({ children }: { children: preact.ComponentChildren }) {
  return <p class="sv-dimline pr-dim" aria-hidden="true"><span>{children}</span></p>;
}
const GAP: Record<string, string> = { tests: "No tests", changelog: "No changelog entry", docs: "No docs", size: "Unusually big" };

export default function PullRequests({ app }: PageProps) {
  const f = useFiles<{ flow: Flow; del: Del; pulse: PulseFile; settings: { values?: unknown } }>({ flow: "flow.json", del: "delivery.json", pulse: "pulse.json", settings: "settings.json" });
  const [me, setMe] = useState<string>(() => prefs.get("me", ""));
  const [ranges, setRange] = useRange();
  const [pickM, setPickM] = useState<string | null>(null);
  const title = "Pull Requests";
  if (!app) return <Page title={title}><EmptyState icon="setup" title="No StackVitals data here yet" action={<Button variant="filled" href="#/setup">Set it up</Button>} /></Page>;
  if (!f.ready) return <PageSkeleton />;
  const fl = f.flow;
  if (!fl) return <Page title={title} subtitle="Who acts next, stuck pull requests and how long reviews take.">
    <EmptyState icon="prs" title="Team Flow hasn't run here yet." action={<Button variant="filled" href="#/settings" icon="settings">Turn it on</Button>}>Add <code>flow</code> to the workflow's modules; it runs every 3 hours.</EmptyState></Page>;
  const gh = (p: string) => `https://github.com/${app.repo}${p}`;
  const handle = me.trim().replace(/^@/, "").toLowerCase();
  const all = fl.queue || [];
  const queue = all.filter((p) => !handle || (p.author || "").toLowerCase() === handle || (p.who || []).some((w) => String(w).toLowerCase() === handle));
  const stuck = Object.entries(f.del?.stuck || {}).flatMap(([k, rows]) => (rows || []).map((r) => ({ ...r, kind: STUCK[k] || k })));
  const ag = f.del?.agreements;
  const st = fl.stages || {};
  const mo = fl.monthly || [];
  const range = (n: number | undefined, m?: { low?: Num; high?: Num }) => (n === undefined ? undefined : m?.low != null ? `n = ${n}, likely ${secs(m.low)} to ${secs(m.high)}` : `n = ${n}`);
  const pts = (g: (x: (typeof mo)[number]) => Num) => mo.filter((x) => g(x) != null).map((x) => ({ label: dateLabel(x.month), value: g(x) as number }));
  const metrics: Metric[] = ([
    { id: "pickup", name: "First review", sub: "Median wait, by month", kind: "secs", better: "down", period: "month", points: pts((x) => x.pickup_median_s),
      meaning: (v) => `Half of the pull requests asking for review got a first answer within ${secs(v)}.`,
      info: { title: "First review", body: "Time from a pull request being ready for review until someone else first comments or reviews it. The median of that month's pull requests.", doc: "methods.md" } },
    { id: "cycle", name: "Ready to merge", sub: "Median, by month", kind: "secs", better: "down", period: "month", points: pts((x) => x.cycle_median_s),
      meaning: (v) => `Half of the merged pull requests went from ready to merged within ${secs(v)}.`,
      info: { title: "Ready to merge", body: "Time from a pull request being ready for review until it merged, by month of merge.", doc: "methods.md" } },
    { id: "merged", name: "Merged", sub: "Pull requests by month", kind: "count", better: "up", period: "month", points: pts((x) => x.merged), meaning: (v) => `${Math.round(v)} pull requests merged that month.` },
    { id: "opened", name: "Opened", sub: "Pull requests by month", kind: "count", better: null, period: "month", points: pts((x) => x.opened), meaning: (v) => `${Math.round(v)} pull requests opened that month.` },
  ] as Metric[]).filter((m) => m.points.length);
  const metric = metrics.find((m) => m.id === pickM) || metrics[0];
  const save = (v: string) => { setMe(v); prefs.set("me", v); };
  const groups = Object.entries(fl.groups || {});
  const hb = fl.habits;
  return <Page title={title} subtitle={`Open pull requests and who has the next move, from the last ${fl.window_days ?? 90} days.`}
    toolbar={app.modules?.flow?.page ? <Button variant="plain" href={app.modules.flow.page} iconEnd="external">Printable page</Button> : null}>

    {metric ? <Section title="Review flow" description="Month by month. Drag across the chart, or pick a row to chart it.">
      <Columns ratio="lead">
        <Card><MetricHero metric={metric} ranges={ranges} setRange={setRange} /></Card>
        <Watchlist label="Review flow" items={metrics.map((m) => metricItem(m, ranges[m.period] || 6))} selected={metric.id} onSelect={setPickM} tones={trendTones(metrics, ranges)} />
      </Columns>
    </Section> : null}

    <Section title="Key numbers" class="pr-key" description={`Last ${fl.window_days ?? 90} days.`}>
      <Dim>last {fl.window_days ?? 90} days</Dim>
      <Stats>
        <Stat label="Open" value={fl.open ?? 0} note={`${fl.drafts || 0} drafts`} />
        <Stat label="Merged" value={fl.merged ?? 0} note={`${fl.closed_unmerged ?? 0} closed without merging`} />
        <Stat label="First review, median" value={secs(st.pickup?.median_s)} note={range(st.pickup?.n, fl.measures?.["flow.pickup_time"])} />
        <Stat label="Ready to merge, median" value={secs(st.cycle?.median_s)} note={range(st.cycle?.n, fl.measures?.["flow.cycle_time"])} />
        <Stat label="Stale" value={fl.stale ?? 0} note="waiting over 30 days" />
        {fl.merged_without_review !== undefined ? <Stat label="Merged without review" value={fl.merged_without_review} /> : null}
      </Stats>
      {fl.bots || fl.excluded ? <Panel title="Left out of every number" class="pr-left"><Facts rows={[
        fl.bots ? ["Bots' pull requests", `${fl.bots.open ?? 0} open, ${fl.bots.closed ?? 0} closed`] : null,
        fl.excluded ? ["Left out by the team", `${count(fl.excluded, "pull request")} (a label or /stackvitals exclude)`] : null]} /></Panel> : null}
    </Section>

    <Section title="Who acts next" description="Each open pull request, whoever holds the next move and why, longest wait first."
      action={<div class="pr-me"><TextInput value={me} onInput={save} placeholder="Only mine: your handle" label="Only mine: your GitHub handle, kept on this device" />
        {me ? <Button size="sm" variant="plain" onClick={() => save("")}>Show all</Button> : null}</div>}>
      <div class="pr-queue"><Table name="who-acts-next" caption="Who acts next" rows={queue} initialSort={{ key: "waiting_s", desc: true }} columns={[
        { key: "n", label: "Pull request", primary: true, raw: (p) => `#${p.n} ${p.title}`, render: (p) => <><a href={gh(`/pull/${p.n}`)} target="_blank" rel="noopener noreferrer">#{p.n}</a> {short(p.title, 80)}</> },
        { key: "author", label: "Author", raw: (p) => p.author || "",
          render: (p) => <>{p.author || "–"}{p.outsider ? <div><Mark tone="accent">Outside contributor</Mark></div> : null}</> },
        ...(all.some((p) => p.actor || p.who?.length) ? [{ key: "actor", label: "Next move", filter: true, raw: (p: QItem) => ACTOR[p.actor || ""] || p.actor || "–",
          render: (p: QItem) => <><b>{ACTOR[p.actor || ""] || p.actor || "–"}</b>{p.who?.length ? <div class="muted">{p.who.join(", ")}</div> : null}</> }] : []),
        { key: "why", label: "Why", render: (p) => <span class="pr-why">{short(p.why, 90)}</span> },
        ...(all.some((p) => p.gaps?.length) ? [{ key: "gaps", label: "Differs from merged PRs", raw: (p: QItem) => (p.gaps || []).map((g) => GAP[g.what] || g.what).join(", "),
          render: (p: QItem) => (p.gaps?.length ? <ul class="pr-gaps">{p.gaps.map((g) => <li title={g.why}><Mark tone="watch">{GAP[g.what] || g.what}</Mark><span class="muted small">{g.why}</span></li>)}</ul>
            : <span class="muted">–</span>) }] : []),
        { key: "waiting_s", label: "Waiting", num: true, raw: (p) => p.waiting_s ?? 0, render: (p) => <>{p.waiting_s != null ? secs(p.waiting_s) : `since ${day(p.since)}`}
          {p.usual_s ? <div class="muted small">usual {secs(p.usual_s)}</div> : null}{p.stale ? <div><Mark tone="watch">Stale</Mark></div> : null}</> },
        { key: "decide", label: "Decide", nowrap: true, raw: () => "", render: (p) => <Decide app={app} kind="pr" id={String(p.n)} verbs={["exclude"]} label="Leave out" /> },
      ]} empty={<Card><EmptyState icon="check" title={handle ? `Nothing waits on ${handle}.` : "Nothing is waiting."}>Open pull requests appear here with whoever holds the next move.</EmptyState></Card>} /></div>
    </Section>

    <Section title="Stuck" description="Waiting on a review for days, red and idle, or dragging on." action={<Mark tone={stuck.length ? "watch" : "good"}>{stuck.length ? `${stuck.length} stuck` : "None stuck"}</Mark>}>
      <Table name="stuck" caption="Stuck pull requests" rows={stuck} columns={[
        { key: "pr", label: "Pull request", primary: true, render: (s) => <a href={gh(`/pull/${s.pr}`)} target="_blank" rel="noopener noreferrer">#{s.pr}</a> },
        { key: "kind", label: "Stuck because", filter: true },
        { key: "why", label: "Detail", render: (s) => <span class="muted">{s.why || (s.hours ? hours(s.hours) : "")}</span> },
        { key: "since", label: "Since", render: (s) => day(s.since) }]}
        empty={<Card><EmptyState icon="check" title="Nothing is stuck.">Pull requests waiting on a review for days, red and idle, or dragging on show up here.</EmptyState></Card>} />
    </Section>

    {(fl as R).rules?.length ? <Section title="Rules" description="Your [[rules]]: what each matches now, and what it would have matched among recent merged pull requests.">
      <Table name="pr-rules" caption="PR rules" search={false} rows={(fl as R).rules as R[]} columns={[
        { key: "name", label: "Rule", primary: true },
        { key: "dry_run", label: "Mode", raw: (r: R) => (r.dry_run ? "Dry run" : "Acting"), render: (r: R) => (r.dry_run ? <Mark tone="neutral">Dry run</Mark> : <Mark tone="good">Acting</Mark>) },
        { key: "open", label: "Open PRs matched", num: true, raw: (r: R) => (r.open || []).length,
          render: (r: R) => ((r.open || []).length ? (r.open as number[]).slice(0, 5).map((n) => `#${n}`).join(", ") : "none") },
        { key: "replay", label: "Recent merged matched", num: true, raw: (r: R) => r.replay?.matched,
          render: (r: R) => `${r.replay?.matched ?? 0} of ${r.replay?.of ?? 0}` }]} />
    </Section> : null}
    <Section title="Working agreements" description="The team's own rules and the pull requests that broke them."
      info={<InfoButton info={{ title: "Working agreements", body: "Rules a team sets for itself, such as a first review within 24 hours or pull requests under 400 lines. Each merged pull request that broke one is listed, with its value.", doc: "methods.md" }} />}
      action={<Button size="sm" variant="plain" href="#/settings?module=agreements" iconEnd="right">Set agreements</Button>}>
      {ag ? <>
        <Stats>{Object.entries(ag.labels).map(([rule, label]) => <Stat label={label} value={ag.counts[rule] ?? 0} note={`broken in ${ag.window_days} days, of ${ag.merged} merged`} />)}</Stats>
        <Framed title="Exceptions" note="merged pull requests that broke an agreement, with the value they had"><Table name="agreement-exceptions" caption="Agreement exceptions" rows={ag.exceptions.map((x) => ({ ...x, label: ag.labels[x.rule] || x.rule }))} columns={[
          { key: "pr", label: "Pull request", primary: true, render: (x) => <a href={gh(`/pull/${x.pr}`)} target="_blank" rel="noopener noreferrer">#{x.pr}</a> },
          { key: "label", label: "Agreement", filter: true },
          { key: "value", label: "Was", num: true, render: (x) => (x.value == null || x.value === true ? "–" : `${x.value}${UNITS[x.rule] || ""}`) },
          { key: "open", label: "Now", raw: (x) => (x.open ? "still open" : "merged") }]}
          empty={<Card><EmptyState icon="check" title="No agreement broken in this window." /></Card>} /></Framed>
        {Object.keys(ag.weekly || {}).length ? <div class="pr-weeks blk-grid">{Object.entries(ag.weekly || {}).map(([rule, weeks]) => <Panel title={ag.labels[rule] || rule}
          state={<span class="muted">broken, per week</span>}>
          {weeks.some((x) => x[1]) ? <BarChart label={`${ag.labels[rule] || rule}: pull requests that broke it, per week`} height={150}
            bars={weeks.map(([w, n]) => ({ label: dateLabel(w), value: n, tone: n ? "watch" as const : "neutral" as const }))} />
            : <p class="blk-note">Nobody broke it in the last {weeks.length} weeks.</p>}
        </Panel>)}</div> : null}
      </> : <Card><EmptyState icon="settings" title="No working agreements set." action={<Button variant="tinted" href="#/settings?module=agreements">Set agreements</Button>}>
        A team sets its own rules (first review within 24 hours, pull requests under 400 lines, a review before every merge) in Settings or under <code>[agreements]</code> in <code>.github/stackvitals.toml</code>.</EmptyState></Card>}
    </Section>

    <Section title="Review stages" description="Where review time goes, for insiders and outside contributors side by side.">
      {!Object.keys(st).length ? <Card><EmptyState icon="clock" title="No review stages measured yet.">They show once pull requests get reviewed and merged.</EmptyState></Card> : null}
      {Object.keys(st).length ? <Framed title="By stage" note="every reviewed pull request in the window"><Table name="stages" caption="Review stages" search={false} rows={Object.entries(st).map(([k, v]) => ({ k, ...v }))} columns={[
        { key: "k", label: "Stage", primary: true, raw: (s) => STAGE[s.k] || s.k },
        { key: "median_s", label: "Median", num: true, render: (s) => secs(s.median_s) }, { key: "p90_s", label: "90th percentile", num: true, render: (s) => secs(s.p90_s) },
        { key: "n", label: "PRs", num: true }]} /></Framed> : null}
      {groups.length ? <Framed title="Insiders and outside contributors" note="medians, side by side"><Table name="groups" caption="Insiders and outside contributors" search={false} rows={groups.map(([k, g]) => ({ k, ...g }))} columns={[
        { key: "k", label: "Who", primary: true, raw: (g) => (g.k === "outsider" ? "Outside contributors" : g.k === "insider" ? "Insiders" : g.k) },
        { key: "merged", label: "Merged", num: true }, { key: "merge_rate", label: "Merge rate", num: true, render: (g) => pct(g.merge_rate) },
        { key: "pickup", label: "First review", num: true, raw: (g) => g.pickup?.median_s, render: (g) => secs(g.pickup?.median_s) },
        { key: "cycle", label: "Ready to merge", num: true, raw: (g) => g.cycle?.median_s, render: (g) => secs(g.cycle?.median_s) },
        { key: "merged_without_review", label: "No review", num: true }]} /></Framed> : null}
      {(fl.load || []).length ? <Framed title="Open review requests" note="per reviewer, busiest first">
        <Table name="review-load" caption="Open review requests" rows={fl.load!} initialSort={{ key: "open_requests", desc: true }} columns={[
          { key: "reviewer", label: "Reviewer", primary: true }, { key: "open_requests", label: "Open requests", num: true },
          { key: "oldest_since", label: "Oldest asked", render: (r) => (r.oldest_since ? day(r.oldest_since) : "–") }]} /></Framed> : null}
      {fl.baselines && Object.values(fl.baselines).some((v) => v != null) ? <Panel title="What counts as slow here" state={<span class="muted">75th percentile of merged PRs</span>}>
        <Facts rows={[["First review", secs(fl.baselines.pickup)], ["Approved to merged", secs(fl.baselines.merge)], ["The author's answer to a review", secs(fl.baselines.author)]]} />
        <p class="blk-note">A pull request waiting longer than this shows its usual time in Who acts next.</p></Panel> : null}
    </Section>

    <Section title="Who knows what" class="pr-know" description="Each folder's main author and their share of its merged pull requests. An area one person carries needs a second reviewer before they're away.">
      {fl.knowledge ? <Lazy name="Knowledge" k={fl.knowledge} /> : <Card><EmptyState icon="clock" title="Not mapped yet.">The next Team Flow run maps who works on each folder.</EmptyState></Card>}
    </Section>

    {fl.delivery ? <Section title="Releases" description={`From GitHub releases in the last ${fl.window_days ?? 90} days, for repos that don't record deployments. Delivery has the full DORA numbers.`}
      action={<Button size="sm" variant="plain" href="#/delivery" iconEnd="right">Delivery</Button>}><Lazy name="Releases" d={fl.delivery} /></Section> : null}

    {hb ? <Section title="Habits" description={`What merged pull requests carry, ${hb.scope || "whole repo"}, ${hb.merged_prs ?? 0} merged.`}>
      <Stats>
        <Stat label="With tests" value={pct(hb.include?.tests)} />
        <Stat label="With docs" value={pct(hb.include?.docs)} />
        <Stat label="With a changelog entry" value={pct(hb.include?.changelog)} />
        <Stat label="Size, median" value={hb.size?.median_lines != null ? `${hb.size.median_lines} lines` : "–"}
          note={`75th percentile ${hb.size?.p75_lines ?? "–"}, 90th ${hb.size?.p90_lines ?? "–"}`} />
      </Stats>
      {hb.asks?.length ? <Framed title="What maintainers ask for in reviews" note="share of reviewed pull requests where it came up">
        <Table name="review-asks" search={false} rows={hb.asks.map((a) => ({ ...a, id: a.ask }))} initialSort={{ key: "share", desc: true }} columns={[
          { key: "ask", label: "Ask", primary: true }, { key: "share", label: "Reviewed PRs", num: true, render: (a) => pct(a.share) }, { key: "prs", label: "PRs", num: true }]} /></Framed> : null}
    </Section> : null}

    {hb ? <Section title="Before opening a pull request" id="preflight" description="Check a planned change against what merged pull requests here include, or have the workflow post the same check on new outside pull requests.">
      <div class="pr-pre-wrap"><Preflight repo={app.repo} h={hb} known={(fl.knowledge?.areas || []) as R[]} />
        <AutoNote app={app} values={f.settings?.values} /></div>
    </Section> : null}
    {f.pulse?.weeks?.length ? <PulseSection p={f.pulse} /> : <Section title="Team pulse" description="Three questions a week, answered by reaction on the digest issue.">
      <Card><EmptyState icon="community" title="No pulse answers yet." action={<Button variant="tinted" href="#/settings?module=digest">Turn on the digest</Button>}>
        With the weekly digest on, its issue asks the team three yes-or-no questions; only the counts are kept.</EmptyState></Card></Section>}

    <Section title="From your machine" description="A private answer that needs your own token; nothing is written to the repo."><Triage repo={app.repo} /></Section>
  </Page>;
}

// The weekly pulse from the digest issue (core/pulse.py): counts only, a share only with 5 or more answers.
interface PulseWeek { week: string; [question: string]: string | { yes: number; no: number; mixed: number } }
interface PulseFile { weeks: PulseWeek[]; min_answers: number; beside?: Record<string, string> }
const PULSE: [string, string][] = [["flow", "Got work done without waiting on others"], ["friction", "CI and reviews stayed out of the way"],
  ["satisfaction", "Happy with how the team shipped"]];
// The measure pulse.json pairs with each question, and where it lives.
const BESIDE: Record<string, [string, string]> = { pickup: ["Pickup time", "#/prs"], first_try: ["First-try green", "#/ci"], deployments: ["Deployments", "#/delivery"] };
const DEFAULT_BESIDE: Record<string, string> = { flow: "pickup", friction: "first_try", satisfaction: "deployments" };

function PulseSection({ p }: { p: PulseFile }) {
  const min = p.min_answers || 5;
  const share = (w: PulseWeek | undefined, k: string) => {
    const c = w?.[k] as { yes: number; no: number; mixed: number } | undefined;
    const n = c ? c.yes + c.no + c.mixed : 0;
    return { n, s: c && n >= min ? c.yes / n : null };
  };
  const last = p.weeks[p.weeks.length - 1], recent = p.weeks.slice(-4);
  const rows = PULSE.map(([k, label]) => {
    const [beside, href] = BESIDE[(p.beside || DEFAULT_BESIDE)[k] || ""] || [(p.beside || {})[k] || "–", "#/"];
    const now = share(last, k);
    const shown = recent.map((w) => share(w, k)).filter((x) => x.s != null);
    return { k, label, beside, href, n: now.n, now: now.s, avg: shown.length ? shown.reduce((a, x) => a + (x.s as number), 0) / shown.length : null };
  });
  return <Section title="Team pulse" description={`The digest issue's three questions, answered by reaction; week ${last.week}. A share needs ${min} answers.`}>
    <Table name="pulse" caption="Team pulse" search={false} rows={rows} columns={[
      { key: "label", label: "Question", primary: true },
      { key: "now", label: "Yes, last week", num: true, render: (r) => (r.now == null ? (r.n ? `${r.n} answers` : "–") : pct(r.now)) },
      { key: "avg", label: "Yes, last 4 weeks", num: true, render: (r) => (r.avg == null ? "–" : pct(r.avg)) },
      { key: "beside", label: "Read with", render: (r) => <a href={r.href}>{r.beside}</a> }]} />
    <p class="blk-note">StackVitals keeps only the counts; GitHub shows who reacted to anyone who can see the issue. On a public repo only the team's own people count.</p>
  </Section>;
}
