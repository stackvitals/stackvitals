// Portal's parts: the repo sheet, the Rules, Catalog and Docs tabs, the org view, campaigns and golden paths.
import { useState } from "preact/hooks";
import { BarChart } from "../../charts/BarChart";
import { count, dateLabel, day, pct, secs, short } from "../../data/format";
import type { AppJson, Num, PortalEntity, PortalFull, PortalRepo, PortalRule } from "../../data/types";
import type { Req } from "../../data/write";
import { Send } from "../../features/Decide";
import { PASTE_FILE_BEFORE, newFile } from "../../github/links";
import { Button } from "../../ui/Button";
import { CodeBlock, EmptyState, Pill, StatePill } from "../../ui/bits";
import { onPrefill } from "../../ui/prefill";
import { Field, Select, TextInput } from "../../ui/controls";
import { Sheet } from "../../ui/Sheet";
import { Card, Columns, Stat, Stats } from "../../ui/Page";
import { Table } from "../../ui/Table";
import { Facts, Panel } from "./panel";
import { appLink, catalogYaml, entityName, ownerRef } from "./setup";

export const ext = { target: "_blank", rel: "noopener noreferrer" };
export const ghr = (name: string) => <a href={`https://github.com/${name}`} {...ext}>{name}</a>;
// What catalog.json keeps per repo beyond what the tables use; every field may be missing on older files.
export type Ent = PortalEntity & { provides_apis?: string[]; consumes_apis?: string[]; tags?: string[] };
type Yes = boolean | null | undefined;
export type Full = Omit<PortalRepo, "owners" | "score" | "modules"> & {
  owners?: { status?: string; file?: string | null; reasons?: string[]; owners?: string[]; suggested?: string[]; suggested_from?: string } | null;
  score?: { level?: string | null; results?: PortalRule[]; not_available?: number } | null; default_branch?: string | null;
  protected?: Yes; rules?: string[] | null; docs?: Record<string, Yes | string[]> | null; files?: Record<string, Record<string, boolean>> | null;
  ci?: { first_try_share?: Num; pushes?: number; median_s?: Num } | null; reviews?: { first_review_median_s?: Num; prs?: number } | null;
  openssf?: { date?: string | null; checks?: Record<string, number | null> | null } | null; properties?: Record<string, unknown>; checked?: string; error?: string;
  modules?: { ci_first_try?: string; ci_first_try_share?: Num; flow?: { open?: number; stale?: number; first_review_median_s?: Num } } | null;
};
export const yes = (v: Yes) => (v === true ? <Pill tone="good">Yes</Pill> : v === false ? <Pill tone="bad">No</Pill> : <Pill tone="neutral" icon={null}>Can't read</Pill>);
export const ownersPill = (s?: string) => <Pill tone={s === "valid" ? "good" : s === "weak" ? "watch" : s === "none" ? "bad" : "neutral"}>{s ? s[0]!.toUpperCase() + s.slice(1) : "Not checked"}</Pill>;
export const levelPill = (l?: string | null) => (l ? <StatePill value={l} /> : <Pill tone="bad">Below bronze</Pill>);
const DOC_NAMES: Record<string, string> = { readme: "README", license: "Licence", contributing: "Contributing guide", code_of_conduct: "Code of conduct" };
const apis = (e: Ent) => [...(e.provides_apis || []).map((a) => `provides ${a.split("/").pop()}`), ...(e.consumes_apis || []).map((a) => `uses ${a.split("/").pop()}`)].join(", ");
const osfTone = (v: number) => (v >= 7 ? "good" : v >= 4 ? "watch" : "bad");
const KV = ({ rows }: { rows: ([string, unknown] | null | false)[] }) => <dl class="kv">{rows.filter((r): r is [string, unknown] => !!r).map(([k, v]) => <><dt>{k}</dt><dd>{v as string}</dd></>)}</dl>;

// One repo's facts as Portal read them: owners, protection, files, CI, reviews, published Scorecard and catalog entities.
export function RepoSheet({ r, onClose }: { r: Full | null; onClose: () => void }) {
  if (!r) return null;
  const o = r.owners, d = r.docs || {}, osf = r.openssf?.checks, ents = (r.descriptor?.entities || []) as Ent[];
  const orgDefaults = Array.isArray(d.org_defaults) ? d.org_defaults : [];
  const firstTry = r.modules?.ci_first_try || (r.ci?.first_try_share != null ? `${pct(r.ci.first_try_share)} of ${r.ci.pushes ?? "?"} pushes` : null);
  const review = r.modules?.flow?.first_review_median_s ?? r.reviews?.first_review_median_s;
  const failing = (r.score?.results || []).filter((x) => x.result === "fail");
  return <Sheet open onClose={onClose} title={r.name} size="md"
    footer={<><Button variant="plain" href={`https://github.com/${r.name}`} external iconEnd="external">Open on GitHub</Button><Button variant="filled" onClick={onClose}>Done</Button></>}>
    {r.error ? <div class="note note-watch"><span>The last check stopped on this repo ({r.error}); these are the facts from the check before.</span></div> : null}
    <section class="sheet-sec"><h3>Level</h3><KV rows={[
      ["Level", levelPill(r.score?.level)],
      ["Rules failing", failing.length ? <ul class="pt-plain">{failing.map((x) => <li><span class="mono-soft">{x.id}</span>{x.evidence ? <div class="muted small">{x.evidence}</div> : null}</li>)}</ul> : "None"],
      !!r.score?.not_available && ["Can't be read", `${count(r.score!.not_available!, "rule")}, usually a published Scorecard check on a private repo`],
      !!r.checked && ["Checked", day(r.checked)]]} /></section>
    <section class="sheet-sec"><h3>Owners</h3><KV rows={[
      ["CODEOWNERS", <>{ownersPill(o?.status)}{o?.file ? <div class="muted small mono-soft">{o.file}</div> : null}</>],
      !!o?.owners?.length && ["Owners", <span class="mono-soft">{o!.owners!.join(", ")}</span>],
      !!o?.reasons?.length && ["Why", o!.reasons!.join("; ")],
      !!o?.suggested?.length && ["Suggested", <><span class="mono-soft">{o!.suggested!.join(", ")}</span><div class="muted small">from {o!.suggested_from || "recent activity"}</div></>]]} /></section>
    <section class="sheet-sec"><h3>Default branch and files</h3><KV rows={[
      ["Branch protected", yes(r.protected)],
      !!r.rules && ["Ruleset rules", <span class="mono-soft">{r.rules!.join(", ") || "none"}</span>],
      ...Object.keys(DOC_NAMES).filter((k) => k in d).map((k) => [DOC_NAMES[k]!, <>{yes(d[k] as Yes)}{orgDefaults.includes(k) ? <div class="muted small">from the org's .github repo</div> : null}</>] as [string, unknown]),
      ...Object.entries(r.files || {}).map(([path, f]) => [path, <>{yes(f.present)}{Object.entries(f).filter(([k]) => k !== "present").map(([k, v]) =>
        <div class="muted small">{k.replace(":", " ")}: {v ? "yes" : "no"}</div>)}</>] as [string, unknown])]} /></section>
    <section class="sheet-sec"><h3>CI and reviews</h3><KV rows={[
      ["CI passes first try", <>{firstTry || "–"}{r.ci?.median_s != null ? <div class="muted small">a push's CI took {secs(r.ci.median_s)} at the median</div> : null}</>],
      ["First review, median", <>{review != null ? secs(review) : "–"}{r.reviews?.prs ? <div class="muted small">over {count(r.reviews.prs, "PR")}</div> : null}</>],
      !!r.modules?.flow && ["Open PRs", <>{r.modules!.flow!.open ?? "–"}{r.modules!.flow!.stale ? <div class="muted small">{r.modules!.flow!.stale} stale</div> : null}</>]]} /></section>
    {osf ? <section class="sheet-sec"><h3>OpenSSF Scorecard{r.openssf?.date ? `, ${day(r.openssf.date)}` : ""}</h3><KV rows={
      Object.entries(osf).sort((a, b) => (a[1] ?? 11) - (b[1] ?? 11)).map(([k, v]) => [k, v == null || v < 0 ? <Pill tone="neutral" icon={null}>Not scored</Pill> : <Pill tone={osfTone(v)}>{v} of 10</Pill>])} /></section>
      : r.private ? <p class="muted small sheet-sec">OpenSSF publishes Scorecards for public repos only.</p> : null}
    {ents.length ? <section class="sheet-sec"><h3>Catalog</h3><KV rows={ents.map((e) => [e.title || e.name, <>{e.kind}{e.system ? `, system ${e.system}` : ""}{e.lifecycle ? `, ${e.lifecycle}` : ""}
      {apis(e) ? <div class="small">{apis(e)}</div> : null}{e.tags?.length ? <div class="muted small">tags: {e.tags.join(", ")}</div> : null}</>])} /></section> : null}
    {r.properties && Object.keys(r.properties).length ? <section class="sheet-sec"><h3>Custom properties</h3><KV rows={
      Object.entries(r.properties).map(([k, v]) => [k, Array.isArray(v) ? v.join(", ") : String(v)])} /></section> : null}
  </Sheet>;
}

const TYPES = ["service", "website", "library", "mobile-app", "tool", "documentation"];
const LIFECYCLES = ["production", "experimental", "deprecated"];

// A catalog-info.yaml for a repo without one, opened in GitHub's editor ready to commit (no token: GitHub asks there).
function CatalogStarter({ repos }: { repos: Full[] }) {
  const [name, setName] = useState(repos[0]?.name || "");
  const r = repos.find((x) => x.name === name) || repos[0];
  const [form, setForm] = useState<Record<string, string>>({});
  if (!r) return null;
  const short_ = r.name.split("/")[1] || r.name;
  const v = { name: entityName(form.name ?? short_), title: form.title ?? "", description: form.description ?? "", type: form.type || "service",
    lifecycle: form.lifecycle || "production", owner: form.owner ?? ownerRef(r.owners?.owners?.[0]), system: form.system ?? "" };
  const set = (k: string) => (x: string) => setForm({ ...form, [k]: x });
  const yaml = catalogYaml(v);
  const link = newFile(r.name, r.default_branch || "main", "catalog-info.yaml", yaml);
  return <Panel title="Add a catalog file" meta={`${count(repos.length, "repo")} without one`}
    foot={<><Button variant="filled" href={link.url} external icon="external" disabled={!v.owner} onClick={onPrefill(link, "Opened on GitHub: press Commit changes there")}>Add catalog-info.yaml to {short_} on GitHub</Button>
      <span class="pn-hint">{link.paste ? PASTE_FILE_BEFORE : "Opens GitHub's editor with the file filled in."} It goes on {r.default_branch || "main"}, or propose it as a pull request. No token needed here; GitHub asks for write access.</span></>}>
    <p>Backstage's format, so Backstage, Port and Cortex read the same file. The owner comes from the repo's CODEOWNERS when it names one.</p>
    <div class="pt-form">
      <Field label="Repo">{(id) => <Select id={id} value={r.name} onChange={(x) => { setName(x); setForm({}); }} options={repos.map((x) => ({ value: x.name, label: x.name }))} />}</Field>
      <Field label="Name" hint="Lowercase letters, digits and dashes.">{(id) => <TextInput id={id} mono value={v.name} onInput={set("name")} />}</Field>
      <Field label="Title">{(id) => <TextInput id={id} value={v.title} onInput={set("title")} placeholder={short_} />}</Field>
      <Field label="Description">{(id) => <TextInput id={id} value={v.description} onInput={set("description")} maxLength={200} />}</Field>
      <Field label="Type">{(id) => <Select id={id} value={v.type} onChange={set("type")} options={TYPES.map((t) => ({ value: t, label: t }))} />}</Field>
      <Field label="Lifecycle">{(id) => <Select id={id} value={v.lifecycle} onChange={set("lifecycle")} options={LIFECYCLES.map((t) => ({ value: t, label: t }))} />}</Field>
      <Field label="Owner" hint="group:team or user:name" error={v.owner ? null : "Name an owner"}>{(id) => <TextInput id={id} mono value={v.owner} onInput={set("owner")} placeholder="group:team" />}</Field>
      <Field label="System" hint="Optional: the larger thing it belongs to.">{(id) => <TextInput id={id} mono value={v.system} onInput={set("system")} />}</Field>
    </div>
    <CodeBlock title="catalog-info.yaml" code={yaml} />
  </Panel>;
}

export function Catalog({ repos }: { repos: Full[] }) {
  const files = repos.filter((r) => r.descriptor?.present);
  const without = repos.filter((r) => !r.descriptor?.present && !r.name.toLowerCase().endsWith("/.github"));
  const rows = files.flatMap((r) => (r.descriptor!.entities || []).map((e) => ({ ...e, repo: r.name })));
  const problems = files.flatMap((r) => (r.descriptor!.problems || []).map((p) => ({ repo: r.name, problem: p })));
  return <>
    <Stats>
      <Stat label="Entities" value={rows.length} />
      <Stat label="Repos with a catalog file" value={`${files.length} of ${repos.length}`} />
      <Stat label="Problems in catalog files" value={problems.length} />
    </Stats>
    {rows.length ? <Table name="catalog" caption="Catalog" rows={rows} columns={[
      { key: "name", label: "Entity", primary: true, render: (e) => <><b>{e.title || e.name}</b>{e.description ? <div class="muted small">{short(e.description, 90)}</div> : null}</> },
      { key: "kind", label: "Kind", filter: true, raw: (e) => e.kind || "" },
      { key: "system", label: "System", filter: true, raw: (e) => e.system || "", render: (e) => e.system || "–" },
      { key: "type", label: "Type", filter: true, raw: (e) => e.type || "", render: (e) => e.type || "–" },
      { key: "lifecycle", label: "Lifecycle", filter: true, raw: (e) => e.lifecycle || "", render: (e) => e.lifecycle || "–" },
      { key: "owner", label: "Owner", raw: (e) => e.owner || "", render: (e) => <><span class="mono-soft">{e.owner || "–"}</span>{e.owner_check ? <div><Pill tone={e.owner_check[0] === "pass" ? "good" : "watch"}>
        {e.owner_check[0] === "pass" ? "In CODEOWNERS" : "Not in CODEOWNERS"}</Pill></div> : null}</> },
      { key: "depends_on", label: "Depends on", raw: (e) => (e.depends_on || []).join(" "), render: (e) => short((e.depends_on || []).map((x) => x.split("/").pop()).join(", "), 60) || "–" },
      { key: "apis", label: "APIs", raw: (e) => apis(e as Ent), render: (e) => short(apis(e as Ent), 60) || "–" },
      { key: "tags", label: "Tags", filter: true, raw: (e) => ((e as Ent).tags || []).join(" "), render: (e) => ((e as Ent).tags || []).join(", ") || "–" },
      { key: "repo", label: "Repo", render: (e) => ghr(e.repo) }]} />
      : <Card><EmptyState icon="portal" title="No repo has a catalog-info.yaml yet." /></Card>}
    {problems.length ? <><h3 class="sub-h">Problems in catalog files</h3><Table name="catalog-problems" caption="Catalog problems" search={false} rows={problems}
      columns={[{ key: "repo", label: "Repo", primary: true, render: (x) => ghr(x.repo) }, { key: "problem", label: "Problem" }]} /></> : null}
    {without.length ? <CatalogStarter repos={without} /> : null}
  </>;
}

// Every repo's docs/ pages in one searchable list; GitHub renders each page.
const DOC = /\.(md|mdx|rst|adoc|txt)$/i;
export function Docs({ repos }: { repos: PortalRepo[] }) {
  const rows = repos.flatMap((r) => (r.doc_pages || []).filter((n) => DOC.test(n) || !n.includes("."))
    .map((n) => ({ page: n.replace(DOC, "").replace(/[-_]+/g, " ").replace(/^./, (c) => c.toUpperCase()), file: n, repo: r.name, folder: !n.includes(".") })));
  if (!rows.length) return <Card><EmptyState icon="portal" title="No repo has a docs/ folder yet.">Pages in each repo's <code class="code-inline">docs/</code> folder are listed here once the next run reads them.</EmptyState></Card>;
  return <><Stats>
      <Stat label="Pages and folders" value={rows.length} />
      <Stat label="Repos with docs/" value={`${new Set(rows.map((x) => x.repo)).size} of ${repos.length}`} />
    </Stats>
    <Table name="docs" caption="Docs pages" rows={rows} columns={[
      { key: "page", label: "Page", primary: true, render: (x) => <a href={`https://github.com/${x.repo}/${x.folder ? "tree" : "blob"}/HEAD/docs/${x.file}`} {...ext}>{x.page}</a> },
      { key: "kind", label: "Kind", filter: true, raw: (x) => (x.folder ? "Folder" : "Page") },
      { key: "file", label: "File", nowrap: true, render: (x) => <span class="mono-soft">docs/{x.file}</span> },
      { key: "repo", label: "Repo", filter: true }]} /></>;
}

export function Rules({ repos }: { repos: PortalRepo[] }) {
  const rules: Record<string, { id: string; level?: string; pass: number; fail: number; exempt: number; preview: number; na: number }> = {};
  for (const r of repos) for (const x of r.score?.results || []) {
    const row = (rules[x.id] ||= { id: x.id, level: x.level, pass: 0, fail: 0, exempt: 0, preview: 0, na: 0 });
    row[(["pass", "fail", "exempt", "preview"].includes(x.result || "") ? x.result : "na") as "na"]++;
  }
  return <Table name="rules" caption="Rules" rows={Object.values(rules)} initialSort={{ key: "fail", desc: true }} columns={[
    { key: "id", label: "Rule", primary: true, nowrap: true, render: (x) => <span class="mono-soft">{x.id}</span> },
    { key: "level", label: "Level", filter: true, render: (x) => <StatePill value={x.level} /> },
    { key: "fail", label: "Failing", num: true, render: (x) => <b>{x.fail}</b> }, { key: "pass", label: "Passing", num: true },
    { key: "exempt", label: "Exempt", num: true }, { key: "preview", label: "Not counted yet", num: true }, { key: "na", label: "Can't check", num: true },
    { key: "share", label: "Passing share", num: true, raw: (x) => (x.pass + x.fail ? x.pass / (x.pass + x.fail) : null), render: (x) => { const s = x.pass / Math.max(1, x.pass + x.fail);
      return <span class="pt-meter" role="img" aria-label={pct(s)}><span class="pt-track"><i style={{ width: `${s * 100}%` }} /></span><span class="num">{pct(s)}</span></span>; } }]} />;
}

export function Golden({ app, p, repos }: { app: AppJson; p: PortalFull; repos: PortalRepo[] }) {
  const [inputs, setInputs] = useState<Record<string, Record<string, string>>>({});
  const paths = p.golden || [];
  if (!paths.length) return <Card><EmptyState icon="setup" title="No golden paths.">Add <code class="code-inline">[[golden_path]]</code> entries to the portal repo's <code class="code-inline">portal.toml</code>:
    a template repo to start from, or a folder of standard files to add to a repo.</EmptyState></Card>;
  const set = (id: string, k: string, v: string) => setInputs({ ...inputs, [id]: { ...(inputs[id] || {}), [k]: v } });
  return <div class="pt-grid">{!p.golden_ready ? <Panel title="Golden paths need the org App" tone="watch"
      foot={<Button variant="tinted" href={appLink(p.org || app.repo.split("/")[0]!, true)} external icon="external">Create the App on GitHub</Button>}>
      <p>Golden paths create repos and open pull requests, so they run with an org App that may write. The button opens GitHub's App form with
        the permissions filled in; then save its client ID as the variable PORTAL_CLIENT_ID, its key as the secret PORTAL_PRIVATE_KEY, and switch on
        the token step (Portal outside the app, below, has the file).</p></Panel> : null}
    {paths.map((g) => {
      const mine = inputs[g.id] || {};
      const ready = g.kind === "repo" ? /^[A-Za-z0-9._-]{1,100}$/.test(mine.name || "") : !!mine.repo;
      const req = { version: 1, changes: [], settings: {}, golden: { path: g.id, inputs: mine } } as Req;
      return <Panel title={g.title} meta={g.kind === "repo" ? `Creates a new ${g.private ? "private" : "public"} repo` : "Opens a pull request"}>
        {g.description ? <p>{g.description}</p> : null}
        <div class="pt-form">{g.kind === "repo" ? <>
          <Field label="Name" hint="Letters, numbers, dots, dashes and underscores.">{(id) => <TextInput id={id} value={mine.name || ""} onInput={(v) => set(g.id, "name", v)} />}</Field>
          <Field label="Description">{(id) => <TextInput id={id} value={mine.description || ""} onInput={(v) => set(g.id, "description", v)} />}</Field></>
          : <Field label="Repo">{(id) => <Select id={id} value={mine.repo || ""} onChange={(v) => set(g.id, "repo", v)}
            options={[{ value: "", label: "Choose a repo" }, ...repos.map((r) => ({ value: r.name, label: r.name }))]} />}</Field>}</div>
        {ready ? <Send app={app} title={`Golden path: ${g.title}`} req={req} who="people with write access to the portal repo"
          lands={g.kind === "repo" ? `a new repo in ${p.org}` : `a pull request in ${mine.repo}`} when="on the next portal run, a minute or two" />
          : <p class="field-hint">{g.kind === "repo" ? "Name the new repo to send the request." : "Choose the repo to send the request."}</p>}
      </Panel>;
    })}</div>;
}

const NAMES: Record<string, string> = { ci_flaky: "Flaky checks", ci_broken: "Broken checks", stale_prs: "Stale PRs", findings: "Open findings",
  newcomers_waiting: "Newcomers waiting", pickup_p75_h: "Pickup, P75 hours", review_p75_h: "Review, P75 hours",
  cycle_p75_h: "Cycle to merge, P75 hours", change_failure_rate: "Change fail rate", vulns_serious: "Critical or high vulnerabilities, or malware" };
export function Org({ o }: { o: PortalFull["org_view"] }) {
  if (!o || !o.running) return <Card><EmptyState icon="portal" title="No repo here runs the suite yet.">Once repos run StackVitals, their CI, review and delivery numbers roll up here.</EmptyState></Card>;
  const m = o.medians, t = o.totals;
  const h = (v: Num) => (v === null || v === undefined ? "–" : `${Math.round(v * 10) / 10} h`);
  const val = (k: string, v: number) => (k === "change_failure_rate" ? pct(v) : k.endsWith("_h") ? h(v) : v);
  return <>
    <Stats>
      <Stat label="Repos running the suite" value={`${o.running} of ${o.repos}`} />
      <Stat label="First-try green, median repo" value={pct(m.ci_first_try)} note={`${o.counts.ci_first_try ?? 0} repos`} />
      <Stat label="Flaky checks" value={t.ci_flaky ?? "–"} note={`${t.ci_broken ?? 0} broken`} />
      <Stat label="Open PRs" value={t.open_prs ?? "–"} note={`${t.stale_prs ?? 0} stale`} />
      <Stat label="Pickup, median repo's P75" value={h(m.pickup_p75_h)} note={`review ${h(m.review_p75_h)}`} />
      <Stat label="Deployments" value={t.deployments ?? "–"} note={m.change_failure_rate === null || m.change_failure_rate === undefined ? null : `change fail rate ${pct(m.change_failure_rate)} (median repo)`} />
      <Stat label="Known vulnerabilities" value={t.vulns_open ?? "–"} note={t.vulns_serious === null || t.vulns_serious === undefined ? null : `${t.vulns_serious} critical, high or malware`} />
    </Stats>
    <h3 class="sub-h">Where each number is highest</h3>
    <div class="pt-leaders">{Object.entries(NAMES).filter(([k]) => (o.leaders[k] || []).length).map(([k, label]) => <Panel title={label} meta={count(o.leaders[k]!.length, "repo")} flush>
      <table class="pt-mini"><thead><tr><th scope="col">Repo</th><th scope="col" class="is-num">{k === "change_failure_rate" ? "Rate" : k.endsWith("_h") ? "Hours" : "Count"}</th></tr></thead>
        <tbody>{o.leaders[k]!.map((x) => <tr><td>{ghr(x.repo)}</td><td class="is-num num">{val(k, x.value)}</td></tr>)}</tbody></table>
    </Panel>)}</div>
  </>;
}

type Campaign = NonNullable<PortalFull["campaigns"]>[number] & { days_left?: number | null };
export function Campaigns({ list }: { list: Campaign[] }) {
  if (!list.length) return <Card><EmptyState icon="portal" title="No campaigns.">A campaign is a set of rules, the repos it targets and a date, in the portal repo's <code class="code-inline">portal.toml</code>.</EmptyState></Card>;
  return <div class="pt-grid">{list.map((c) => {
    const done = c.passing === c.targets, ended = c.days_left != null && c.days_left < 0;
    const left = c.days_left == null ? "–" : c.days_left < 0 ? `Ended ${count(-c.days_left, "day")} ago` : c.days_left === 0 ? "Ends today" : count(c.days_left, "day");
    return <Panel title={c.title} tone={done ? "good" : ended ? "bad" : "watch"} meta={done ? <Pill tone="good">Every repo passes</Pill> : <Pill tone={ended ? "bad" : "watch"}>{count((c.targets ?? 0) - (c.passing ?? 0), "repo")} still failing</Pill>}>
      <Facts rows={[["Passing", <span class="num">{c.passing ?? "–"} of {c.targets ?? "–"}</span>], ["Until", c.until ? day(c.until) : "No date"], ["Days left", left]]} />
      <Columns>
        <div><h4 class="pt-h4">Repos still failing, by day</h4><BarChart label={`${c.title}: repos still failing by day`} height={160} bars={(c.burn_down || []).map(([d, v]) => ({ label: dateLabel(d), value: v, tone: "accent" as const }))} /></div>
        <div><h4 class="pt-h4">Still failing</h4>{(c.failing || []).length ? <ul class="pt-fail">{(c.failing || []).slice(0, 30).map((x) => <li>{ghr(x)}</li>)}</ul> : <p class="muted">None.</p>}</div>
      </Columns>
    </Panel>;
  })}</div>;
}
