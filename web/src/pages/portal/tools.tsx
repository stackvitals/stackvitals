// Portal's commands done in the app: the owners report (`portal report`), the access check (`portal check`), setting up
// the portal repo (`portal init`, `portal app-link`), and a "From your machine" panel for what needs your own terminal.
import { useState } from "preact/hooks";
import { count } from "../../data/format";
import { useStore } from "../../data/store";
import type { AppJson, PortalFull } from "../../data/types";
import { makeApi } from "../../github/client";
import { account } from "../../github/token";
import { PASTE_FILE_BEFORE, newFile, type PrefillLink } from "../../github/links";
import { Button } from "../../ui/Button";
import { CodeBlock, Pill } from "../../ui/bits";
import { PasteNote, onPrefill } from "../../ui/prefill";
import { Field, SegmentedControl, TextInput } from "../../ui/controls";
import { Stat, Stats } from "../../ui/Page";
import { Table } from "../../ui/Table";
import { checkAccess, type Line } from "./access";
import { Facts, Panel, Steps } from "./panel";
import { ext, ghr, levelPill, ownersPill, type Full } from "./parts";
import { PORTAL_FILE, appLink, codeowners, newRepoLink, portalWorkflow } from "./setup";

const isShared = (r: Full) => r.name.split("/").pop()!.toLowerCase() === ".github";

// `stackvitals portal report`: every active repo's level and owners with the evidence, from the published catalog.
export function OwnersReport({ repos }: { repos: Full[] }) {
  const active = repos.filter((r) => !r.archived && !r.fork);
  const judged = active.filter((r) => !isShared(r));
  const n = (s: string) => judged.filter((r) => r.owners?.status === s).length;
  const fixLink = (r: Full): { label: string; href: string; link?: PrefillLink } | null => {
    const o = r.owners;
    if (o?.status === "none" && o.suggested?.length) {
      const link = newFile(r.name, r.default_branch || "main", ".github/CODEOWNERS", codeowners(o.suggested));
      return { label: "Add CODEOWNERS", href: link.url, link };
    }
    if (o?.status === "weak" && o.file) return { label: "Edit CODEOWNERS", href: `https://github.com/${r.name}/edit/${encodeURIComponent(r.default_branch || "main")}/${o.file}` };
    return null;
  };
  return <>
    <Stats>
      <Stat label="Active repos" value={active.length} note={`${repos.length - active.length} archived or forks, listed but not checked`} />
      <Stat label="Owners valid" value={n("valid")} />
      <Stat label="Owners weak" value={n("weak")} />
      <Stat label="No owners" value={n("none")} />
    </Stats>
    <Table name="owners-report" caption="Owners report" rows={active} initialSort={{ key: "owners", desc: false }} columns={[
      { key: "name", label: "Repo", primary: true, render: (r) => ghr(r.name) },
      { key: "level", label: "Level", filter: true, raw: (r) => (isShared(r) ? "not judged" : r.score?.level || "below bronze"), render: (r) => (isShared(r) ? <span class="muted">Not judged</span> : levelPill(r.score?.level)) },
      { key: "owners", label: "Owners", filter: true, raw: (r) => (isShared(r) ? "not judged" : r.owners?.status || "not checked"), render: (r) => (isShared(r) ? <span class="muted">Not judged</span> : ownersPill(r.owners?.status)) },
      { key: "who", label: "Named in CODEOWNERS", raw: (r) => (r.owners?.owners || []).join(" "), render: (r) => (r.owners?.owners?.length ? <span class="mono-soft">{r.owners.owners.join(", ")}</span> : "–") },
      { key: "why", label: "Evidence", raw: (r) => (isShared(r) ? "the org's shared settings repo" : (r.owners?.reasons || []).join("; ")),
        render: (r) => (isShared(r) ? "The org's shared settings repo" : (r.owners?.reasons || []).join("; ") || (r.owners?.file ? `${r.owners.file} names an owner for every file` : "–")) },
      { key: "suggested", label: "Suggested", raw: (r) => (r.owners?.suggested || []).join(" "), render: (r) => (r.owners?.suggested?.length
        ? <><span class="mono-soft">{r.owners.suggested.join(", ")}</span><div class="muted small">from {r.owners.suggested_from || "recent commits"}</div></> : "–") },
      { key: "fix", label: "Fix", raw: () => "", render: (r) => { const f = fixLink(r); return f ? <Button size="sm" variant="tinted" href={f.href} external iconEnd="external" {...(f.link ? { onClick: onPrefill(f.link, "Opened on GitHub: press Commit changes there") } : {})}>{f.label}</Button> : "–"; } }]} />
    <p class="muted small">Add CODEOWNERS opens GitHub's editor with a file naming the suggested people; Edit opens the existing file. Either way you commit on GitHub, with your own access.</p>
  </>;
}

// What the last portal run could read, from catalog.json alone (no token needed).
function LastRun({ p, repos }: { p: PortalFull & { complete?: boolean }; repos: Full[] }) {
  const priv = repos.filter((r) => r.private).length;
  const owners = repos.filter((r) => r.owners?.status).length;
  const prot = repos.filter((r) => r.protected !== null && r.protected !== undefined).length;
  const props = repos.filter((r) => r.properties && Object.keys(r.properties).length).length;
  const na = repos.reduce((s, r) => s + (r.score?.not_available || 0), 0);
  const errs = repos.filter((r) => r.error);
  const line = (what: string, ok: boolean | null, detail: string) => ({ what, ok, detail });
  const rows: Line[] = [
    line("Repos", repos.length > 0, `${repos.length} read (${priv} private), ${p.mode || "?"} mode${p.mode === "public" ? ": public repos only" : ""}`),
    line("CODEOWNERS", owners === repos.length, `checked in ${owners} of ${repos.length}`),
    line("Branch protection", prot === repos.length ? true : prot ? null : false, `readable in ${prot} of ${repos.length}`),
    line("Custom properties", props ? true : null, props ? `set on ${props} repos` : "none read (none set, or not readable)"),
    line("Scorecard rules", na ? null : true, na ? `${count(na, "rule")} couldn't be read (published Scorecards cover public repos only)` : "every rule could be read"),
    line("Finished", errs.length || p.complete === false ? null : true, errs.length ? `stopped on ${errs.map((r) => r.name).join(", ")}; their facts are from the run before` : p.complete === false ? "not every repo was checked yet; the next run continues" : "every repo was checked"),
  ];
  return <AccessTable rows={rows} name="portal-last-run" />;
}

const AccessTable = ({ rows, name }: { rows: Line[]; name: string }) => <Table name={name} search={false} rows={rows.map((r, i) => ({ ...r, id: i }))} columns={[
  { key: "what", label: "What", primary: true },
  { key: "ok", label: "Result", raw: (r) => (r.ok ? "readable" : r.ok === false ? "not readable" : "partly"),
    render: (r) => <Pill tone={r.ok ? "good" : r.ok === false ? "bad" : "watch"}>{r.ok ? "Readable" : r.ok === false ? "Not readable" : "Partly"}</Pill> },
  { key: "detail", label: "Detail" }]} />;

// `stackvitals portal check ORG` in the browser, with the signed-in account, a pasted token, or none (public data only).
export function AccessCheck({ org, p, repos }: { org: string; p: PortalFull | null; repos: Full[] }) {
  const acc = useStore(account);
  const [name, setName] = useState(org);
  const [how, setHow] = useState<"account" | "paste" | "none">(acc ? "account" : "paste");
  const [pasted, setPasted] = useState("");
  const [state, setState] = useState<{ busy?: boolean; lines?: Line[]; error?: string; as?: string } | null>(null);
  const tok = how === "account" ? acc?.token : how === "paste" ? pasted : undefined;
  const run = async () => {
    setState({ busy: true });
    try {
      const lines = await checkAccess(makeApi(tok || null), name.trim());
      setState({ lines, as: how === "none" ? "without a token" : how === "account" ? `as ${acc?.login || "your account"}` : "with the pasted token" });
    } catch (e) { setState({ error: (e as Error).message }); }
  };
  const ready = /^[A-Za-z0-9-]{1,39}$/.test(name.trim()) && (how !== "paste" || !!pasted);
  return <div class="pt-grid">
    {p ? <Panel title="What the last run could read" meta="from catalog.json, no token needed" flush><LastRun p={p} repos={repos} /></Panel> : null}
    <Panel title="Check a token's access" meta="what stackvitals portal check does"
      foot={<><Button variant="filled" icon="check" loading={state?.busy} disabled={!ready} onClick={run}>Check {name.trim() || "the org"}</Button>
        <span class="pn-hint">Read-only: about six requests to api.github.com from this browser; nothing is written and the token isn't kept.</span></>}>
      <p>Before a first run, or after changing the org App: see what a token can read in the org. The portal workflow reads with its own token
        (the built-in one for public repos, the org App's for private ones), so check with a token like the one it will use.</p>
      <div class="pt-form">
        <Field label="Org or user">{(id) => <TextInput id={id} mono value={name} onInput={(v) => setName(v.trim())} />}</Field>
        <div class="field"><span class="field-label">Read as</span>
          <SegmentedControl label="Read as" value={how} onChange={setHow} scroll options={[
            ...(acc ? [{ value: "account" as const, label: `Signed in${acc.login ? ` (${acc.login})` : ""}` }] : []),
            { value: "paste" as const, label: "A token" }, { value: "none" as const, label: "No token" }]} /></div>
        {how === "paste" ? <Field label="Token" hint="A fine-grained token for the org with read access to Contents, Metadata, Members and Custom properties, or a classic one with repo and read:org. Kept only until you leave the page.">{(id) =>
          <TextInput id={id} type="password" mono value={pasted} onInput={(v) => setPasted(v.trim())} placeholder="github_pat_…" />}</Field> : null}
        {how === "none" ? <p class="field-hint">Without a token GitHub shows public data only, 60 requests an hour.</p> : null}
      </div>
      <div role="status">{state?.lines ? <><p class="pt-result-h">{name} {state.as}</p><AccessTable rows={state.lines} name="portal-check" /></> : null}</div>
      <div role="alert">{state?.error ? <p class="note note-bad"><span>Not checked: {state.error}.</span></p> : null}</div>
    </Panel>
  </div>;
}

// The portal workflow file, with or without the org App's token step, and the one-click ways to put it in place.
function WorkflowFile({ org, repo, branch, exists, workflow }: { org: string; repo: string; branch: string; exists: boolean; workflow?: string | null }) {
  const [priv, setPriv] = useState<"public" | "private">("public");
  const yaml = portalWorkflow({ app: priv === "private" });
  const file = workflow && /portal/i.test(workflow) ? `.github/workflows/${workflow}` : PORTAL_FILE;
  const link = newFile(repo, branch, PORTAL_FILE, yaml);
  return <Panel title={exists ? "The portal workflow" : "The portal workflow file"} meta={<span class="mono-soft">{file}</span>}
    foot={<>{exists ? <Button variant="tinted" href={`https://github.com/${repo}/edit/${encodeURIComponent(branch)}/${file}`} external icon="external">Edit it on GitHub</Button>
      : <Button variant="filled" href={link.url} external icon="external" onClick={onPrefill(link, "Opened on GitHub: press Commit changes there")}>Add it to {repo}</Button>}
      {priv === "private" ? <Button variant="plain" href={appLink(org)} external iconEnd="external">Create the read-only App</Button> : null}
      <span class="pn-hint">{exists ? "Copy the file below, then paste it over the old one in GitHub's editor and commit; the next run uses it."
        : link.paste ? "No token needed here." : "Opens GitHub's editor with the file filled in; commit it there. No token needed here."}</span></>}>
    {exists ? null : <PasteNote link={link} />}
    <div class="field"><span class="field-label">Repos to read</span>
      <SegmentedControl label="Repos to read" value={priv} onChange={setPriv} options={[{ value: "public", label: "Public repos" }, { value: "private", label: "Private repos too" }]} /></div>
    <p>{priv === "public" ? "With the built-in token the workflow reads the org's public repos; nothing else to set up."
      : "Private repos need an org-owned GitHub App with read-only permissions: create it, install it on the org's repos, save its client ID as the variable PORTAL_CLIENT_ID and a private key as the secret PORTAL_PRIVATE_KEY in the portal repo. This file already has the App's token step switched on."}</p>
    <CodeBlock title={file} code={yaml} />
  </Panel>;
}

// No portal yet: create the org's portal repo and its workflow, each one click on GitHub.
export function SetupPortal({ app }: { app: AppJson | null }) {
  const [org, setOrg] = useState(app?.repo?.split("/")[0] || "");
  const [name, setName] = useState("portal");
  const ok = /^[A-Za-z0-9-]{1,39}$/.test(org) && /^[A-Za-z0-9._-]{1,100}$/.test(name);
  const repo = `${org || "my-org"}/${name}`;
  const wfLink = newFile(repo, "main", PORTAL_FILE, portalWorkflow());
  return <div class="pt-grid">
    <Panel title="Set up Portal for an org" meta="about five minutes, no token here">
      <p>Portal runs once a day in a repo of its own and keeps the org's catalog, owners and scorecards on that repo's stackvitals-data branch,
        which only people who can read the repo can open.</p>
      <div class="pt-form">
        <Field label="Org">{(id) => <TextInput id={id} mono value={org} onInput={(v) => setOrg(v.trim())} placeholder="my-org" />}</Field>
        <Field label="Portal repo name" hint="Private is best.">{(id) => <TextInput id={id} mono value={name} onInput={(v) => setName(v.trim())} />}</Field>
      </div>
    </Panel>
    <Panel title="Steps" flush>
      <Steps items={[
        { title: "Create the portal repo", text: <>GitHub's new-repo form, filled in: <span class="mono-soft">{repo}</span>, private. Tick "Add a README" so it has a main branch.</>,
          action: <Button variant="filled" disabled={!ok} href={newRepoLink(org, name)} external icon="external">Create it on GitHub</Button> },
        { title: "Add the workflow", text: <>{wfLink.paste ? PASTE_FILE_BEFORE : "GitHub's editor opens with the portal workflow in it; commit it on main."} For private repos, use the file in the next panel instead.</>,
          action: <Button variant="tinted" disabled={!ok} href={wfLink.url} external icon="external" onClick={onPrefill(wfLink, "Opened on GitHub: press Commit changes there")}>Add the workflow</Button> },
        { title: "Run it", text: "It runs daily; start the first run from the Actions tab (Run workflow). Then open this app on the portal repo.",
          action: <Button variant="plain" disabled={!ok} href={`https://github.com/${repo}/actions`} external iconEnd="external">Open Actions</Button> },
      ]} />
    </Panel>
    {ok ? <WorkflowFile org={org} repo={repo} branch="main" exists={false} /> : null}
    <AccessCheck org={org} p={null} repos={[]} />
    <FromMachine org={org || "my-org"} />
  </div>;
}

// The files the workflow writes, the workflow itself, the org App, and the terminal commands.
export function Outside({ app, p }: { app: AppJson; p: PortalFull }) {
  const org = p.org || app.repo.split("/")[0]!;
  const blob = (f: string) => `https://github.com/${app.repo}/blob/stackvitals-data/portal/${f}`;
  const files = [["catalog.json", "Every fact on this page, one record per repo"], ["README.md", "The same as a Markdown table, readable on GitHub"],
    ["entities.yaml", "A Backstage Component for each repo without its own catalog file: register its URL as one location"],
    ["history/", "One file a day; the campaign bars are drawn from it"]].map(([file, what]) => ({ id: file!, file: file!, what: what! }));
  return <div class="pt-grid">
    <Panel title="Files the portal workflow writes" meta={<>on the <span class="mono-soft">stackvitals-data</span> branch, <span class="mono-soft">portal/</span></>} flush>
      <Table name="portal-files" search={false} rows={files} columns={[
        { key: "file", label: "File", primary: true, nowrap: true, render: (x) => <a class="mono-soft" href={x.file.endsWith("/") ? blob(x.file).replace("/blob/", "/tree/") : blob(x.file)} {...ext}>portal/{x.file}</a> },
        { key: "what", label: "What it holds" }]} />
    </Panel>
    <WorkflowFile org={org} repo={app.repo} branch={app.default_branch || "main"} exists workflow={app.links?.workflow} />
    <Panel title="Org App" meta={p.mode === "private" ? <Pill tone="good">Private mode is on</Pill> : <Pill tone="neutral" icon={null}>Public repos only</Pill>}
      foot={<><Button variant="tinted" href={appLink(org)} external icon="external">Read-only App</Button>
        <Button variant="plain" href={appLink(org, true)} external iconEnd="external">App that may write</Button>
        <span class="pn-hint">Each opens GitHub's App form for {org} with the permissions filled in; an org owner creates it there.</span></>}>
      <Facts rows={[["Read-only", "Private repos in the catalog: Actions, Contents, Metadata, Members and Custom properties, all read"],
        ["May write", "Also golden paths and required checks: checks, contents, pull requests, administration and workflows"]]} cols={2} />
    </Panel>
    <FromMachine org={org} />
  </div>;
}

export function FromMachine({ org }: { org: string }) {
  return <Panel title="From your machine" meta="pip install stackvitals">
    <p>The same check and report with your own token, for any org you can read, before a portal repo exists or for an org this page doesn't show.
      These need a terminal because they read with your token and keep a copy on your computer.</p>
    <CodeBlock inline code={`stackvitals portal check ${org}`} note="What your token can read in the org (repos, CODEOWNERS, branch rules, teams, custom properties)." />
    <CodeBlock inline code={`stackvitals portal report ${org}`} note="Every repo and its owners, with evidence; --json for the whole catalog, --budget to cap API requests, --no-scorecard to skip OpenSSF." />
  </Panel>;
}
