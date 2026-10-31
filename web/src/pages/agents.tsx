// Agents: connect a coding agent to StackVitals' MCP server (a setup card per client: numbered steps and the config to
// copy), what it can ask (every tool in one table), the skills, the editor marker, and what the server reads.
import "./agents.css";
import { useEffect, useState } from "preact/hooks";
import type { PageProps } from "../app/routes";
import { prefs } from "../data/store";
import { Button } from "../ui/Button";
import { CodeBlock, DOCS, PageSkeleton } from "../ui/bits";
import { SegmentedControl } from "../ui/controls";
import { Card, Page, Section } from "../ui/Page";
import { ClientCard, SkillTable, ToolTable } from "./agents/parts";

type Data = typeof import("../features/agents-data");
type Pick = "core" | "all";

function Editor({ repo }: { repo: string }) {
  const [ed, setEd] = useState<"vscode" | "cursor" | "vscodium">("vscode");
  const name = { vscode: "VS Code", cursor: "Cursor", vscodium: "VSCodium" }[ed];
  return <article class="ag-card card ag-editor">
    <header class="ag-strip"><h3>Flaky-test marker</h3>
      <SegmentedControl label="Editor" size="sm" value={ed} onChange={setEd} options={[{ value: "vscode", label: "VS Code" }, { value: "cursor", label: "Cursor" }, { value: "vscodium", label: "VSCodium" }]} /></header>
    <div class="ag-body">
      <p class="ag-why">From your machine: it installs into {name} on your computer, so this page can't do it for you.</p>
      <ol class="ag-steps">
        <li>In a terminal, run the command below.</li>
        <li>Reload {name}.</li>
        <li>Open a test file in {repo}; known flaky tests are marked where they're defined.</li>
        <li>To fetch the newest, run <q>StackVitals: Refresh flaky tests</q> from the command palette.</li>
      </ol>
      <CodeBlock inline code={`uvx stackvitals editor ${ed}`} />
    </div>
  </article>;
}

const HOW: [string, string][] = [
  ["Runs on", "Your computer, started by your agent through uvx."],
  ["Reads", "The repo's stackvitals-data branch, or a local copy read from GitHub with your token."],
  ["Sends to StackVitals", "Nothing: there is no StackVitals server."],
  ["Every answer says", "When its numbers are from and where they came from."],
];

export default function Agents({ app }: PageProps) {
  const [d, setD] = useState<Data | null>(null);
  const [all, setAll] = useState<Pick>(prefs.get("agentTools", "all"));
  const [to, setTo] = useState<"claude" | "codex">("claude");
  useEffect(() => { import("../features/agents-data").then(setD, () => setD(null)); }, []);
  if (!d) return <PageSkeleton />;
  const total = d.GROUPS.reduce((n, g) => n + g.tools.length, 0);
  const repo = app?.repo || "your repo";
  return <Page title="Agents" subtitle="Give your coding agent this repo's history: known flakes, how changes get merged, who should review.">
    <Section title="Connect your agent" description="One MCP server for every client. Your agent runs on your computer, so its config lives there: follow the steps on your agent's card and copy its config."
      action={<SegmentedControl label="Tools in the config" size="sm" value={all} onChange={(v) => { setAll(v); prefs.set("agentTools", v); }}
        options={[{ value: "core", label: `Core (${d.CORE.length})` }, { value: "all", label: `All tools (${total})` }]} />}>
      <p class="ag-hint">{all === "all" ? `Every tool (${total}), as the skills and the MCP registry entry use.` : `The ${d.CORE.length} everyday tools keep the agent's context small; the rest load with --tools all.`}</p>
      <div class="ag-cards">{d.CLIENTS.map((c) => <ClientCard d={d} client={c.id} all={all === "all"} />)}</div>
    </Section>

    <Section title="What your agent can ask" description={`${total} tools, ${d.CORE.length} of them core. Each answers from kept history and comparisons across repos. Filter by area or by how it loads.`}>
      <ToolTable d={d} />
    </Section>

    <Section title="Skills" description="Ready-made instructions that tell your agent when to ask StackVitals. They use all tools. Install all at once, or one by one."
      action={<SegmentedControl label="Install skills for" size="sm" value={to} onChange={setTo} options={[{ value: "claude", label: "Claude Code" }, { value: "codex", label: "Codex" }]} />}>
      <SkillTable d={d} to={to} />
    </Section>

    <Section title="Editor" description="Marks known flaky tests right in your test files, from the repo's stackvitals-data branch.">
      <Editor repo={repo} />
    </Section>

    <Section title="How it works" description="What the server reads and where it runs.">
      <Card class="ag-how">
        <dl class="ag-facts">{HOW.map(([k, v]) => <div><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
        <div class="ag-how-foot"><Button size="sm" variant="plain" href={DOCS + "modules.md"} external iconEnd="external">Learn more</Button></div>
      </Card>
    </Section>
  </Page>;
}
