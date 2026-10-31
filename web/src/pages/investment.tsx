// Investment: where merged work went each month (feature, fix, maintenance, security, docs), a share chart per kind of
// work, stacked monthly bars with the numbers behind them, how each pull request was sorted, and work by epic or project.
import "./investment.css";
import { useState } from "preact/hooks";
import type { PageProps } from "../app/routes";
import { MetricHero, Watchlist, metricItem, useRange } from "../charts/MetricHero";
import type { Metric } from "../charts/metric";
import { useFiles } from "../data/files";
import { current } from "../data/repos";
import { fetchText } from "../data/source";
import { dateLabel, pct } from "../data/format";
import type { DeliveryJson } from "../data/types";
import { Button } from "../ui/Button";
import { CodeBlock, EmptyState, InfoButton, PageSkeleton, toast } from "../ui/bits";
import { Toggle } from "../ui/controls";
import { Card, Columns, Page, Section } from "../ui/Page";
import { Table } from "../ui/Table";
import { Facts, Framed, Panel } from "./delivery/blocks";

interface Month { month: string; n: number; counts: Record<string, number> }
interface Inv { since: string; months: Month[]; n: number; counts: Record<string, number>; shares: Record<string, number>; decided_by: Record<string, number>; bots: number }
interface Epics { since: string; linked: number; no_epic: number; epics: { epic: string; title?: string | null; prs: number; share: number }[]; feature_share: number }
type D = DeliveryJson & { investment?: Inv | null; epics?: Epics | null };

const CATS: [string, string][] = [["feature", "Feature"], ["fix", "Fix"], ["maintenance", "Maintenance"], ["security", "Security"], ["docs", "Docs"], ["other", "Not sorted"]];
const RULES = `[investment.labels]
feature = ["kind/feature"]
maintenance = ["area: platform"]`;
const HOW: Record<string, string> = { label: "A label", issue: "The linked issue's type", changelog: "A changelog fragment", title: "The title", only: "The files changed", other: "Nothing matched" };
// The order core/investment.py tries the rules in; the first that matches decides.
const ORDER: [string, string][] = [["Your own label rules", "[investment.labels] in .github/stackvitals.toml"], ["A security label", "security, vulnerability"],
  ["The linked Jira or Linear issue's type", "Story, Bug, Task"], ["Common labels", "bug, enhancement, chore, documentation"], ["The title's prefix", "fix:, feat(api):, docs:, Release 2.1"],
  ["A changelog fragment", "news/123.bugfix.rst"], ["The files changed", "only docs, tests, or CI and dependency files"], ["The title's first verb", "Fix, Add, Update"],
  ["The title mentions a fix", "crash, regression, bug"]];
const monthName = (m: string) => `${dateLabel(m)} ${m.slice(0, 4)}`;

// Stacked bars in a fixed category order; tapping a month names its mix underneath.
function Stack({ months }: { months: Month[] }) {
  const [at, setAt] = useState<number | null>(null);
  const max = Math.max(1, ...months.map((m) => m.n));
  const m = months[at ?? months.length - 1];
  return <div>
    <div class="inv-stack" role="listbox" aria-label="Merged pull requests by month and kind of work" tabIndex={0}
      onKeyDown={(e) => { if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return; e.preventDefault(); const d = e.key === "ArrowRight" ? 1 : -1; setAt(Math.max(0, Math.min(months.length - 1, (at ?? months.length - 1) + d))); }}>
      {months.map((x, i) => <div role="option" aria-selected={at === i} class={"inv-col" + (at === i ? " is-on" : "")} onClick={() => setAt(i)} onMouseEnter={() => setAt(i)}
        aria-label={`${monthName(x.month)}: ${x.n} merged; ${CATS.filter(([k]) => x.counts[k]).map(([k, l]) => `${l} ${x.counts[k]}`).join(", ")}`}>
        <span class="inv-n num" aria-hidden="true">{x.n}</span>
        <span class="inv-track" aria-hidden="true"><span class="inv-fill" style={{ height: `${(x.n / max) * 100}%`, animationDelay: `${i * 50}ms` }}>
          {CATS.map(([k]) => (x.counts[k] ? <i class={`inv-c-${k}`} style={{ flexGrow: x.counts[k] }} /> : null))}</span></span>
        <span class="inv-label" aria-hidden="true">{dateLabel(x.month)}</span>
      </div>)}
    </div>
    {m ? <p class="inv-pick" aria-live="polite"><b>{monthName(m.month)}</b>: {m.n} merged{CATS.filter(([k]) => m.counts[k]).map(([k, l]) => `, ${l.toLowerCase()} ${m.counts[k]}`).join("")}.</p> : null}
  </div>;
}

export default function Investment({ app }: PageProps) {
  const f = useFiles<{ d: D }>({ d: "delivery.json" });
  const [ranges, setRange] = useRange();
  const [pick, setPick] = useState<string | null>(null);
  const [nums, setNums] = useState(false);
  const title = "Investment", sub = "Where engineering time goes: features, fixes, upkeep, security and docs, from merged pull requests.";
  if (!app) return <Page title={title} subtitle={sub}><EmptyState icon="setup" title="No StackVitals data here yet" action={<Button variant="filled" href="#/setup">Set it up</Button>} /></Page>;
  if (!f.ready) return <PageSkeleton />;
  if (!f.d) return <Page title={title} subtitle={sub}><EmptyState icon="investment" title="Delivery hasn't run here yet." action={<Button variant="filled" href="#/settings" icon="settings">Turn it on</Button>}>The mix comes with Delivery, which runs with Team Flow on the schedule.</EmptyState></Page>;
  const inv = f.d.investment, ep = f.d.epics;
  if (inv === undefined) return <Page title={title} subtitle={sub}><EmptyState icon="clock" title="Not measured yet.">The next run with this version fills it in.</EmptyState></Page>;
  if (!inv) return <Page title={title} subtitle={sub}><EmptyState icon="investment" title="No merged pull requests by people in the last six months.">The mix shows once people's work merges.</EmptyState></Page>;
  const shown = CATS.filter(([k]) => inv.counts[k]);
  const metrics: Metric[] = shown.map(([k, name]) => ({ id: k, name, sub: `${inv.counts[k]} of ${inv.n} merged PRs`, kind: "share", better: null, period: "month",
    points: inv.months.map((m) => ({ label: dateLabel(m.month), value: m.n ? (m.counts[k] || 0) / m.n : 0, n: m.n })),
    meaning: (v, p) => `${pct(v)} of ${p.n ?? "the"} pull requests merged that month were ${k === "other" ? "not sorted" : `${name.toLowerCase()} work`}.` }));
  const metric = metrics.find((m) => m.id === pick) || metrics[0];
  const how = Object.entries(inv.decided_by);
  return <Page title={title} subtitle={sub}>
    {metric ? <Section title="Mix of work" description={`Each kind's share of merged pull requests by month, since ${monthName(inv.since)}. Pick a row to chart it.`}
      info={<InfoButton info={{ title: "Mix of work", body: "Merged pull requests into the default branch by people and AI agents, sorted into one kind of work each. Update bots' pull requests are counted apart.",
        facts: [["Merged PRs", String(inv.n)], ["Update-bot PRs, apart", String(inv.bots)]] }} />}>
      <Columns ratio="lead">
        <Card><MetricHero metric={metric} ranges={ranges} setRange={setRange} /></Card>
        <Watchlist label="Kinds of work" items={metrics.map((m) => ({ ...metricItem(m, ranges[m.period] || 6), value: pct(inv.shares[m.id]),
          sub: <><i class={`inv-dot inv-c-${m.id}`} />{inv.counts[m.id]} of {inv.n} merged PRs</> }))} selected={metric.id} onSelect={setPick} />
      </Columns>
    </Section> : null}

    <Section title="Month by month" description={`People and AI agents; ${inv.bots} update-bot pull requests counted apart. Tap a month to read its mix.`}
      action={<label class="inv-toggle"><span>Show numbers</span><Toggle checked={nums} onChange={setNums} label="Show numbers" /></label>}>
      <Card>
        <ul class="inv-legend">{CATS.map(([k, name]) => <li><i class={`inv-dot inv-c-${k}`} />{name} <span class="muted num">{inv.counts[k] || 0}</span></li>)}</ul>
        <Stack months={inv.months} />
      </Card>
      {nums ? <Framed title="The numbers behind the bars" note="merged pull requests by month and kind" class="inv-nums"><Table name="investment-months" caption="Merged pull requests by month and kind" search={false} rows={inv.months.map((m) => ({ ...m, ...m.counts }))} columns={[
        { key: "month", label: "Month", primary: true, raw: (m) => monthName(m.month) }, ...CATS.map(([k, name]) => ({ key: k, label: name, num: true })), { key: "n", label: "All", num: true }]} /></Framed> : null}
    </Section>

    <Section title="How each pull request was sorted" description="The first rule that matches decides; your own label rules come first.">
      <div class="inv-sorted">
        <Framed title="What decided each one" note={`${inv.n} merged pull requests`}>
          <Table name="investment-decided" search={false} rows={how.map(([k, n]) => ({ k, n, share: inv.n ? n / inv.n : null }))} initialSort={{ key: "n", desc: true }} columns={[
            { key: "k", label: "Decided by", primary: true, raw: (r) => HOW[r.k] || r.k }, { key: "n", label: "PRs", num: true },
            { key: "share", label: "Share", num: true, render: (r) => pct(r.share) }]} />
        </Framed>
        <Framed title="The order the rules are tried" note="the first match wins">
          <Table name="investment-order" search={false} rows={ORDER.map(([rule, example], i) => ({ i: i + 1, rule, example }))} columns={[
            { key: "i", label: "Step", num: true }, { key: "rule", label: "Rule", primary: true }, { key: "example", label: "For example" }]} />
        </Framed>
      </div>
      <Panel title="Sort your own labels" class="inv-rules" bar={<Button size="sm" variant="tinted" href="#/settings?module=delivery" iconEnd="right">Open Settings</Button>}>
        <p class="blk-note">Name the labels that mean each kind of work in Settings (Delivery, labels per kind of work), or paste this into <code>.github/stackvitals.toml</code> with your own labels; the next run sorts again.</p>
        <CodeBlock code={RULES} title=".github/stackvitals.toml" />
      </Panel>
    </Section>

    {ep ? <Section title="By epic or project" description={`Merged pull requests linked to Jira or Linear issues since ${monthName(ep.since)}.`}>
      <Panel title="Linked work" class="inv-facts"><Facts rows={[["Linked pull requests", String(ep.linked)], ["Without an epic or project", String(ep.no_epic)],
        ["On feature issues", <>{pct(ep.feature_share)} <span class="muted">(the part teams often capitalise; an estimate from issue types, not an accounting figure)</span></>]]} /></Panel>
      <Framed title="Epics and projects" note="largest first"><Table name="epics" caption="By epic or project" search={false} rows={[...ep.epics.map((e) => ({ ...e, name: e.title || (e.epic.startsWith("linear:project:") ? "A Linear project (names hidden on public repos)" : e.epic) })),
        ...(ep.no_epic ? [{ epic: "", name: "No epic or project", prs: ep.no_epic, share: ep.no_epic / ep.linked }] : [])]} columns={[
        { key: "name", label: "Epic or project", primary: true }, { key: "prs", label: "PRs", num: true }, { key: "share", label: "Share", num: true, render: (e) => pct(e.share) }]} /></Framed>
    </Section> : null}
    {(f.d as R).capex ? <Finance c={(f.d as R).capex} /> : null}
  </Page>;
}

// For finance (core/capex.py): author-weeks by kind of work each month, and the CSV an auditor can follow to GitHub.
type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
async function saveCsv(): Promise<void> {
  const text = await fetchText(current.get().source, "capex.csv");
  if (!text) { toast("The CSV isn't published here; the next Delivery run writes it", "bad"); return; }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  a.download = "stackvitals-capex.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

function Finance({ c }: { c: R }) {
  const months = [...(c.months || [])].reverse() as R[];
  return <Section title="For finance" description="Author-weeks by kind of work each month, and a CSV of every merged pull request an auditor can follow back to GitHub."
    action={<Button size="sm" variant="tinted" icon="down" onClick={() => { void saveCsv(); }}>Download CSV</Button>}>
    <Panel title="What the CSV holds" class="inv-facts" bar={<Button size="sm" variant="tinted" icon="down" onClick={() => { void saveCsv(); }}>Download CSV</Button>}><Facts rows={[["Rows in the CSV", `${c.rows} merged pull requests, last 12 months`],
      ["Each row has", "month, merge time, link, kind of work, how that was decided, epic, and whether a person or a coding agent wrote it"],
      ["An author-week", "one person's pull requests of one kind in one ISO week"], ["Names", "none: the file names no one"]]} /></Panel>
    <Framed title="Author-weeks by kind of work" note="newest month first"><Table name="capex" caption="Author-weeks by kind of work" search={false} rows={months} columns={[
      { key: "month", label: "Month", primary: true, raw: (m) => monthName(m.month) }, { key: "prs", label: "Merged PRs", num: true },
      { key: "feature", label: "Feature author-weeks", num: true, raw: (m) => m.author_weeks?.feature ?? 0 },
      { key: "other", label: "Other author-weeks", num: true, raw: (m) => Object.entries(m.author_weeks || {}).filter(([k]) => k !== "feature").reduce((a, [, v]) => a + (v as number), 0) },
      { key: "feature_share", label: "Feature share", num: true, render: (m) => (m.feature_share == null ? "–" : `${Math.round(m.feature_share * 100)}%`) },
      { key: "agent_prs", label: "By agents", num: true }]} /></Framed>
    <p class="blk-note inv-after">Feature work is what teams usually capitalise; the rule stays yours and your auditor's.</p>
  </Section>;
}
