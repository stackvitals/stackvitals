// Dependencies tools: the code scanning upload as a one-click new workflow file, "check a package" answered from this
// repo's files, the lockfile scan (machine only) and the workflow steps that fill the "Your code" column.
import { useState } from "preact/hooks";
import type { AppJson, DepsFull, SupplyJson, VulnsJson } from "../../data/types";
import { Button, safeHref } from "../../ui/Button";
import { CodeBlock, CopyButton, EmptyState, Pill } from "../../ui/bits";
import { Field, Select, TextInput } from "../../ui/controls";
import { Table } from "../../ui/Table";
import { AddFile, Facts, Panel } from "./blocks";
import { checkCommand, knownNames, lookup, parseSpec, type Hit } from "./lookup";
import { SCAN_BRANCH, SCAN_FILE, editLink, scanningWorkflow, yourCodeSteps, type CodeTool } from "./scanning";

type F = { deps?: DepsFull | null; supply?: SupplyJson | null; vulns?: VulnsJson | null };

export function CodeScanning({ app, sast }: { app: AppJson; sast?: string[] }) {
  const content = scanningWorkflow(app.repo);
  return <Panel title="Show findings in GitHub's Security tab" state={<Pill tone="neutral" icon={null}>a new workflow file</Pill>}>
    <Facts rows={[
      ["What it adds", <span class="mono-soft">{SCAN_FILE}</span>],
      ["When it runs", "After each StackVitals run on the default branch, or by hand"],
      ["What it uploads", "Known vulnerabilities (vulns.sarif) and the security checks (security.sarif)"],
      ["Where they show", "Security tab, Code scanning, beside CodeQL's alerts"],
      ["Private repos", app.visibility === "private" ? "Needs GitHub Code Security on this repo" : "Needs GitHub Code Security (public repos have it free)"],
      (sast || []).length ? ["Code scanning here now", (sast || []).join(", ")] : null,
    ]} />
    <p>Each run already writes both files to the stackvitals-data branch. This workflow reads them there and uploads them; your own code is never checked out.</p>
    <AddFile app={app} needs="Contents, Pull requests and Workflows: read and write"
      f={{ file: SCAN_FILE, content, branch: SCAN_BRANCH, message: "Upload StackVitals findings to code scanning", title: "Show StackVitals findings in code scanning",
        body: `Adds \`${SCAN_FILE}\`, made in the StackVitals app. After each StackVitals run it uploads the known vulnerabilities and security checks from the stackvitals-data branch to code scanning (it needs security-events: write).` }} />
  </Panel>;
}

const HIT_COLS = [
  { key: "area", label: "Found in", filter: true, primary: true },
  { key: "where", label: "Item", raw: (h: Hit) => h.where,
    render: (h: Hit) => (h.href ? <a href={safeHref(h.href)} target="_blank" rel="noopener noreferrer">{h.where}</a> : h.where) },
  { key: "state", label: "State", raw: (h: Hit) => h.state, render: (h: Hit) => <Pill tone={h.tone} icon={null}>{h.state}</Pill> },
  { key: "detail", label: "Detail", raw: (h: Hit) => h.detail },
];

// In the app: what this repo's files say about one package. The verdict (use, monitor, investigate) needs the CLI.
export function CheckPackage({ app, f }: { app: AppJson; f: F }) {
  const names = knownNames(f);
  const [spec, setSpec] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const hits = asked ? lookup(asked, f, app.repo) : [];
  const go = (s = spec) => { if (s.trim()) setAsked(s.trim()); };
  const shown = asked ? parseSpec(asked).name : "";
  return <Panel title="Check a package" state={<Pill tone="good" icon={null}>in the app</Pill>}>
    <form class="blk-form dp-check-form" onSubmit={(e) => { e.preventDefault(); go(); }}>
      <Field label="Package name" hint="A name like lodash, or npm:lodash and pypi:requests to name the ecosystem.">{(id) =>
        <TextInput id={id} mono value={spec} onInput={setSpec} placeholder="lodash" maxLength={200} />}</Field>
      <div class="dp-form-go"><Button type="submit" variant="filled" icon="search" disabled={!spec.trim()}>Check it</Button></div>
    </form>
    {names.length ? <p class="blk-how">Flagged in this repo: {names.slice(0, 12).map((n, i) => <>{i ? ", " : ""}<button type="button" class="blk-link mono-soft" onClick={() => { setSpec(n); go(n); }}>{n}</button></>)}{names.length > 12 ? ` and ${names.length - 12} more` : ""}.</p> : null}
    {asked ? <div class="blk-out" aria-live="polite">
      {hits.length ? <Table name="package-check" caption={`What this repo's files say about ${shown}`} search={false} rows={hits} columns={HIT_COLS} />
        : <EmptyState icon="check" title={`Nothing flagged for ${shown}.`}>No open vulnerability, update pull request, licence rule, licence change or Scorecard drop names it here.
          These files list only packages with a finding, so this can't say whether the repo uses it.</EmptyState>}
    </div> : null}
    <p class="blk-how">Answered from this repo's own files (vulnerabilities, update pull requests, supply chain), no token and nothing sent.</p>
    {asked ? <CodeBlock inline code={checkCommand(asked)} note="The verdict (use, monitor or investigate) weighs the public crawl's upgrade outcomes and maintainer history, which the app doesn't load, so it runs from your machine." /> : null}
  </Panel>;
}

// Scanning a lockfile needs the crawl's evidence and the lockfile parsers, which run in Python: a command per lockfile.
export function ScanLockfile({ v }: { v?: VulnsJson | null }) {
  const files = v?.files || [];
  const [file, setFile] = useState(files[0] || "package-lock.json");
  const cmd = `stackvitals deps scan ${/\s/.test(file) ? JSON.stringify(file) : file}`;
  return <Panel title="Scan a lockfile" state={<Pill tone="neutral" icon={null}>from your machine</Pill>}>
    <p>Every package in a lockfile with a verdict, the ones to look at first on top. It runs on your machine because it reads a lockfile you haven't pushed yet
      and weighs the public crawl's evidence, which the app doesn't load.</p>
    {files.length ? <Field label="Lockfile" hint="The lockfiles the last scan read in this repo.">{(id) =>
      <Select id={id} value={file} onChange={setFile} options={files.map((x) => ({ value: x, label: x }))} />}</Field> : null}
    <CodeBlock inline code={cmd} note="Add --all to list the packages with a use verdict too, --json for the raw evidence. pip install stackvitals first." />
    <p class="blk-how">In the repo this already happens by itself: a pull request that changes a lockfile gets the dependency check from the StackVitals workflow.</p>
  </Panel>;
}

const TOOL_FOR: Record<string, CodeTool | null> = { go: "govulncheck", npm: "imports", pypi: "imports", cargo: "imports", "crates.io": "imports", maven: null, nuget: null };

// The steps that fill "Your code": an edit to the existing workflow file, so GitHub's editor opens on it with the steps to paste.
export function YourCode({ app, v, s }: { app: AppJson; v?: VulnsJson | null; s?: SupplyJson | null }) {
  const ecos = new Set([...(v?.open || []).map((x) => (x.ecosystem || "").toLowerCase()), ...Object.keys(s?.systems || {}).map((k) => k.toLowerCase())]);
  const guess: CodeTool = ecos.has("go") ? "govulncheck" : "imports";
  const [tool, setTool] = useState<CodeTool>(guess);
  const unsupported = [...ecos].filter((e) => e && e !== "actions" && TOOL_FOR[e] === null);
  const { steps, input } = yourCodeSteps(tool);
  const wf = `.github/workflows/${app.links?.workflow || "stackvitals.yml"}`;
  const branch = app.default_branch || "main";
  const done = tool === "govulncheck" ? !!s?.reachability?.findings?.length : (v?.open || []).some((x) => x.imported === true || x.imported === false);
  return <Panel title="Fill the Your code column" state={done ? <Pill tone="good" icon={null}>on</Pill> : <Pill tone="neutral" icon={null}>a workflow edit</Pill>}
    bar={<><Button variant="filled" href={editLink(app.repo, branch, wf)} external icon="external">Edit the workflow on GitHub</Button>
      <CopyButton text={steps} label="Copy the steps" /><CopyButton text={input.trim()} label="Copy the input" /></>}>
    <p>Whether your own code reaches a vulnerable package. It reads your code, so it runs in your workflow: add these steps before the StackVitals step, and the input
      under its <span class="mono-soft">with:</span>. The workflow file already exists, so GitHub's editor opens on it; paste and commit there.</p>
    <Field label="Tool" hint={tool === "govulncheck" ? "Go: call paths from govulncheck (your code calls it, imports it, or only requires it)." : "Python, JavaScript and Rust: whether your code imports the package (an import, not a call path)."}>{(id) =>
      <Select id={id} value={tool} onChange={setTool} options={[{ value: "imports", label: "Imports (Python, JavaScript, Rust)" }, { value: "govulncheck", label: "govulncheck (Go)" }]} />}</Field>
    <CodeBlock title={`Steps for ${wf}`} code={steps} />
    <CodeBlock inline code={input.trim()} note="Under the StackVitals step's with:" />
    {unsupported.length ? <p class="blk-how">No free tool tells this for {unsupported.join(", ")} yet, so those rows stay unknown.</p> : null}
    {tool === "imports" ? <p class="blk-how">The same list from your machine: <span class="mono-soft">stackvitals deps imports . --out imports.json</span>.</p> : null}
  </Panel>;
}
