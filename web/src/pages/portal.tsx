// Portal: every repo in the org with its level, owners and links; which rules fail most; the typed catalog from
// catalog-info.yaml files; docs pages; campaigns with their burn-down; golden paths; and the org view across repos.
import "./portal.css";
import type { PageProps } from "../app/routes";
import { navigate, withQuery, type Route } from "../app/router";
import { BarChart } from "../charts/BarChart";
import { useFiles } from "../data/files";
import { count, day, pct } from "../data/format";
import type { AppJson, PortalFull } from "../data/types";
import { Button } from "../ui/Button";
import { InfoButton, PageSkeleton, Pill } from "../ui/bits";
import { SegmentedControl } from "../ui/controls";
import { Columns, Page, Section, Stat, Stats } from "../ui/Page";
import { Table } from "../ui/Table";
import { Panel } from "./portal/panel";
import { Campaigns, Catalog, Docs, Golden, Org, RepoSheet, Rules, ext, levelPill, ownersPill, yes, type Full } from "./portal/parts";
import { AccessCheck, OwnersReport, Outside, SetupPortal } from "./portal/tools";

const LEVELS = ["gold", "silver", "bronze"];
const level = (r: Full) => r.score?.level || "below bronze";
const cap = (s: string) => s[0]!.toUpperCase() + s.slice(1);

const TABS = ["repos", "owners", "rules", "catalog", "docs"] as const;
type Tab = (typeof TABS)[number];
const LABEL: Record<Tab, string> = { repos: "Repos", owners: "Owners", rules: "Rules", catalog: "Catalog", docs: "Docs" };

export default function Portal({ app, route }: PageProps) {
  const f = useFiles<{ p: PortalFull }>({ p: "portal.json" });
  if (!f.ready) return <PageSkeleton />;
  const p = f.p;
  if (!p || !app) return <Page title="Portal" subtitle="Every repo in an organisation with its owners, scorecard and catalog.">
    <Section title="Set up Portal" description="Portal runs from a repo of its own in the org. Create it and its workflow here, each one click on GitHub.">
      <SetupPortal app={app || null} />
    </Section>
  </Page>;
  return <Main app={app} p={p} route={route} />;
}

function Main({ app, p, route }: { app: AppJson; p: PortalFull; route: Route }) {
  const tab = (TABS as readonly string[]).includes(route.query.get("tab") || "") ? route.query.get("tab") as Tab : "repos";
  const repos = (p.repos || []).filter((r) => !r.archived) as Full[];
  const own = repos.filter((r) => !r.fork);
  const n = (l: string) => repos.filter((r) => r.score?.level === l).length;
  const below = repos.filter((r) => !r.score?.level).length;
  const counts: Record<Tab, number> = { repos: repos.length, owners: own.length, rules: new Set(repos.flatMap((r) => (r.score?.results || []).map((x) => x.id))).size,
    catalog: repos.reduce((s, r) => s + (r.descriptor?.entities?.length || 0), 0), docs: repos.reduce((s, r) => s + (r.doc_pages?.length || 0), 0) };
  const ownerOk = repos.filter((r) => r.owners?.status === "valid").length;
  const org = p.org || app.repo.split("/")[0]!;
  // ?repo= opens that repo's facts, so a link can point at one repo.
  const shown = route.query.get("repo");
  const detail = (name: string) => withQuery(route, "repo", name);
  return <Page title={`Portal: ${org}`} subtitle={`${count(repos.length, "repo")}, ${p.mode} mode, checked ${String(p.built_at || "").slice(0, 16).replace("T", " ")}.`}
    toolbar={app.modules?.portal?.page || app.pages?.includes("portal.html") ? <Button variant="plain" href={app.modules?.portal?.page || "portal.html"} iconEnd="external">Printable page</Button> : null}>
    <Section title="Levels" description="Each repo's level from the scorecard rules: bronze, silver, gold."
      info={<InfoButton info={{ title: "Levels", doc: "modules.md#portal", body: "A repo reaches a level when it passes every rule at that level and the ones below. Exempt rules don't count against it; rules in preview aren't counted yet." }} />}>
      <Columns ratio="lead">
        <Panel title="At bronze or better" meta={`${repos.length - below} of ${count(repos.length, "repo")}`} tone={below ? "watch" : "good"}>
          <div class="pt-figure num">{repos.length ? pct((repos.length - below) / repos.length) : "–"}</div>
          <p class="pt-figure-note">{below ? `${below} below bronze; the Rules tab shows what fails most.` : "Every repo reaches bronze or better."}</p>
          <BarChart label="Repos by level" height={170} bars={[...LEVELS.map((l) => ({ label: cap(l), value: n(l), tone: (l === "gold" ? "good" : l === "bronze" ? "watch" : "neutral") as "good" })),
            { label: "Below bronze", value: below, tone: "bad" as const }]} />
        </Panel>
        <Stats>
          {LEVELS.map((l) => <Stat label={cap(l)} value={n(l)} />)}
          <Stat label="Below bronze" value={below} />
          <Stat label="Owners valid" value={ownerOk} note={`${repos.filter((r) => r.owners?.status === "none").length} without CODEOWNERS`} />
        </Stats>
      </Columns>
    </Section>

    <Section title="Across the org" description="The numbers each repo running StackVitals publishes, summed or as medians, and the repos that lead.">
      <Org o={p.org_view} />
    </Section>

    <Section title="Repositories" description="Every repo with its level, owners with evidence, the rules that fail most, the catalog and docs.">
      <div class="pt-tabs"><SegmentedControl<Tab> label="Show" scroll value={tab} onChange={(v) => navigate(withQuery(route, "tab", v === "repos" ? null : v))}
        options={TABS.map((t) => ({ value: t, label: <>{LABEL[t]}<span class="seg-count num">{counts[t]}</span></>, aria: `${LABEL[t]}, ${counts[t]}` }))} /></div>
      <div class="pt-panel" key={tab}>
        {tab === "repos" ? <Table name="repos" caption="Repos" rows={repos} columns={[
          { key: "name", label: "Repo", primary: true, render: (r) => <><a href={detail(r.name)} title="What Portal read about this repo">{r.name}</a>
            {r.modules ? <div class="small"><a href={`https://${r.name.split("/")[0]!.toLowerCase()}.github.io/${r.name.split("/")[1]}/`} {...ext}>Its StackVitals app</a></div> : null}</> },
          { key: "visibility", label: "Visibility", filter: true, raw: (r) => (r.private ? "Private" : "Public") },
          { key: "level", label: "Level", filter: true, raw: level, render: (r) => levelPill(r.score?.level) },
          { key: "owners", label: "Owners", filter: true, raw: (r) => r.owners?.status || "", render: (r) => ownersPill(r.owners?.status) },
          { key: "protected", label: "Protected", filter: true, raw: (r) => String(r.protected ?? "can't read"), render: (r) => yes(r.protected) },
          { key: "language", label: "Language", filter: true, render: (r) => r.language || "–" },
          { key: "runtime", label: "Runs on", filter: true, raw: (r) => (r.runtime || []).join(" "), render: (r) => (r.runtime || []).join(", ") || "–" },
          { key: "ci", label: "CI first try", num: true, raw: (r) => r.modules?.ci_first_try_share ?? null, render: (r) => r.modules?.ci_first_try || "–" },
          { key: "since", label: "At this level since", raw: (r) => String((typeof r.since === "object" ? r.since?.level : r.since) || ""), render: (r) => day(String((typeof r.since === "object" ? r.since?.level : r.since) || "")) }]} /> : null}
        {tab === "owners" ? <OwnersReport repos={repos} /> : null}
        {tab === "rules" ? <Rules repos={repos} /> : null}
        {tab === "catalog" ? <Catalog repos={own} /> : null}
        {tab === "docs" ? <Docs repos={own} /> : null}
      </div>
    </Section>

    <Section title="Campaigns" description="A set of rules, the repos it targets and a date; the bars show repos still failing, day by day."
      action={(p.campaigns || []).length ? <Pill tone="neutral" icon={null}>{count((p.campaigns || []).length, "campaign")}</Pill> : null}>
      <Campaigns list={p.campaigns || []} />
    </Section>

    <Section title="Golden paths" description="Start a new repo from a template, or open a pull request that adds standard files. One click sends it to the portal workflow.">
      <Golden app={app} p={p} repos={own} />
    </Section>

    <Section title="Access" description="What the portal could read on its last run, and a check of any token's access to the org from this page.">
      <AccessCheck org={org} p={p} repos={repos} />
    </Section>

    <Section title="Portal outside the app" description="The files the portal workflow writes, the workflow itself, the org App and the terminal commands.">
      <Outside app={app} p={p} />
    </Section>
    <RepoSheet r={(shown ? repos.find((r) => r.name === shown) || null : null)} onClose={() => navigate(withQuery(route, "repo", null))} />
  </Page>;
}
