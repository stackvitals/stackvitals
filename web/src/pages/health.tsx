// Data health: is each source current, did it finish reading its history, what went wrong and since when, and how far
// back each kind of history goes. Read from health.json, which every run writes (core/health.py).
import "./health.css";
import type { PageProps } from "../app/routes";
import { useFiles } from "../data/files";
import { ago, count } from "../data/format";
import { issueUrl } from "../data/requestIssue";
import { request, type Req } from "../data/write";
import type { PrefillLink } from "../github/links";
import { Button } from "../ui/Button";
import { EmptyState, InfoButton, PageSkeleton, Pill } from "../ui/bits";
import { onPrefill } from "../ui/prefill";
import { Card, Page, Section, Stat, Stats } from "../ui/Page";
import { Table } from "../ui/Table";

interface Source { kind: "module" | "connector"; last_try: string | null; last_ok: string | null; failing_since: string | null;
  error: string | null; complete: boolean | null; read: Record<string, number> }
interface Stream { oldest: string; newest: string; files: number; bytes: number; keeps_days: number }
interface HealthJson { as_of?: string; sources?: Record<string, Source>; history?: Record<string, Stream>;
  dropped?: { at: string; retention: Record<string, number>; size_cap: Record<string, number> } | null }

const STALE_MS = 2 * 86400e3;  // no run for two days: the schedule may have stopped
const STREAMS: Record<string, string> = { "ci/days": "CI runs", "ci/transitions": "CI test changes", "flow/closed": "Closed pull requests",
  "community/issues/closed": "Closed issues", "portal/history": "Portal scores" };
const streamName = (k: string) => STREAMS[k] || (k.startsWith("connectors/") ? `${k.split("/")[1]} ${k.endsWith("/raw") ? "answers kept" : "records"}` : k);
// The source each row stands for, for a targeted re-sync request (core/resync.py).
const SOURCE_IDS: Record<string, string> = { "CI Health": "ci", "Team Flow": "flow", Jira: "jira", Linear: "linear", PagerDuty: "pagerduty", "incident.io": "incident_io",
  Copilot: "copilot", Discourse: "discourse", Slack: "slack", Discord: "discord" };
const days = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 86400e3) + 1;

function state(s: Source): ["bad" | "watch" | "good", string] {
  if (s.error) return ["bad", "Failing"];
  if (s.last_try && Date.now() - Date.parse(s.last_try) > STALE_MS) return ["watch", "No recent run"];
  if (s.complete === false) return ["watch", "Filling in"];
  return ["good", "Current"];
}

// A prefilled request issue: read this service again from 30 days back (the date in the block can be changed first).
function againUrl(app: PageProps["app"], name: string): PrefillLink | null {
  const id = SOURCE_IDS[name];
  if (!app || !id) return null;
  const since = new Date(Date.now() - 30 * 86400e3).toISOString().slice(0, 10);
  return issueUrl(app, `StackVitals: read ${name} again`, { ...request(), resync: [{ source: id, since }] } as Req,
    `Read ${name} again from ${since} (change the date below, or set it to null for the whole 180 days). Records already kept stay.`);
}

export default function Health({ app }: PageProps) {
  const f = useFiles<{ h: HealthJson }>({ h: "health.json" });
  if (!f.ready) return <PageSkeleton />;
  const h = f.h;
  if (!h?.sources) return <Page title="Data health" subtitle="Is the data current, and is it complete?">
    <Card><EmptyState icon="clock" title="No health report yet.">The next StackVitals run writes one: every source, when it last worked,
      and how far back each history goes.</EmptyState></Card></Page>;
  const rows = Object.entries(h.sources).map(([name, s]) => ({ name, ...s, st: state(s) }));
  const failing = rows.filter((r) => r.st[0] === "bad"), filling = rows.filter((r) => r.st[1] === "Filling in");
  const stale = rows.filter((r) => r.st[1] === "No recent run");
  const streams = Object.entries(h.history || {}).map(([k, v]) => ({ k, ...v, span: days(v.oldest, v.newest) }));
  const cut = h.dropped ? [...Object.entries(h.dropped.retention || {}), ...Object.entries(h.dropped.size_cap || {})] : [];
  return <Page title="Data health" subtitle="Is the data current, did each source finish reading, and what is missing and why.">
    <Section title="At a glance" description={h.as_of ? `As of the run ${ago(h.as_of)}.` : undefined}
      info={<InfoButton info={{ title: "Data health", doc: "app.md#data-health", body: <>Each run records when every source last worked.
        A failing source keeps its last good data; the next run tries again. Filling in means a big history is still being read, a
        few hundred items a run, within GitHub's and each service's limits.</> }} />}>
      <Stats>
        <Stat label="Sources" value={rows.length} note={`${rows.filter((r) => r.kind === "connector").length} connected services`} />
        <Stat label="Failing" value={failing.length} note={failing.length ? failing.map((r) => r.name).join(", ") : "none"} />
        <Stat label="Still filling in" value={filling.length} note={filling.length ? filling.map((r) => r.name).join(", ") : "every history read"} />
        <Stat label="No recent run" value={stale.length} note="over two days" />
      </Stats>
    </Section>

    {failing.length ? <Section title="What to fix" description="Each failing source, since when, and what it said.">
      {failing.map((r) => <Card tone="bad"><p><b>{r.name}</b> has failed since {ago(r.failing_since)}
        {r.last_ok ? <>; its data is from {ago(r.last_ok)}</> : <>; it has not worked yet</>}.</p>
        <p class="muted">{r.error}</p></Card>)}
    </Section> : null}

    <Section title="Sources" description="Every step of the run and every connected service.">
      <Table name="health-sources" caption="Sources" rows={rows} columns={[
        { key: "name", label: "Source", primary: true },
        { key: "st", label: "State", filter: true, raw: (r) => r.st[1], render: (r) => <Pill tone={r.st[0]}>{r.st[1]}</Pill> },
        { key: "last_ok", label: "Last worked", raw: (r) => r.last_ok || "", render: (r) => <span title={r.last_ok || ""}>{r.last_ok ? ago(r.last_ok) : "never"}</span> },
        { key: "read", label: "Read last time", raw: (r) => Object.entries(r.read || {}).map(([k, v]) => `${v} ${k}`).join(", "),
          render: (r) => <span class="muted">{Object.entries(r.read || {}).map(([k, v]) => `${v.toLocaleString()} ${k.replace(/_/g, " ")}`).join(", ") || "–"}</span> },
        { key: "error", label: "Problem", render: (r) => <span class="muted">{r.error || "–"}</span> },
        { key: "again", label: "", render: (r) => { const url = againUrl(app, r.name);
          return url ? <Button variant="tinted" size="sm" href={url.url} onClick={onPrefill(url, "Opened on GitHub: press Submit there")}>Read again</Button> : null; } }]} />
    </Section>

    <Section title="History kept" description="How far back each kind of history goes, against how long it is kept.">
      <Table name="health-history" caption="History" rows={streams} columns={[
        { key: "k", label: "History", primary: true, raw: (s) => streamName(s.k) },
        { key: "oldest", label: "From" }, { key: "newest", label: "To" },
        { key: "span", label: "Days covered", num: true, render: (s) => `${s.span} of ${s.keeps_days}` },
        { key: "files", label: "Day files", num: true },
        { key: "bytes", label: "Size", num: true, render: (s) => `${(s.bytes / 1048576).toFixed(1)} MB` }]}
        empty={<Card><EmptyState icon="clock" title="No history yet.">The first run starts it.</EmptyState></Card>} />
      {cut.length ? <p class="muted small">Last removed {ago(h.dropped!.at)}: {cut.map(([k, v]) => `${count(v, "day file")} of ${streamName(k)}`).join(", ")}
        {Object.keys(h.dropped!.size_cap || {}).length ? " (the size cap; raise size-cap-mb to keep more)" : " (past its keep window)"}.</p> : null}
    </Section>
  </Page>;
}
