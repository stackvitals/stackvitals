// Agents' structured parts: one setup card per client (numbered steps and the config to copy), the tools and skills as tables.
import type { ComponentChildren } from "preact";
import type { Client, Group } from "../../features/agents-data";
import { CodeBlock, CopyButton } from "../../ui/bits";
import { Table, type Column } from "../../ui/Table";

type Data = typeof import("../../features/agents-data");
const UV = <a href="https://docs.astral.sh/uv/" target="_blank" rel="noopener noreferrer">uv</a>;

// Where the config goes and how the client picks it up; step 1 (uv) and the last (a test question) are shared.
const STEPS: Record<Client, { add: ComponentChildren; load: ComponentChildren }> = {
  claude: { add: <>In a terminal, in your repo's folder, run the command below.</>, load: <>Restart Claude Code; <code class="ag-id">/mcp</code> lists <b>stackvitals</b>.</> },
  cursor: { add: <>Paste it into <code class="ag-id">.cursor/mcp.json</code> in the project, or <code class="ag-id">~/.cursor/mcp.json</code> for every project.</>,
    load: <>Reload Cursor; its MCP settings list <b>stackvitals</b>.</> },
  vscode: { add: <>Paste it into <code class="ag-id">.vscode/mcp.json</code> in the workspace.</>, load: <>Open Copilot Chat in agent mode; its tools list <b>stackvitals</b>.</> },
  codex: { add: <>Add it to <code class="ag-id">~/.codex/config.toml</code>.</>, load: <>Start a new Codex session.</> },
  desktop: { add: <>In Claude Desktop: Settings, Developer, Edit config. Paste it into <code class="ag-id">claude_desktop_config.json</code> and save.</>,
    load: <>Restart the app.</> },
  windsurf: { add: <>Add it to Cascade's MCP servers, in <code class="ag-id">~/.codeium/windsurf/mcp_config.json</code>.</>, load: <>Refresh Cascade's MCP servers.</> },
};

export function ClientCard({ d, client, all }: { d: Data; client: Client; all: boolean }) {
  const c = d.CLIENTS.find((x) => x.id === client)!;
  const s = STEPS[client];
  return <article class="ag-card card">
    <header class="ag-strip"><h3>{c.label}</h3><span class="ag-file">{c.file === "Terminal" ? "One command" : <code class="ag-id">{c.file}</code>}</span></header>
    <div class="ag-body">
      <ol class="ag-steps">
        <li>Install {UV} once, if you don't have it.</li>
        <li>{s.add}</li>
        <li>{s.load}</li>
        <li>Check it: ask <q>Is test_upload a known flake in this repo?</q></li>
      </ol>
      <div class="ag-code"><CodeBlock code={d.config(client, all)} title={c.file === "Terminal" ? "Command" : c.file} /></div>
    </div>
  </article>;
}

interface ToolRow { id: string; name: string; area: string; icon: Group["icon"]; does: string; ask: string; loads: string }

export function ToolTable({ d }: { d: Data }) {
  const rows: ToolRow[] = d.GROUPS.flatMap((g) => g.tools.map((t) => ({ id: t.name, name: t.name, area: g.title, icon: g.icon, does: t.does, ask: t.ask,
    loads: d.CORE.includes(t.name) ? "Core" : "All tools" })));
  const cols: Column<ToolRow>[] = [
    { key: "name", label: "Tool", primary: true, nowrap: true, render: (r) => <code class="ag-id ag-tool-name">{r.name}</code> },
    { key: "area", label: "Area", filter: true, nowrap: true },
    { key: "does", label: "What it answers" },
    { key: "ask", label: "Example question", render: (r) => <q class="ag-q">{r.ask}</q> },
    { key: "loads", label: "Loaded with", filter: true,
      render: (r) => <span class="ag-state"><span class={"sv-mark " + (r.loads === "Core" ? "sv-mark-accent" : "sv-mark-neutral")} aria-hidden="true" />{r.loads}</span> },
  ];
  return <Table rows={rows} columns={cols} name="agent-tools" caption="Tools your agent can use" limit={60} />;
}

interface SkillRow { id: string; title: string; does: string; cmd: string }

export function SkillTable({ d, to }: { d: Data; to: "claude" | "codex" }) {
  const rows: SkillRow[] = d.SKILLS.map((s) => ({ id: s.id, title: s.title, does: s.does, cmd: d.skillCommand(s.id, to) }));
  const all = rows.map((r) => r.cmd).join(" && \\\n");
  return <>
    <div class="ag-code"><CodeBlock code={all} title={`All ${rows.length} skills, for ${to === "claude" ? "Claude Code" : "Codex"}`} /></div>
    <Table rows={rows} name="agent-skills" caption="Skills" search={false} columns={[
      { key: "title", label: "Skill", primary: true, render: (r) => <span class="ag-skill-name"><b>{r.title}</b><code class="ag-id">{r.id}</code></span> },
      { key: "does", label: "When your agent uses it" },
      { key: "cmd", label: "Install one", nowrap: true, render: (r) => <CopyButton text={r.cmd} small label="Copy command" /> },
    ]} />
  </>;
}
