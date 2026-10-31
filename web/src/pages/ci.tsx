// CI Health: the weekly trends as a scrub chart with a watchlist, the key numbers, this week against the four before,
// what is flaky or failing (decide in a click), failure groups, the slowest, new and skipped tests, coverage, cost,
// quarantine, test impact, a builder that sets the CI commands up in a workflow, and a page per test or job.
import "./ci.css";
import { useEffect, useState } from "preact/hooks";
import { useJump } from "../app/jump";
import type { PageProps } from "../app/routes";
import { navigate, withQuery, type Route } from "../app/router";
import { MetricHero, Watchlist, metricItem, trendTones, useRange } from "../charts/MetricHero";
import { Sparkline } from "../charts/Sparkline";
import type { Metric } from "../charts/metric";
import { inForce, useFiles } from "../data/files";
import { ago, dateLabel, day, pct, secs, short } from "../data/format";
import type { AppJson, CiItem, CiJson, Coverage as Cov, Decision, DecisionsJson } from "../data/types";
import { target } from "../data/write";
import { Commands, Decide } from "../features/Decide";
import { EvidenceLink, type DoraEvidence } from "../features/Evidence";
import { ciMetrics, jobId } from "../features/vitals";
import { Button, safeHref } from "../ui/Button";
import { CopyButton, EmptyState, Pill, PageSkeleton, Skeleton, StatePill } from "../ui/bits";
import { SegmentedControl } from "../ui/controls";
import { Icon } from "../ui/icons";
import { Card, Columns, Page, Section, Stat, Stats } from "../ui/Page";
import { Table, type Column } from "../ui/Table";
import { Facts, Feedback, Framed, Panel, ThisWeek, jump } from "./ci/parts";

const gh = (app: AppJson, path: string) => `https://github.com/${app.repo}${path}`;
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const decisionText = (d: Decision | null | undefined) => (d ? `${cap(d.verb)} by ${d.by}${d.until ? ` until ${d.until}` : ""}${d.reason ? `: ${d.reason}` : ""}` : null);
// Decisions made since the CI file was written (or kept only in decisions.json) count too, as on Overview.
function withDecisions(ci: CiJson | null, dec: DecisionsJson | null): CiJson | null {
  const state = dec?.state || {};
  if (!ci || !Object.keys(state).length) return ci;
  const pick = (k: string, d?: Decision | null) => (inForce(state[k]) ? state[k]! : d && inForce(d) ? d : null);
  return { ...ci, tests: (ci.tests || []).map((t) => ({ ...t, decision: pick(`test:${t.id}`, t.decision) })),
    jobs: (ci.jobs || []).map((j) => ({ ...j, decision: pick(`job:${jobId(j)}`, j.decision) })) };
}
// Quarantine, test impact, signals, causes and the CI setup builder load with their own module.
type More = typeof import("./ci/more");
let more: Promise<More> | null = null;
function Lazy({ name, ...p }: { name: "Began" | "Quarantine" | "Impact" | "Signals" | "Causes" | "Setup" } & R) {
  const [m, setM] = useState<More | null>(null);
  useEffect(() => { (more ||= import("./ci/more")).then(setM); }, []);
  if (!m) return name === "Signals" || name === "Causes" ? null : <Skeleton lines={3} />;
  const C = m[name] as (x: R) => preact.JSX.Element | null;
  return <C {...p} />;
}
const KIND_NOTE: Record<string, string> = { timing: "a wait or timeout ran out", network: "a host didn't answer", infrastructure: "the runner itself", concurrency: "a race between threads",
  "async wait": "checked before it was ready", "shared state": "left over from another test", randomness: "a random seed", ordering: "an order that isn't guaranteed",
  time: "time zones or the clock", "resource leak": "files or sockets left open", io: "a file on disk", "floating point": "numeric rounding" };
const STATE_ORDER: Record<string, number> = { broken: 0, flaky: 1, suspect: 2, fixed: 3, ok: 4 };

type Row = CiItem & { kind: "test" | "job"; name: string; href: string };
type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

async function historyPage(kind: string, ident: string): Promise<string | null> {
  // The static history page's name: a slug plus the first 8 hex of SHA-1, as the Action names it.
  const slug = ident.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(-60).replace(/^-+|-+$/g, "");
  try {
    const hash = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(ident));
    const hex = [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 8);
    return `history/${kind}-${slug}-${hex}.html`;
  } catch {
    return null;
  }
}

function Item({ app, ci, kind, id }: { app: AppJson; ci: CiJson; kind: "test" | "job"; id: string }) {
  const item = kind === "test" ? (ci.tests || []).find((t) => t.id === id) : (ci.jobs || []).find((j) => jobId(j) === id);
  const [history, setHistory] = useState<string | null>(null);
  const [cmds, setCmds] = useState(false);
  useEffect(() => {
    if (item) historyPage(kind, kind === "test" ? item.id! : `${item.workflow}|${item.job}`).then(setHistory);
  }, [id]);
  if (!item) return <Page title="Not found" subtitle={`No ${kind} called ${id} in the last ${ci.window_days} days.`}>
    <EmptyState icon="search" title="Nothing by that name" action={<Button variant="filled" href="#/ci">Back to CI Health</Button>} /></Page>;
  const x = item as R;
  const what = target(kind, kind === "test" ? item.id! : id);
  const runs = (item.evidence || []).map((e) => ({ ...e, url: gh(app, `/actions/runs/${e.run}/attempts/${e.att}`) }));
  const d = item.decision;
  const why = [
    !!item.monitors?.length && ["Monitors", cap(item.monitors.join(", ").replace(/_/g, " "))],
    !!item.labels?.length && ["Labels", cap(item.labels.join(", ").replace(/_/g, " "))],
    !!item.message && ["Fails with", <code class="code-inline">{item.message}</code>],
    !!item.top_step && ["Most failing step", item.top_step],
    x.flake_steps?.length > 1 && ["Steps it failed in", x.flake_steps.join(", ")],
    !!x.flake && ["Looks like", <>{cap(x.flake)} <span class="muted">({KIND_NOTE[x.flake] || "from its usual error"})</span></>],
    !!item.owners?.length && ["Owners", item.owners.join(", ")],
    !!item.workflow && ["Workflow", <span class="mono-soft">{item.workflow}</span>],
  ] as ([string, preact.ComponentChildren] | false)[];
  return <Page title={id} subtitle={`${kind === "test" ? "Test" : "Job"} in ${item.workflow || "?"}, last ${ci.window_days} days.`}
    toolbar={<><Button variant="plain" icon="left" href="#/ci">CI Health</Button>
      {history && item.state !== "ok" ? <Button variant="tinted" href={history} iconEnd="external">Week by week</Button> : null}</>}>
    <Section title="At a glance" class="ci-glance">
      <Stats>
        <Stat label="State" value={<StatePill value={item.state} />} />
        {item.state === "broken" ? <Stat label="Failed" value={`${item.failures ?? "–"} of ${item.runs}`} note="runs, the same code failing again" /> : null}
        {item.flake_events ? <>
          <Stat label="Flaked" value={`${item.flake_events} of ${item.runs}`} note="runs" />
          <Stat label="Flake rate" value={pct(item.flake_rate)} note={`likely ${pct(item.rate_low)} to ${pct(item.rate_high)}`} />
          <Stat label="Last flake" value={day(item.last_flake)} note={ago(item.last_flake)} />
          {Object.keys(item.variants || {}).length ? <Stat label="Flakes came from" value={Object.keys(item.variants || {})[0]}
            note={Object.entries(item.variants || {}).map(([k, n]) => `${k}: ${n}`).join(", ")} /> : null}</> : null}
        {item.since ? <Stat label="In this state since" value={day(item.since)} /> : null}
        {x.muted_until ? <Stat label="No alerts until" value={x.muted_until >= "9999" ? "reopened" : day(x.muted_until)} note="still measured" /> : null}
        {item.retry_minutes !== undefined ? <Stat label="Lost to re-runs" value={`${Math.round(item.retry_minutes)} min`} /> : null}
        {item.prs_affected?.length ? <Stat label="Pull requests hit" value={item.prs_affected.length} /> : null}
      </Stats>
    </Section>
    <Section title="Why it is marked and what to do" description="What marks it, then the decision on it; the workflow applies a decision and logs who, when and why.">
      <div class="ci-pair">
        <Panel title="Why it is marked" state={<StatePill value={item.state} />}>
          {why.some(Boolean) ? <Facts rows={why} /> : <p class="ci-say"><span class="sv-mark sv-mark-good" aria-hidden="true" />Nothing marks it right now.</p>}
        </Panel>
        <Panel title="Decision" state={d ? <Pill tone="accent" icon="check">{cap(d.verb)}</Pill> : <Pill tone="neutral" icon={null}>None yet</Pill>}
          bar={<><Decide app={app} kind={kind} id={kind === "test" ? item.id! : id} label="Make a decision"
            verbs={kind === "test" ? ["quarantine", "mute", "acknowledge", "unquarantine", "unmute", "reopen", "confirm", "dispute"] : ["mute", "acknowledge", "unmute", "reopen", "confirm", "dispute"]} />
            <Button size="sm" variant="plain" expanded={cmds} onClick={() => setCmds(!cmds)} iconEnd={cmds ? "up" : "down"}>As a comment</Button></>}>
          {d ? <Facts rows={[["What", cap(d.verb)], ["Who", d.by || "–"], ["Until", d.until ? day(d.until) : "Reopened by hand"], ["Why", d.reason || "No reason given"],
            !!d.at && ["Decided", day(d.at)]]} />
            : <p class="ci-say">Quarantine it so it can't fail builds, mute its alerts for a while, or acknowledge it for good.</p>}
          {cmds ? <div class="ci-cmds"><p class="muted small">Type one of these in any issue or pull request comment:</p><Commands list={[
            ...(kind === "test" ? [{ text: `/stackvitals quarantine ${what} for 14d because `, note: "Your test command passes while only quarantined tests fail." }] : []),
            { text: `/stackvitals mute ${what} for 7d because `, note: "Still measured; no alert and no new issue." },
            { text: `/stackvitals acknowledge ${what} because `, note: "The team lives with it until someone reopens it." },
            { text: `/stackvitals dispute ${what} because `, note: "StackVitals called this wrong: it counts against its accuracy here and changes nothing else." },
          ]} /></div> : null}
        </Panel>
      </div>
    </Section>
    {x.began ? <Section title="When it began" description="Runs before its first flake against runs since, so you can tell whether a change started it.">
      <Lazy name="Began" b={x.began} app={app} /></Section> : null}
    <Section title="Evidence" description="Each run where it failed and then passed, or flipped on the same code.">
      <Framed title="Evidence runs" note={`${runs.length} run${runs.length === 1 ? "" : "s"}`}>
        <Table name="evidence" caption="Evidence runs" rows={runs} columns={[
          { key: "run", label: "Run", primary: true, render: (r) => <a href={safeHref(r.url)} target="_blank" rel="noopener noreferrer">{r.run}</a> },
          { key: "att", label: "Attempt", num: true },
          { key: "kind", label: "What happened", raw: (r) => (r.kind === "retry" ? "Failed, then passed on a re-run" : r.kind === "flip" ? "Passed and failed on the same code" : r.kind) }]}
          empty={<Card><EmptyState icon="search" title="No runs kept for this one." /></Card>} />
      </Framed>
    </Section>
  </Page>;
}

function Coverage({ app, cov, days }: { app: AppJson; cov: Cov | null | undefined; days: number }) {
  const [ranges, setRange] = useRange();
  if (!cov) return <Card><EmptyState icon="ci" title="No coverage reports found.">Upload Cobertura (coverage.xml), LCOV (lcov.info) or JaCoCo XML in an artifact whose name says coverage; each run's total and each pull request's patch coverage show here.</EmptyState></Card>;
  const l = cov.latest;
  const metric: Metric = { id: "coverage", name: "Line coverage", sub: "Default branch, daily", kind: "share", better: "up", period: "day",
    points: (cov.trend || []).map(([d, v]) => ({ label: dateLabel(d), value: v })), meaning: (v) => `${pct(v)} of lines ran in the default branch's tests.` };
  return <>
    <Stats>
      <Stat label="Line coverage, default branch" value={l ? pct(l.pct) : "–"} note={l ? `${l.covered} of ${l.lines} lines, ${day(l.at)}` : "no default-branch report yet"} />
      <Stat label={`Change, last ${days} days`} value={cov.change === null || cov.change === undefined ? "–" : `${cov.change >= 0 ? "+" : ""}${(cov.change * 100).toFixed(1)} pts`} />
      <Stat label="Pull requests measured" value={(cov.prs || []).length} note="patch coverage: added lines that ran" />
    </Stats>
    {metric.points.length ? <Card><MetricHero metric={metric} ranges={ranges} setRange={setRange} height={240} /></Card> : null}
    <Framed title="Patch coverage by pull request" note="Added lines that ran in the pull request's tests.">
      <Table name="patch-coverage" caption="Patch coverage by pull request" rows={cov.prs || []} columns={[
        { key: "pr", label: "Pull request", primary: true, render: (p) => <a href={gh(app, `/pull/${p.pr}`)} target="_blank" rel="noopener noreferrer">#{p.pr}</a> },
        { key: "pct", label: "Added lines that ran", num: true, render: (p) => (p.lines ? pct(p.pct) : "–") },
        { key: "lines", label: "Lines", num: true, render: (p) => (p.lines ? `${p.covered} of ${p.lines}` : "no code lines") },
        { key: "missed", label: "Not run", raw: (p) => Object.keys(p.missed || {}).length, render: (p) => (Object.keys(p.missed || {}).length ? <ul class="ci-cell-list">{Object.entries(p.missed || {}).slice(0, 3)
          .map(([file, ls]) => <li><span class="mono-soft">{short(file, 60)}</span> <span class="muted">lines {ls.slice(0, 8).join(", ")}{ls.length > 8 ? "…" : ""}</span></li>)}</ul> : "–") },
        { key: "at", label: "Measured", render: (p) => ago(p.at) }]}
        empty={<Card><EmptyState icon="prs" title="No pull request has a coverage report yet." /></Card>} />
    </Framed>
  </>;
}

const TABS = ["flaky", "groups", "all", "slow", "inventory", "coverage"] as const;
type Tab = (typeof TABS)[number];

export default function CI({ app, route }: PageProps) {
  useJump();
  const f = useFiles<{ ci: CiJson; dec: DecisionsJson }>({ ci: "data.json", dec: "decisions.json" });
  const [ranges, setRange] = useRange();
  const [pick, setPick] = useState<string | null>(null);
  if (!app) return <Page title="CI Health" subtitle="Flaky and failing tests and jobs."><EmptyState icon="setup" title="No StackVitals data here yet" action={<Button variant="filled" href="#/setup">Set it up</Button>} /></Page>;
  if (!f.ready) return <PageSkeleton />;
  const ci = withDecisions(f.ci, f.dec);
  if (!ci) return <Page title="CI Health" subtitle="Flaky and failing tests and jobs, first-try green and time to green.">
    <EmptyState icon="ci" title="CI Health hasn't run here yet." action={<Button variant="filled" href="#/settings" icon="settings">Turn it on</Button>}>Add <code>ci</code> to the workflow's modules; the next run fills this page.</EmptyState></Page>;
  if (route.rest[0] === "test" || route.rest[0] === "job") return <Item app={app} ci={ci} kind={route.rest[0]} id={route.rest.slice(1).join("/")} />;
  return <CiMain app={app} ci={ci} route={route} ranges={ranges} setRange={setRange} pick={pick} setPick={setPick} />;
}

const nameCell = (r: Row) => <><a href={r.href} class="ci-id">{short(r.name, 90)}</a>{r.decision ? <div class="ci-dec"><span class="sv-mark sv-mark-accent" aria-hidden="true" />{decisionText(r.decision)}</div> : null}</>;

function CiMain({ app, ci, route, ranges, setRange, pick, setPick }: { app: AppJson; ci: CiJson; route: Route; ranges: Record<string, number>;
  setRange: (p: string, n: number) => void; pick: string | null; setPick: (id: string) => void }) {
  const tab = (TABS as readonly string[]).includes(route.query.get("tab") || "") ? route.query.get("tab") as Tab : "flaky";
  const items: Row[] = [
    ...(ci.tests || []).map((t) => ({ ...t, kind: "test" as const, name: t.id!, href: `#/ci/test/${encodeURIComponent(t.id!)}` })),
    ...(ci.jobs || []).map((j) => ({ ...j, kind: "job" as const, name: jobId(j), href: `#/ci/job/${encodeURIComponent(jobId(j))}` })),
  ];
  const bad = items.filter((i) => i.state !== "ok" && i.state !== undefined).sort((a, b) =>
    (STATE_ORDER[a.state!] ?? 9) - (STATE_ORDER[b.state!] ?? 9) || (b.flake_events || 0) - (a.flake_events || 0));
  const metrics = ciMetrics(ci).filter((m) => m.points.length);
  const metric = metrics.find((m) => m.id === pick) || metrics[0];
  const minutes = Object.entries(ci.minutes || {});
  const expired: string[] = (ci as R).quarantine_expired || [];
  const columns: Column<Row>[] = [
    { key: "state", label: "State", filter: true, render: (r) => <StatePill value={r.state} /> },
    { key: "kind", label: "Kind", filter: true, render: (r) => cap(r.kind) },
    { key: "name", label: "Name", primary: true, render: nameCell },
    { key: "flake_events", label: "Flakes", num: true },
    { key: "flake", label: "Likely cause", filter: true, raw: (r) => (r as R).flake || "", render: (r) => ((r as R).flake ? <span title={KIND_NOTE[(r as R).flake]}>{cap((r as R).flake)}</span> : "–") },
    { key: "runs", label: "Runs", num: true },
    { key: "flake_rate", label: "Rate", num: true, render: (r) => pct(r.flake_rate) },
    { key: "last_flake", label: "Last seen", raw: (r) => r.last_flake || "", render: (r) => (r.last_flake ? ago(r.last_flake) : "–") },
  ];
  const decideCol: Column<Row> = { key: "decide", label: "Action", nowrap: true, raw: () => "", render: (r) => (r.state === "flaky" || r.state === "broken") && !r.decision
    ? <Decide app={app} kind={r.kind} id={r.name} verbs={r.kind === "test" ? ["quarantine", "mute", "acknowledge"] : ["mute", "acknowledge"]} />
    : <Button size="sm" variant="plain" href={r.href} iconEnd="right">Open</Button> };
  const counts: Record<Tab, number | null> = { flaky: bad.length, groups: (ci.failure_groups || []).length, all: items.length, slow: (ci.slow_tests || []).length,
    inventory: (ci.new_tests || []).length + (ci.skipped_tests || []).length, coverage: null };
  const LABEL: Record<Tab, string> = { flaky: "Flaky and failing", groups: "Failure groups", all: "Everything", slow: "Slowest", inventory: "New and skipped", coverage: "Coverage" };
  return <Page title="CI Health" subtitle={`Flaky and failing tests and jobs over the last ${ci.window_days} days, from ${(ci.runs ?? 0).toLocaleString("en-US")} runs. A flake failed and then passed with no code change.`}
    toolbar={<>{app.modules?.ci?.page ? <Button variant="plain" href={app.modules.ci.page} iconEnd="external">Printable page</Button> : null}
      <Button variant="tinted" onClick={() => jump("ci-setup")} iconEnd="down">Set up in your CI</Button></>}>
    {expired.length ? <div class="note note-watch"><Icon name="warn" /><span>{expired.length} flaky test{expired.length === 1 ? "" : "s"} stayed in quarantine past the limit you set and fail builds again until fixed: {expired.slice(0, 5).join(", ")}{expired.length > 5 ? " and more" : ""}.</span></div> : null}
    {metric ? <Section title="Trends" description="Week by week. Drag across the chart, or focus it and use the arrow keys.">
      <Columns ratio="lead">
        <Card><MetricHero metric={metric} ranges={ranges} setRange={setRange} /></Card>
        <Watchlist label="CI metrics" items={metrics.map((m) => metricItem(m, ranges[m.period] || 12))} selected={metric.id} onSelect={setPick} tones={trendTones(metrics, ranges)} />
      </Columns>
    </Section> : null}

    <Section title="Key numbers" description={`Last ${ci.window_days} days, and the runs left out of the flake counts.`}>
      <Stats>
        <Stat label="Green on the first try" value={pct(ci.pushes?.first_try_share)} note={ci.pushes ? <>{`${ci.pushes.pushes} pushes${ci.pushes.first_try_range ? `, likely ${pct(ci.pushes.first_try_range[0])} to ${pct(ci.pushes.first_try_range[1])}` : ""}`}<br /><EvidenceLink kind="not_first_try" ev={ci.pushes as DoraEvidence} repo={app?.repo} /></> : null} />
        <Stat label="Push to all checks done" value={secs(ci.pushes?.median_s)} note={ci.pushes ? `${ci.pushes.median_range_s ? `likely ${secs(ci.pushes.median_range_s[0])} to ${secs(ci.pushes.median_range_s[1])}; ` : ""}90th percentile ${secs(ci.pushes.p90_s)}` : null} />
        <Stat label="Runs re-run" value={pct(ci.rerun_share)} />
        <Stat label="Queue wait" value={secs(ci.queue?.median_s)} note={ci.queue ? `95th percentile ${secs(ci.queue.p95_s)}` : null} />
        <Stat label="Runner minutes" value={minutes.reduce((a, [, b]) => a + b, 0).toLocaleString("en-US")} note={`${ci.window_days} days${minutes.filter(([, v]) => v).length ? `: ${minutes.filter(([, v]) => v).map(([k, v]) => `${k} ${v}`).join(", ")}` : ""}`} />
      </Stats>
      <Lazy name="Signals" ci={ci} />
    </Section>

    {ci.changes || ci.verdict_feedback ? <Section title="This week" description="Against the four weeks before, and how often your team agreed with the calls.">
      {ci.changes ? <ThisWeek changes={ci.changes} /> : null}
      {ci.verdict_feedback ? <Feedback fb={ci.verdict_feedback} /> : null}
    </Section> : null}

    <Section title="Tests and jobs" description={bad.some((b) => b.state === "flaky") ? `Decide on a flaky item here, from its page, or with /stackvitals in any comment. ${bad.filter((b) => b.decision).length} decided.` : "Everything CI ran, grouped the ways you'll look for it."}>
      <div class="tabs-row">
        <SegmentedControl<Tab> label="Show" scroll value={tab} onChange={(v) => navigate(withQuery(route, "tab", v === "flaky" ? null : v))}
          options={TABS.map((t) => ({ value: t, label: <>{LABEL[t]}{counts[t] !== null ? <span class="seg-count num">{counts[t]}</span> : null}</> , aria: `${LABEL[t]}${counts[t] !== null ? `, ${counts[t]}` : ""}` }))} />
      </div>
      <div class="tab-panel" key={tab}>
        {tab === "flaky" ? <>
          <Framed title="Flaky and failing" note="Failing first, then by flakes.">
            <Table name="flaky" caption="Flaky and failing" rows={bad} columns={[...columns, decideCol]}
              empty={<Card><EmptyState icon="check" title="Nothing is flaky or failing.">{ci.has_test_reports ? "" : "Upload test reports (JUnit, CTRF, Jest, Vitest, Go, TRX) as artifacts to see single tests too."}</EmptyState></Card>} />
          </Framed>
          <Lazy name="Causes" rows={bad} />
        </> : null}
        {tab === "all" ? <Framed title="Every test and job" note={`${items.length} in the last ${ci.window_days} days`}><Table name="ci-items" caption="Every test and job" rows={items} columns={columns} /></Framed> : null}
        {tab === "groups" ? <Framed title="Failure groups" note="Failures with the same error and code location.">
          <Table name="failure-groups" caption="Failure groups" rows={ci.failure_groups || []} columns={[
            { key: "type", label: "Error", primary: true }, { key: "where", label: "Where", render: (g) => <span class="mono-soft">{short(g.where, 60)}</span> },
            { key: "message", label: "Message", render: (g) => short(g.message, 100) }, { key: "tests", label: "Tests", num: true },
            { key: "failures", label: "Failures", num: true }, { key: "last", label: "Last", render: (g) => day(g.last) },
            { key: "top_tests", label: "Tests it hits most", raw: (g) => ((g as R).top_tests || []).length, render: (g) => <ul class="ci-cell-list">{((g as R).top_tests || []).slice(0, 3).map((t: string) =>
              <li><a class="mono-soft" href={`#/ci/test/${encodeURIComponent(t)}`}>{short(t, 50)}</a></li>)}</ul> },
            { key: "prompt", label: "For an AI agent", raw: () => "", render: (g) => (g.prompt ? <CopyButton text={g.prompt} label="Copy prompt" small /> : "–") }]}
            empty={<Card><EmptyState icon="check" title="No failures share a cause.">Failures with the same root cause and code location are grouped here.</EmptyState></Card>} />
        </Framed> : null}
        {tab === "slow" ? <>
          <Framed title="Slowest tests" note="Median and 95th percentile time per test.">
            <Table name="slow-tests" caption="Slowest tests" rows={ci.slow_tests || []} initialSort={{ key: "median_ms", desc: true }} columns={[
              { key: "id", label: "Test", primary: true, render: (t) => <a class="ci-id" href={`#/ci/test/${encodeURIComponent(t.id)}`}>{short(t.id, 70)}</a> },
              { key: "median_ms", label: "Median", num: true, render: (t) => secs(t.median_ms / 1000) },
              { key: "p95_ms", label: "95th percentile", num: true, render: (t) => secs(t.p95_ms / 1000) },
              { key: "slower", label: "This week", raw: (t) => t.slower?.pct ?? null, render: (t) => (t.slower ? <Pill tone="watch">{t.slower.pct}% slower</Pill> : "–") },
              { key: "trend", label: "Daily median", raw: () => "", render: (t) => <Sparkline values={(t.trend || []).map((p) => p[1])} label={`Daily median time of ${t.id}`} /> },
              { key: "samples", label: "Samples", num: true }]} />
          </Framed>
          <Framed title="Slowest jobs">
            <Table name="slow-jobs" caption="Slowest jobs" rows={(ci.jobs || []).filter((j) => j.median_s)} initialSort={{ key: "median_s", desc: true }} columns={[
              { key: "job", label: "Job", primary: true, raw: (j) => jobId(j), render: (j) => <a class="ci-id" href={`#/ci/job/${encodeURIComponent(jobId(j))}`}>{jobId(j)}</a> },
              { key: "median_s", label: "Median", num: true, render: (j) => secs(j.median_s) }, { key: "p95_s", label: "95th percentile", num: true, render: (j) => secs(j.p95_s) },
              { key: "slower", label: "This week", raw: (j) => j.slower?.pct ?? null, render: (j) => (j.slower ? <Pill tone="watch">{j.slower.pct}% slower</Pill> : "–") },
              { key: "trend", label: "Daily median", raw: () => "", render: (j) => <Sparkline values={(j.trend || []).map((p) => p[1])} label={`Daily median time of ${jobId(j)}`} /> }]} />
          </Framed>
        </> : null}
        {tab === "inventory" ? <>
          <Framed title="New tests" note="Last 14 days.">
            <Table name="new-tests" caption="New tests" rows={ci.new_tests || []} columns={[
              { key: "state", label: "State", filter: true, render: (t) => <StatePill value={t.state} /> },
              { key: "id", label: "Test", primary: true, render: (t) => <a class="ci-id" href={`#/ci/test/${encodeURIComponent(t.id!)}`}>{short(t.id, 90)}</a> },
              { key: "first", label: "First seen", render: (t) => day(t.first) }, { key: "runs", label: "Runs since", num: true },
              { key: "failures", label: "Failed", num: true }, { key: "flake_events", label: "Flaked", num: true }]}
              empty={<Card><EmptyState icon="ci" title="No new tests in the last 14 days.">{ci.has_test_reports ? "Tests are named here the first time a report shows them." : "Upload test reports (JUnit, CTRF, Jest, Vitest, Go, TRX) as artifacts to track tests."}</EmptyState></Card>} />
          </Framed>
          <Framed title="Skipped on the default branch now" note="Since as far back as the stored reports go.">
            <Table name="skipped-tests" caption="Skipped tests" rows={ci.skipped_tests || []} columns={[
              { key: "id", label: "Test", primary: true, render: (t) => <span class="ci-id">{short(t.id, 90)}</span> },
              { key: "new", label: "Newly skipped", raw: (t) => (t.new ? "yes" : "no"), render: (t) => (t.new ? <Pill tone="watch">Newly skipped</Pill> : "–") },
              { key: "since", label: "Skipped since", render: (t) => day(t.since) }, { key: "days", label: "Days", num: true },
              { key: "suites", label: "Jobs", num: true }]}
              empty={<Card><EmptyState icon="check" title="Nothing is skipped.">Skipped tests are named once a run with this version reads their reports.</EmptyState></Card>} />
          </Framed>
        </> : null}
        {tab === "coverage" ? <Coverage app={app} cov={ci.coverage} days={ci.window_days ?? 30} /> : null}
      </div>
    </Section>
    {(ci as CostCi).cost ? <CostSection c={(ci as CostCi).cost!} /> : null}
    <Lazy name="Quarantine" ci={ci} />
    <Lazy name="Impact" app={app} ci={ci} />
    <Lazy name="Setup" app={app} ci={ci} />
    {ci.benchmark ? <p class="ci-say"><span class="sv-mark sv-mark-neutral" aria-hidden="true" />Compared with similar public repos on the printable page.</p> : null}
  </Page>;
}

// What CI costs (ci/cost.py): billed minutes and money by workflow and job, and what flaky re-runs add.
type CostRow = { workflow?: string; job?: string; minutes: number; usd: number };
interface CostReport { days: number; private: boolean; minutes: number; usd: number; private_usd: number; rerun_minutes: number;
  rerun_usd: number; self_hosted_minutes: number; by_runner?: Record<string, number>; workflows: CostRow[]; jobs: CostRow[]; prices_read: string;
  tests?: { id: string; suite?: string; minutes: number; usd: number; flakes: number; prs: number }[] }
type CostCi = CiJson & { cost?: CostReport };
const usd = (n: number) => `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function CostSection({ c }: { c: CostReport }) {
  const runners = Object.entries(c.by_runner || {}).sort((a, b) => b[1] - a[1]).map(([runner, minutes]) => ({ id: runner, runner, minutes }));
  return <Section title="What CI costs" description={`Last ${c.days} days, at GitHub's published per-minute prices (read ${c.prices_read}); each job rounded up to a whole minute, as GitHub bills it.`}>
    <Stats>
      <Stat label="Billed minutes" value={c.minutes.toLocaleString()} note={c.self_hosted_minutes ? `${c.self_hosted_minutes.toLocaleString()} on self-hosted runners (not priced)` : undefined} />
      <Stat label={c.private ? "Cost" : "Cost (public repo)"} value={usd(c.usd)} note={c.private ? undefined : `standard runners are free here; ${usd(c.private_usd)} on a private repo`} />
      <Stat label="Spent on flaky re-runs" value={`${c.rerun_minutes.toLocaleString()} min`} note={`${usd(c.rerun_usd)}: attempts that failed, then passed when run again`} />
    </Stats>
    <Columns>
      <Framed title="By workflow">
        <Table name="cost-workflows" caption="By workflow" search={false} rows={c.workflows} columns={[
          { key: "workflow", label: "Workflow", primary: true }, { key: "minutes", label: "Minutes", num: true },
          { key: "usd", label: "Cost", num: true, render: (r) => usd(r.usd) }]} />
      </Framed>
      {runners.length ? <Framed title="By runner" note="Minutes">
        <Table name="cost-runners" caption="Minutes by runner" search={false} rows={runners} columns={[
          { key: "runner", label: "Runner", primary: true }, { key: "minutes", label: "Minutes", num: true, render: (r) => r.minutes.toLocaleString() }]} />
      </Framed> : null}
    </Columns>
    <Framed title="Costliest jobs" note="The ten that cost the most.">
      <Table name="cost-jobs" caption="Costliest jobs" search={false} rows={c.jobs.slice(0, 10)} columns={[
        { key: "job", label: "Job", primary: true }, { key: "workflow", label: "Workflow" }, { key: "minutes", label: "Minutes", num: true },
        { key: "usd", label: "Cost", num: true, render: (r) => usd(r.usd) }]} />
    </Framed>
    {c.tests?.length ? <Framed title="What each flaky test cost" note="The attempts it flaked in, shared when several flaked together.">
      <Table name="cost-tests" caption="What each flaky test cost" search={false} rows={c.tests} columns={[
        { key: "id", label: "Test", primary: true, render: (r) => <a class="ci-id" href={`#/ci/test/${encodeURIComponent(r.id)}`}>{r.id}</a> }, { key: "flakes", label: "Flakes", num: true },
        { key: "minutes", label: "Minutes", num: true }, { key: "usd", label: "Cost", num: true, render: (r) => usd(r.usd) },
        { key: "prs", label: "PRs it got in the way of", num: true }]} />
    </Framed> : null}
  </Section>;
}
