// Where you stand: every comparison with similar public repos in one place (CI, review flow, delivery, community),
// each measured with the crawl benchmarks' own definitions and placed in the closest group with enough repos.
import "./standing.css";
import type { PageProps } from "../app/routes";
import { useFiles } from "../data/files";
import { count, hours, pct } from "../data/format";
import { Button } from "../ui/Button";
import { EmptyState, InfoButton, PageSkeleton } from "../ui/bits";
import { Card, Page, Section, Stat, Stats } from "../ui/Page";
import { Table } from "../ui/Table";
import { Panel } from "./portal/panel";

type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
interface Row { id: string; name: string; you: string; typical: string; place: string }
interface Area { key: string; area: string; href: string; group: string | null; rows: Row[]; why: string }

// A value as its section measures it: CI times in seconds, Delivery and Team Flow in hours, shares as percentages.
function shown(m: R, v: unknown): string {
  if (typeof v !== "number") return "–";
  if (m.kind === "share" || /share|rate/.test(String(m.key || ""))) return pct(v);
  if (m.kind === "time") return v >= 3600 ? hours(v / 3600) : `${Math.round(v / 60)} min`;
  if (/hours/.test(String(m.key || "")) || m.kind === "hours") return hours(v);
  return v.toLocaleString();
}
const groupOf = (c: R | null | undefined) => (c ? `${c.group || "similar repos"}${c.repos ? `, ${Number(c.repos).toLocaleString()} repos` : ""}` : null);

function metrics(c: R | null | undefined): Row[] {
  if (!c || !Array.isArray(c.metrics)) return [];
  return c.metrics.map((m: R, i: number) => ({ id: String(m.key || i), name: String(m.name || m.key), you: shown(m, m.you), typical: shown(m, m.typical), place: String(m.place || "–") }));
}

// Community: the score's facts (each placed as "better than N%"), bus factor and top share against the middle half, star growth.
function community(com: R | null | undefined): Row[] {
  const out: Row[] = [];
  for (const f of (com?.score?.facts || []) as R[]) out.push({ id: String(f.key), name: String(f.name || f.key), you: shown(f, f.you), typical: shown(f, f.typical),
    place: f.better_than != null ? `better than about ${f.better_than}%` : "–" });
  const d = com?.dependency, mid = (x: R, f: (v: number) => string) => `${f(x.typical)} (middle half ${f(x.low)} to ${f(x.high)})`;
  if (d?.peers?.bus_factor) out.push({ id: "bus_factor", name: "Bus factor: fewest people behind half the merged PRs", you: String(d.bus_factor ?? "–"), typical: mid(d.peers.bus_factor, String),
    place: d.bus_factor == null ? "–" : d.bus_factor < d.peers.bus_factor.low ? "below the middle half" : d.bus_factor > d.peers.bus_factor.high ? "above the middle half" : "within the middle half" });
  if (d?.peers?.top_share) out.push({ id: "top_share", name: "Most active person's share of merged PRs", you: pct(d.top_share), typical: mid(d.peers.top_share, (v) => pct(v)),
    place: d.top_share == null ? "–" : d.top_share > d.peers.top_share.high ? "more concentrated than most" : d.top_share < d.peers.top_share.low ? "more spread than most" : "within the middle half" });
  const stars = com?.stars?.peers || com?.peers;
  if (stars?.place) out.push({ id: "stars", name: "Star growth, last 12 weeks", you: com?.stars?.gained_12w != null ? `+${com.stars.gained_12w}` : "–",
    typical: stars.typical_gain != null ? `+${stars.typical_gain}` : "–", place: String(stars.place) });
  return out;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export default function Standing(_: PageProps) {
  const f = useFiles<{ ci: R; flow: R; dl: R; com: R }>({ ci: "data.json", flow: "flow.json", dl: "delivery.json", com: "community.json" });
  if (!f.ready) return <PageSkeleton />;
  const com = f.com, stars = com?.stars?.peers || com?.peers;
  const areas: Area[] = [
    { key: "ci", area: "CI", href: "#/ci", group: groupOf(f.ci?.benchmark), rows: metrics(f.ci?.benchmark), why: "needs about a week of CI history and the crawl's CI benchmark file" },
    { key: "flow", area: "Review flow", href: "#/prs", group: groupOf(f.flow?.peers), rows: metrics(f.flow?.peers), why: "needs about ten merged pull requests and the crawl's review benchmark file" },
    { key: "delivery", area: "Delivery", href: "#/delivery", group: groupOf(f.dl?.peers), rows: metrics(f.dl?.peers), why: "needs recorded deployments and the crawl's delivery benchmark file" },
    { key: "community", area: "Community", href: "#/community", group: groupOf(com?.score) || groupOf(stars), rows: community(com),
      why: "needs two facts with a public comparison, or a few months of merged work" },
  ];
  const shown_ = areas.filter((a) => a.rows.length), missing = areas.filter((a) => !a.rows.length);
  const agents = f.dl?.ai?.leaderboard;
  const lead = agents ? Object.entries(agents.agents || {}).map(([k, v]) => ({ id: k, k: cap(String(k)), ...(v as R) }) as R).sort((a, b) => (b.prs ?? 0) - (a.prs ?? 0)) : [];
  const total = shown_.reduce((s, a) => s + a.rows.length, 0);
  return <Page title="Where you stand" subtitle="This repo against similar public repos, measured the same way, in one place.">
    <Section title="Summary" description="How many measures have a comparison, and against which groups."
      info={<InfoButton info={{ title: "Where you stand", doc: "accuracy.md", body: <>The groups come from StackVitals' crawl of public repos,
        refreshed daily. Each comparison uses that benchmark's own definition, so it can differ from the number on the module's page,
        which follows your settings. A place is a share of the group's repos, not a grade.</> }} />}>
      <Stats>
        <Stat label="Measures compared" value={total} />
        <Stat label="Areas with a comparison" value={`${shown_.length} of ${areas.length}`} note={shown_.map((a) => a.area).join(", ") || "none yet"} />
        <Stat label="Coding agents measured" value={lead.length || "–"} note={lead.length ? "across the crawl's public repos" : "no leaderboard file here"} />
      </Stats>
    </Section>

    {shown_.length ? shown_.map((a) => <Section title={a.area} description={`Compared with ${a.group || "similar repos"}: the closest group (same language and size, then wider) with enough repos.`}
      action={<Button size="sm" variant="plain" href={a.href} iconEnd="right">Open {a.area}</Button>}>
      <Table name={`standing-${a.key}`} caption={`${a.area} against similar repos`} search={false} rows={a.rows} columns={[
        { key: "name", label: "Measure", primary: true }, { key: "you", label: "Here", num: true }, { key: "typical", label: "Typical", num: true },
        { key: "place", label: "Place" }]} />
    </Section>) : <Section title="Against similar repos" description="Each number is placed in the closest group with enough repos.">
      <Card><EmptyState icon="insights" title="No comparison yet.">Comparisons appear once the crawl's benchmark files are
        available to this repo and each module has enough of its own history (about ten merged pull requests, a week of CI).</EmptyState></Card>
    </Section>}

    {missing.length ? <Section title="Not compared yet" description="The areas without a comparison, and what each needs.">
      <Table name="standing-missing" caption="Areas not compared yet" search={false} rows={missing.map((a) => ({ id: a.key, area: a.area, why: cap(a.why), href: a.href }))} columns={[
        { key: "area", label: "Area", primary: true }, { key: "why", label: "What it needs" },
        { key: "href", label: "Open", raw: () => "", render: (r) => <Button variant="plain" size="sm" href={r.href} iconEnd="right">Open {r.area}</Button> }]} />
    </Section> : null}

    {agents ? <Section title="Coding agents" description="How each agent's pull requests fare across public repos.">
      <Panel title="Agent leaderboard" meta={<>{count(lead.length, "agent")}{agents.window_days ? `, last ${agents.window_days} days` : ""}</>}
        foot={<Button variant="tinted" href="#/delivery?tab=ai" iconEnd="right">Open the full leaderboard</Button>} flush>
        <Table name="standing-agents" search={false} limit={8} rows={lead} columns={[
          { key: "k", label: "Agent", primary: true }, { key: "repos", label: "Repos", num: true }, { key: "prs", label: "Decided PRs", num: true },
          { key: "merged", label: "Merged", num: true, render: (r) => pct(r.merged) }]} />
      </Panel>
    </Section> : null}

  </Page>;
}
