// Explore: the summary tables behind every page (one row per pull request, job, test, deployment), ready questions and a
// query builder that run on them in this browser, each table downloadable; the SQL explorer (DuckDB in the browser, from
// jsDelivr, pinned) and `stackvitals sql` take the same queries.
import "./explore.css";
import { useEffect, useState } from "preact/hooks";
import type { PageProps } from "../app/routes";
import { json, table } from "../data/files";
import { count, csv, day } from "../data/format";
import { current } from "../data/repos";
import { useStore } from "../data/store";
import type { AppJson, SummaryManifest } from "../data/types";
import { Button } from "../ui/Button";
import { CodeBlock, EmptyState, InfoButton, PageSkeleton, Pill, toast } from "../ui/bits";
import { Card, Page, Section, Stat, Stats } from "../ui/Page";
import { Table } from "../ui/Table";
import { Builder, Questions, sqlCommand } from "./explore/parts";
import { explorerTable } from "./explore/query";
import { Panel } from "./portal/panel";

const ABOUT: Record<string, string> = { prs: "One row per pull request", ci_jobs: "One row per CI job", tests: "One row per test",
  devlake_pull_requests: "DevLake's pull_requests", devlake_project_pr_metrics: "DevLake's PR cycle-time phases",
  devlake_cicd_deployment_commits: "DevLake's deployments", devlake_incidents: "DevLake's incidents", devlake_issues: "DevLake's issues" };

// Where explore.html lives for the open repo: beside this page or on its Pages site; a data branch has no pages.
function explorer(app: AppJson | null, kind: string, url?: string): string | null {
  if (app?.pages && !app.pages.includes("explore.html")) return null;
  if (kind === "here") return "explore.html";
  return kind === "pages" && url ? new URL("explore.html", new URL(url, location.href)).href : null;
}

async function save(name: string): Promise<void> {
  const rows = ((await table(name)) || []) as Record<string, unknown>[];
  const keys = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const href = URL.createObjectURL(new Blob([csv(rows, keys.map((k) => ({ key: k, label: k })))], { type: "text/csv" }));
  const a = Object.assign(document.createElement("a"), { href, download: `${name}.csv` });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
  toast(`Saved ${name}.csv, ${count(rows.length, "row")}`);
}

export default function Explore({ app }: PageProps) {
  const repo = useStore(current);
  const [manifest, setManifest] = useState<SummaryManifest | null | undefined>(undefined);
  const [start, setStart] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setManifest(undefined);
    (async () => {
      for (const base of app?.summary === null ? ["../summary/"] : ["summary/", "../summary/"]) {
        const m = await json<SummaryManifest>(base + "manifest.json", repo.source);
        if (m) return m;
      }
      return null;
    })().then((m) => live && setManifest(m));
    return () => { live = false; };
  }, [repo.id, app?.repo]);
  if (manifest === undefined) return <PageSkeleton />;
  const src = repo.source;
  const sql = explorer(app, src.kind, src.kind === "pages" ? src.url : undefined);
  const name = app?.repo || repo.label || "owner/repo";
  const files = Object.entries(manifest?.files || {}).map(([file, v]) => ({ id: file, name: file.replace(/\.jsonl$/, ""), ...v }));
  const tables = files.map((f) => f.name);
  const rows = files.reduce((s, f) => s + (f.rows || 0), 0);
  const query = (t: string) => { setStart(t); requestAnimationFrame(() => document.getElementById("ex-builder")?.scrollIntoView({ behavior: "smooth", block: "start" })); };
  return <Page title="Explore" subtitle="The tables behind every page: ask a question, build a query or download a table. It all runs in this browser; nothing leaves the page."
    toolbar={sql ? <Button variant="plain" href={sql} external iconEnd="external">Open the SQL explorer</Button> : null}>
    {files.length ? <>
      <Stats>
        <Stat label="Tables" value={files.length} />
        <Stat label="Rows" value={rows.toLocaleString()} />
        <Stat label="Written" value={manifest?.generated ? day(String(manifest.generated)) : "–"} />
        <Stat label="SQL explorer" value={sql ? "Published" : "Not here"} note={sql ? "beside this app" : "the questions and builder below work without it"} />
      </Stats>

      <Section title="Ask a question" description="Pick one: it runs on this repo's tables right here. Open it in the SQL explorer or copy it as a command to take it further."
        info={<InfoButton info={{ title: "How questions run", doc: "app.md", body: <>The questions and the builder read the summary tables this app already loads and
          compute in your browser, with no download beyond the tables. Each prints the same query as DuckDB SQL: the SQL explorer runs it on DuckDB in your browser
          (about 35 MB once, from jsDelivr, pinned with integrity hashes), and <code class="code-inline">stackvitals sql</code> runs it in a terminal.</> }} />}>
        <Questions repo={name} explorer={sql} tables={tables} />
      </Section>

      <Section title="Build a query" description="Filter, group and measure any table without writing SQL. The SQL it stands for is one click away." id="ex-builder">
        <Builder repo={name} explorer={sql} tables={tables} start={start && tables.includes(start) ? start : tables.includes("prs") ? "prs" : tables[0]!} />
      </Section>

      <Section title="Tables" description="Each summary table with its size; query it above or download it as CSV." action={<Pill tone="neutral" icon={null}>{count(files.length, "table")}</Pill>}>
        <Table name="tables" caption="Tables" search={false} rows={files} columns={[
          { key: "name", label: "Table", primary: true, nowrap: true, render: (t) => <span class="ex-id">{t.name}</span> },
          { key: "about", label: "What it holds", raw: (t) => ABOUT[t.name] || "", render: (t) => ABOUT[t.name] || "–" },
          { key: "rows", label: "Rows", num: true, raw: (t) => t.rows ?? null, render: (t) => (t.rows ?? 0).toLocaleString() },
          { key: "generated", label: "Written", raw: (t) => String(t.generated || ""), render: (t) => (t.generated ? String(t.generated).slice(0, 16).replace("T", " ") : "–") },
          { key: "act", label: "Actions", raw: () => "", render: (t) => <span class="row-btns">
            <Button size="sm" variant="tinted" onClick={() => query(t.name)} label={`Query ${t.name}`}>Query</Button>
            {sql ? <Button size="sm" variant="plain" href={`${sql}#sql=${encodeURIComponent(`select * from ${explorerTable(t.name)} limit 50`)}`} external iconEnd="external" label={`Open ${t.name} in the SQL explorer`}>SQL explorer</Button> : null}
            <Button size="sm" variant="plain" icon="down" onClick={() => save(t.name)} label={`Download ${t.name} as CSV`}>CSV</Button></span> }]} />
      </Section>
    </> : <Section title="Tables" description="Public repos publish them beside this app; a private repo's live on its data branch.">
      <Card><EmptyState icon="explore" title="No summary tables here.">Open a repo that runs StackVitals, or open a private repo's app from your machine (below).</EmptyState></Card>
    </Section>}

    <Section title="From your machine" description="For tables too big for a browser, several repos in one query, or a private repo without a published app.">
      <Panel title="stackvitals sql" meta={`pip install "stackvitals[sql]"`}>
        <p>Reads the tables from the repo's stackvitals-data branch with your GitHub token (GITHUB_TOKEN, or gh auth login) and runs DuckDB on your computer,
          so size is limited only by your machine. Repeat <code class="code-inline">--repo</code> to query several repos at once; each row gets a repo column.</p>
        <CodeBlock inline code={sqlCommand(name, "select role, count(*) as prs, round(median(pickup_s) / 3600, 1) as median_pickup_hours from prs where author_kind = 'person' group by 1 order by 2 desc")}
          note="Any query from this page: Copy as a command fills it in." />
        <CodeBlock inline code={`stackvitals ui ${name}`} note="Opens this app, the SQL explorer included, from a local copy of the data branch: the way to explore a private repo." />
      </Panel>
    </Section>
  </Page>;
}
