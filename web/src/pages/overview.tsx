// Overview: installation health, the weather-style conditions per area, the trend you pick, what needs a decision,
// what to fix first, decisions ending soon and a builder to make one.
import "./overview.css";
import { useState } from "preact/hooks";
import { useJump } from "../app/jump";
import type { PageProps } from "../app/routes";
import { href } from "../app/router";
import { MetricHero, Watchlist, metricItem, trendTones, useRange } from "../charts/MetricHero";
import { freshest, inForce, useFiles } from "../data/files";
import { ago, count, hours } from "../data/format";
import type { AlertsJson, CiJson, CommunityJson, DecisionsJson, DeliveryJson, DepsJson, FlowJson, InsightsJson, PortalJson, VulnsJson } from "../data/types";
import { HealthStrip } from "../features/Health";
import { AREA_ICON, areas, overall, overviewMetrics, queue, type VitalFiles } from "../features/vitals";
import { Button } from "../ui/Button";
import { EmptyState, InfoButton, Pill, PageSkeleton } from "../ui/bits";
import { Icon } from "../ui/icons";
import { Card, Columns, Page, Section } from "../ui/Page";
import { DecisionBuilder, DecisionTables, FixFirst, NeedsTable, needs, pickables } from "./overview/parts";

type F = { ci: CiJson; flow: FlowJson; delivery: DeliveryJson; community: CommunityJson; deps: DepsJson; portal: PortalJson; insights: InsightsJson; decisions: DecisionsJson; alerts: AlertsJson; vulns: VulnsJson };

const NO_DATA = <EmptyState icon="setup" title="No StackVitals data here yet"
  action={<><Button variant="filled" href="#/setup" icon="setup">Set it up</Button><Button variant="tinted" href="?demo=1" icon="play">Try the demo</Button></>}>
  The first run of the StackVitals workflow writes it. Already installed? Open your repo from the switcher at the top right, by name or Pages address.
</EmptyState>;

export default function Overview({ app }: PageProps) {
  useJump();
  const f = useFiles<F>({ ci: "data.json", flow: "flow.json", delivery: "delivery.json", community: "community.json", deps: "deps.json",
    portal: "portal.json", insights: "insights.json", decisions: "decisions.json", alerts: "alerts.json", vulns: "vulns.json" });
  const [ranges, setRange] = useRange();
  const [pick, setPick] = useState<string | null>(null);
  if (!app) return <Page title="Overview" subtitle="Your repository's vital signs at a glance.">{NO_DATA}</Page>;
  if (!f.ready) return <PageSkeleton />;
  const files = f as unknown as VitalFiles;
  const todo = queue(files, app);
  const list = areas(files, todo);
  const metrics = overviewMetrics(files);
  const chartable = metrics.filter((m) => m.points.length > 1);
  const metric = metrics.find((m) => m.id === pick) || chartable[0] || metrics[0];
  const findings = f.insights?.findings || [];
  const fixes = findings.filter((x) => !x.decision).slice(0, 3);
  const stake = f.insights ? (f.insights.opportunity?.hours ?? findings.filter((x) => !x.decision).reduce((s, x) => s + x.hours, 0)) : null;
  const decided = Object.values(f.decisions?.state || {}).filter(inForce);
  const soon = decided.filter((d) => d.until).sort((a, b) => String(a.until).localeCompare(String(b.until))).slice(0, 6);
  const log = (f.decisions?.log || []).slice(0, 6);
  const word = overall(list);
  const worst = list.find((a) => a.tone === "bad");
  const line = fixes[0]?.title || (worst ? `${worst.name}: ${worst.value} ${worst.note.split(";")[0]}.` : todo.length ? `${count(todo.length, "thing")} waiting for a decision.` : "Nothing waits for you right now.");
  const when = freshest(app);
  return <Page title="Overview" subtitle={<>{app.repo}{app.visibility === "private" ? <> · <Pill tone="neutral" icon="lock">Private</Pill></> : null}<span class="sub-when">{when ? `updated ${ago(when)}` : "no data written yet"}</span></>}>
    <HealthStrip app={app} />

    <div class="conditions" aria-label="Conditions">
      <div class="cond-text">
        <p class="cond-word">{word}.</p>
        <p class="cond-line">{line}</p>
        <p class="cond-sub">{decided.length ? `${count(decided.length, "decision")} in force` : "No decisions in force"}{todo.length ? `, ${todo.length} waiting for one` : ", nothing waiting"}.</p>
      </div>
      {stake !== null ? <div class="stake"><b class="num">{Math.round(stake)}</b><span>hours at stake <InfoButton info={{ title: "Hours at stake",
        body: "Waiting time you could win back across the open findings, each hour counted once. An estimate of what fixing could win back, not hours proven lost.",
        facts: f.insights?.opportunity ? [["Findings", String(f.insights.opportunity.findings)], ["Hours", hours(f.insights.opportunity.hours)]] : [], doc: "methods.md" }} /></span></div> : null}
    </div>

    <Section title="Areas" description="One reading per module. Tap an area to open it.">
      <div class="tiles">
        {list.map((a, i) => <a class={`tile tone-${a.tone} press`} href={a.tone === "off" ? "#/setup" : href(a.id)} style={{ animationDelay: `${i * 40}ms` }}
          aria-label={`${a.name}: ${a.word}. ${a.value} ${a.note}${a.alarm ? `. ${a.alarm}` : ""}`}>
          <span class="tile-top"><Icon name={AREA_ICON[a.tone]} />{a.name}</span>
          <span class="tile-word">{a.word}</span>
          <span class="tile-value num">{a.value}</span>
          <span class="tile-note">{a.note}</span>
          {a.alarm ? <span class="tile-alarm"><Icon name="warn" />{a.alarm}</span> : null}
        </a>)}
      </div>
    </Section>

    {metric ? <Section title="Trends" description="Drag across the chart, or focus it and use the arrow keys. Pick a row to chart it.">
      <Columns ratio="lead">
        <Card><MetricHero metric={metric} ranges={ranges} setRange={setRange} /></Card>
        <Watchlist label="Vital signs" items={metrics.map((m) => metricItem(m, ranges[m.period] || 12))} selected={metric.id} onSelect={setPick} tones={trendTones(metrics, ranges)} />
      </Columns>
    </Section> : null}

    <Section title="Needs a decision" description="New flaky tests, stuck reviews, security updates and newcomers. Sort by a column or filter by kind; Decide lands in the decisions log."
      action={<Pill tone={todo.length ? "watch" : "good"}>{todo.length ? `${todo.length} waiting` : "All clear"}</Pill>}>
      {todo.length ? <NeedsTable app={app} rows={needs(todo, files)} />
        : <Card><EmptyState icon="check" title="Nothing waits for a decision.">New flaky tests, stuck reviews, security updates and newcomers show up here.</EmptyState></Card>}
    </Section>

    <Section title="Fix first" description="The open findings with the most hours of waiting at stake, ranked." action={<Button size="sm" variant="plain" href="#/insights" iconEnd="right">All findings</Button>}>
      <FixFirst fixes={fixes} />
    </Section>

    <Section title="Decisions" description="Quarantines, mutes and snoozes ending soon, and the latest decisions made." action={<Button size="sm" variant="plain" href="#/activity" iconEnd="right">Activity</Button>}>
      <DecisionTables soon={soon} log={log} />
    </Section>

    <Section id="ov-decide" title="Make a decision" description="Pick an item this page knows, the decision and a reason. It goes to GitHub as a prefilled issue, through the workflow with your token, or as a comment you paste."
      action={app.links?.new_issue ? <Button size="sm" variant="plain" href={app.links.new_issue} external iconEnd="external">Open an issue</Button> : null}>
      <DecisionBuilder app={app} items={pickables(todo, files, findings.filter((x) => !x.decision))} newcomers={todo.filter((t) => t.kind === "community").length} />
    </Section>
  </Page>;
}
