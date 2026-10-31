// Insights: every finding ranked by the hours at stake, with its sample, evidence, age and decision; flaky tests traced
// to the pull requests they held red; and how long ready pull requests sat with a failing check.
import "./insights.css";
import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import type { PageProps } from "../app/routes";
import { BarChart } from "../charts/BarChart";
import { useFiles } from "../data/files";
import { count, day, hours, pct } from "../data/format";
import type { InsightsJson } from "../data/types";
import { Button } from "../ui/Button";
import { EmptyState, InfoButton, PageSkeleton, Pill } from "../ui/bits";
import { Card, Page, Section, Stat, Stats } from "../ui/Page";
import { Table } from "../ui/Table";
import { ChainRow, FindingRow, findingId, goTo, type Chain } from "./insights/parts";

type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
type Ins = Omit<InsightsJson, "chains"> & { chains?: Chain[]; red_ci?: InsightsJson["red_ci"] & { open_red?: { pr: number; since?: string; hours: number }[];
  cycle_hours?: { red?: { median?: number | null; n: number }; clear?: { median?: number | null; n: number } }; measures?: Record<string, R>;
  rerun_jobs?: { workflow: string; job: string; hours: number; prs: number }[]; rerun_tests?: { test: string; hours: number; prs: number; pr_list?: number[] }[];
  top?: { pr: number; hours: number; waits?: { ended_by?: string }[] }[] } };
const ENDED: Record<string, string> = { push: "a new commit", rerun: "a passing re-run", merged: "the merge", closed: "closing it", open: "still red" };

const STAKE_INFO = { title: "Hours at stake",
  body: "Waiting or outage time each finding causes, estimated from CI and pull request history. Each hour is counted once, so overlapping findings don't add up twice. It is what fixing could win back, not hours proven lost. People are never ranked.",
  doc: "methods.md" };

// One labelled figure in the summary block.
function Cell({ label, value, note }: { label: string; value: ComponentChildren; note?: ComponentChildren }) {
  return <div class="ins-cell"><dt class="ins-cell-k">{label}</dt><dd class="ins-cell-v num">{value}</dd>{note ? <dd class="ins-cell-note">{note}</dd> : null}</div>;
}

// A table with its own visible heading on the frame (no second caption).
function Titled({ title, note, children }: { title: string; note?: string; children: ComponentChildren }) {
  return <div class="ins-tbl"><div class="ins-tbl-h"><h3>{title}</h3>{note ? <span class="ins-tbl-note">{note}</span> : null}</div>{children}</div>;
}

const prLink = (repo: string, n: number) => <a href={`https://github.com/${repo}/pull/${n}`} target="_blank" rel="noopener noreferrer">#{n}</a>;

export default function Insights({ app }: PageProps) {
  const f = useFiles<{ ins: Ins }>({ ins: "insights.json" });
  const [at, setAt] = useState<number | null>(null);
  const title = "Insights", sub = "What to fix first, ranked by the estimated hours of waiting or outage at stake. People are never ranked.";
  if (!app) return <Page title={title} subtitle={sub}><EmptyState icon="setup" title="No StackVitals data here yet" action={<Button variant="filled" href="#/setup">Set it up</Button>} /></Page>;
  if (!f.ready) return <PageSkeleton />;
  const ins = f.ins;
  if (!ins) return <Page title={title} subtitle={sub}><EmptyState icon="insights" title="Insights haven't run here yet.">They join CI Health and Pull Requests history after each run.</EmptyState></Page>;
  const found = ins.findings || [];
  const open = found.filter((x) => !x.decision), aside = found.filter((x) => x.decision);
  const opp = ins.opportunity, tr = ins.track_record, red = ins.red_ci;
  const total = opp?.hours ?? open.reduce((s, x) => s + x.hours, 0);
  const pick = at === null ? null : open[at];
  const chains = ins.chains || [];
  const openRed = red?.open_red || [];
  const inside = opp?.inside_another ?? 0;
  const first = open[0];
  return <Page title={title} subtitle={sub}
    toolbar={app.modules?.insights?.page ? <Button variant="plain" href={app.modules.insights.page} iconEnd="external">Printable page</Button> : null}>

    <Section title="Summary" description="What fixing the open findings could win back, and how earlier top findings turned out." info={<InfoButton info={STAKE_INFO} />}>
      <div class="ins-sum card">
        <div class="ins-sum-top">
          <div class="ins-head">
            <p class="ins-k">Could be won back</p>
            <p class="ins-big num">{Math.round(total)}<small>hours</small></p>
            <p class="ins-dim">Estimated waiting or outage time across the open findings.</p>
          </div>
          <dl class="ins-cells">
            <Cell label="Open findings" value={open.length} note={open.length ? "ranked below by hours" : "nothing to fix now"} />
            <Cell label="Counted once" value={inside ? `${inside} overlap` : "Yes"} note={inside ? `${count(inside, "flaky-CI finding")} inside the red-check hours, not added twice` : "no hour is added twice"} />
          </dl>
        </div>
        {tr?.top_findings ? <div class="ins-track">
          <p class="ins-k">Track record <span class="ins-dim">since {day(tr.since)}</span></p>
          <dl class="ins-cells">
            <Cell label="Ranked first" value={tr.top_findings} note="findings at the top of this list" />
            <Cell label="Shrank by half" value={tr.shrank_by_half} note="later at half the hours or less" />
            <Cell label="Cleared" value={tr.cleared} note="not seen for a week" />
          </dl>
        </div> : null}
        <div class="ins-first">
          <p class="ins-k">Fix this first</p>
          {first ? <p class="ins-first-v">
            <button type="button" class="ins-link" onClick={() => goTo(findingId(1))}>{first.title}</button>
            <span class="ins-dim num"> · {hours(first.hours)} at stake, the most of any finding</span></p>
            : <p class="ins-first-v ins-dim">Nothing open. Findings appear when CI and pull request history show hours worth winning back.</p>}
        </div>
        {open.length > 1 ? <div class="ins-bars">
          <p class="ins-k">Hours by finding <span class="ins-dim">pick a bar to read it</span></p>
          <BarChart label="Hours at stake by finding" kind="hours" height={180} onPick={setAt}
            bars={open.map((x, i) => ({ label: `#${i + 1}`, value: x.hours, tone: x.structural ? "watch" : "accent" }))} />
          <p class="ins-pick" aria-live="polite">{pick ? <>
            <b class="num">#{(at ?? 0) + 1}</b> {pick.title} <span class="ins-dim num">· {hours(pick.hours)}</span>{" "}
            <button type="button" class="ins-link" onClick={() => goTo(findingId((at ?? 0) + 1))}>Go to it</button></> : <span class="ins-dim">No bar picked.</span>}</p>
        </div> : null}
      </div>
    </Section>

    <Section title="What to fix first" description="Biggest wait first. Decide in one click: snooze for a while or acknowledge for good."
      action={<Pill tone={open.length ? "watch" : "good"} icon={null}>{count(open.length, "open finding")}</Pill>}>
      {open.length ? <ol class="ins-list">{open.map((x, i) => <FindingRow app={app} f={x} rank={i + 1} />)}</ol>
        : <Card><EmptyState icon="check" title="Nothing stands out.">Findings appear when CI and pull request history show hours worth winning back.</EmptyState></Card>}
    </Section>

    {aside.length ? <Section title="Acknowledged or snoozed" description="Off the list until the decision ends or someone reopens it."
      action={<Pill tone="neutral" icon={null}>{count(aside.length, "decided finding")}</Pill>}>
      <ol class="ins-list">{aside.map((x) => <FindingRow app={app} f={x} rank={null} />)}</ol>
    </Section> : null}

    {chains.length ? <Section title="From flaky test to decision" description="Tests whose failures held merged pull requests red until a re-run passed, traced to an owner and a decision.">
      <ul class="ins-chains">{chains.map((c) => <ChainRow app={app} c={c} />)}</ul>
    </Section> : null}

    {red ? <Section title="Red checks on pull requests" description="How long ready pull requests sat with a failing check."
      info={red.definition ? <InfoButton info={{ title: "Red checks", body: red.definition, doc: "methods.md" }} /> : null}>
      {red.prs ? <Stats>
        <Stat label="Merged PRs that sat red" value={`${red.red_prs} of ${red.prs}`} note={`${pct(red.prs ? red.red_prs / red.prs : null)} of merged PRs`} />
        <Stat label="Hours red in all" value={hours(red.red_hours_total)} note="across the merged PRs" />
        <Stat label="Cleared only by a re-run" value={hours(red.rerun_hours_total)} note={count(red.rerun_waits, "wait")} />
        <Stat label="Merged without any check" value={red.without_checks} note="merged PRs" />
        {red.cycle_hours?.red?.median != null ? <Stat label="Ready to merge, red PRs" value={hours(red.cycle_hours.red.median)}
          note={red.cycle_hours.clear?.median != null ? `vs ${hours(red.cycle_hours.clear.median)} for PRs never red (n = ${red.cycle_hours.red.n} and ${red.cycle_hours.clear.n})` : `n = ${red.cycle_hours.red.n}`} /> : null}
      </Stats> : <Card><EmptyState icon="prs" title="No merged pull request to measure yet.">Hours red show once ready pull requests merge.</EmptyState></Card>}
      {red.measures?.["insight.red_ci_share"]?.low != null ? <p class="ins-range">The share of merged pull requests that sat red is likely between {pct(red.measures["insight.red_ci_share"].low)} and {pct(red.measures["insight.red_ci_share"].high)} (n = {red.measures["insight.red_ci_share"].n}).</p> : null}
      {red.rerun_jobs?.length ? <Titled title="Jobs a re-run cleared" note="sorted by hours red"><Table name="rerun-jobs" search={false} rows={red.rerun_jobs} initialSort={{ key: "hours", desc: true }} columns={[
        { key: "job", label: "Job", primary: true },
        { key: "workflow", label: "Workflow" },
        { key: "hours", label: "Hours red", num: true, render: (j) => hours(j.hours) },
        { key: "prs", label: "Pull requests", num: true }]} /></Titled> : null}
      {red.rerun_tests?.length ? <Titled title="Tests a re-run cleared" note="sorted by hours red"><Table name="rerun-tests" search={false} rows={red.rerun_tests} initialSort={{ key: "hours", desc: true }} columns={[
        { key: "test", label: "Test", primary: true, render: (t) => <a class="mono-soft" href={`#/ci/test/${encodeURIComponent(t.test)}`}>{t.test}</a> },
        { key: "hours", label: "Hours red", num: true, render: (t) => hours(t.hours) },
        { key: "prs", label: "Pull requests", num: true },
        { key: "list", label: "Which", raw: (t) => (t.pr_list || []).join(" "), render: (t) => t.pr_list?.length ? <span class="ins-prs">{t.pr_list.map((n, i) => <>{i ? ", " : ""}{prLink(app.repo, n)}</>)}</span> : "–" }]} /></Titled> : null}
      {red.top?.length ? <Titled title="Merged pull requests red the longest"><Table name="red-top" search={false} rows={red.top} initialSort={{ key: "hours", desc: true }} columns={[
        { key: "pr", label: "Pull request", primary: true, render: (t) => prLink(app.repo, t.pr) },
        { key: "hours", label: "Hours red", num: true, render: (t) => hours(t.hours) },
        { key: "waits", label: "Times it went red", num: true, raw: (t) => (t.waits || []).length },
        { key: "end", label: "Last cleared by", raw: (t) => ENDED[(t.waits || []).slice(-1)[0]?.ended_by || ""] || "–" }]} /></Titled> : null}
      {openRed.length ? <Titled title="Open and red right now"><Table name="open-red" search={false} rows={openRed} initialSort={{ key: "hours", desc: true }} columns={[
        { key: "pr", label: "Pull request", primary: true, render: (p) => prLink(app.repo, p.pr) },
        { key: "since", label: "Red since", raw: (p) => day(p.since) },
        { key: "hours", label: "Hours red", num: true, render: (p) => hours(p.hours) }]} /></Titled> : null}
    </Section> : null}
  </Page>;
}
