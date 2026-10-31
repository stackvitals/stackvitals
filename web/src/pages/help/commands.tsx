// Help's reference tables: what the app now does in one click, every command (what it does, where it runs, its in-app
// equivalent), and the printable pages the last run wrote.
import { href } from "../../app/router";
import type { AppJson } from "../../data/types";
import { CopyButton } from "../../ui/bits";
import { Table, type Column } from "../../ui/Table";

interface InApp { label: string; to: string }
const AT = {
  setup: { label: "Setup", to: href("setup") },
  decide: { label: "Overview, Make a decision", to: href("overview") + "?at=ov-decide" },
  ciSetup: { label: "CI Health, Set up in your CI", to: href("ci") + "?at=ci-setup" },
  settings: { label: "Settings", to: href("settings") },
  connections: { label: "Connections, Test connection", to: href("connections") },
  explore: { label: "Explore", to: href("explore") },
  agents: { label: "Agents", to: href("agents") },
  ci: { label: "CI Health", to: href("ci") },
  prs: { label: "Pull Requests", to: href("prs") },
  delivery: { label: "Delivery", to: href("delivery") },
  community: { label: "Community", to: href("community") },
  insights: { label: "Insights", to: href("insights") },
  portal: { label: "Portal", to: href("portal") },
} satisfies Record<string, InApp>;

// Where a command has to run; "Your machine" ones read with your own token or files.
type Where = "Your machine" | "Your CI's test step" | "Your CD tool or pager" | "Jenkins, CircleCI or Buildkite";
interface Cmd { id: string; cmd: string; what: string; area: string; where: Where; app?: InApp; same?: string }

const c = (area: string, where: Where, cmd: string, what: string, app?: InApp, same?: string): Cmd => ({ id: cmd, cmd, what, area, where, app, same });
const READ = "Read a repo", TEST = "Test step", BEFORE = "Before a change", DATA = "Data in and out", SET = "Set up and connect";
const THIS = "the same for this repo";

export const COMMANDS: Cmd[] = [
  c(READ, "Your machine", "stackvitals ci report owner/repo --days 14", "CI Health: flaky, failing and slow jobs and tests", AT.ci, THIS),
  c(READ, "Your machine", "stackvitals flow report owner/repo", "Team Flow: who acts next on each pull request", AT.prs, THIS),
  c(READ, "Your machine", "stackvitals delivery owner/repo", "Cycle time, DORA and stuck pull requests", AT.delivery, THIS),
  c(READ, "Your machine", "stackvitals delivery group/project --gitlab", "The same from GitLab merge requests and deployments"),
  c(READ, "Your machine", "stackvitals delivery workspace/repo --bitbucket", "The same from Bitbucket Cloud (BITBUCKET_TOKEN for private repos)"),
  c(READ, "Your machine", "stackvitals delivery org/project/repo --azure", "The same from Azure DevOps (AZURE_DEVOPS_TOKEN for private projects)"),
  c(READ, "Your machine", "stackvitals community report owner/repo", "Newcomer funnel and first answers", AT.community, THIS),
  c(READ, "Your machine", "stackvitals insights owner/repo", "What to fix first, across modules", AT.insights, THIS),
  c(READ, "Your machine", "stackvitals portal report my-org", "Every repo of an org and its owners, with evidence", AT.portal, "when the org's Portal runs"),
  c(READ, "Your machine", "stackvitals contribute brief owner/repo", "How changes get merged in a repo you want to contribute to", AT.agents, "repo_brief, from your agent"),
  c(TEST, "Your CI's test step", 'stackvitals ci quarantine --reports "out/*.xml" -- pytest --junitxml out/results.xml', "Pass when only known-flaky tests failed", AT.ciSetup, "generates the step"),
  c(TEST, "Your CI's test step", "stackvitals ci retry --reports 'out/*.xml' -- pytest --junitxml out/results.xml", "Re-run only the failed tests, never known-broken ones", AT.ciSetup, "generates the step"),
  c(TEST, "Your CI's test step", "stackvitals ci burn-in --base origin/main --times 5 -- pytest {files}", "Run the tests a PR adds or changes several times; fail on a flip", AT.ciSetup, "generates the step"),
  c(TEST, "Your CI's test step", "stackvitals ci impact --base origin/main --tests 'tests/**/*.py'", "The test files a change can affect, from names and past failures", AT.ciSetup, "generates the step"),
  c(TEST, "Your CI's test step", "stackvitals ci shards owner/repo --n 4", "Split test files into shards that take about the same time", AT.ciSetup, "generates the step"),
  c(TEST, "Your CI's test step", "stackvitals ci validate 'build/test-results/**/*.xml'", "Check test reports are read as you expect", AT.ciSetup, "generates the step"),
  c(TEST, "Jenkins, CircleCI or Buildkite", 'stackvitals ci upload --repo owner/name --sha "$SHA" --provider jenkins test-results/*.xml', "Send reports from Jenkins, CircleCI or Buildkite"),
  c(BEFORE, "Your machine", "stackvitals deps check requests", "One package's evidence: use, monitor or investigate", AT.agents, "check_package, from your agent"),
  c(BEFORE, "Your machine", "stackvitals deps scan package-lock.json", "Every package in a lockfile, the ones to look at first"),
  c(BEFORE, "Your machine", "stackvitals flow preflight owner/repo --paths src/db/pool.py --lines 120", "What merged PRs here usually include, and what yours is missing", AT.agents, "preflight, from your agent"),
  c(BEFORE, "Your machine", "stackvitals flow triage owner/repo", "Chance each open outside PR gets merged, and why"),
  c(DATA, "Your CD tool or pager", 'stackvitals record deployment owner/repo --id argo-1287 --sha "$GIT_SHA" --tool argo-cd', "Send a deployment from any CD tool"),
  c(DATA, "Your CD tool or pager", "stackvitals record incident owner/repo --id INC-42 --at 2026-10-29T09:12:00Z", "Send an incident from any pager", AT.connections, "pager connectors"),
  c(DATA, "Your machine", "stackvitals project web org/frontend org/api org/worker", "DORA for one project across several repos"),
  c(DATA, "Your machine", "stackvitals explain owner/repo lead-time", "What a headline number was counted from"),
  c(DATA, "Your machine", 'stackvitals sql --repo owner/name "select role, count(*) from prs group by role"', "SQL over a repo's summaries", AT.explore, "SQL in the browser"),
  c(DATA, "Your machine", "stackvitals export owner/repo --format devlake", "DevLake tables (also ctrf, otel --tests, postgres)", AT.explore, "each table as a download"),
  c(DATA, "Your machine", "stackvitals propose owner/repo --set alerts.pickup_p75_hours=6", "A link proposing a settings change that a person submits", AT.settings, "edit and send"),
  c(DATA, "Your machine", "stackvitals ui owner/repo", "Open a repo's pages and Explore from a local copy"),
  c(SET, "Your machine", "stackvitals init owner/repo", "Set up a repo: commits the workflow, follows the first run, turns on Pages for a public repo", AT.setup, "the same, with a button"),
  c(SET, "Your machine", "stackvitals ci init owner/repo > .github/workflows/stackvitals.yml", "Only print the workflow file, with this repo's names filled in", AT.setup, "commits it for you"),
  c(SET, "Your machine", "stackvitals portal check my-org", "What your token can read in an org, before the first run"),
  c(SET, "Your machine", "stackvitals connectors check --all", "Test each connector's key", AT.connections, "one connector at a time"),
  c(SET, "Your machine", "stackvitals serve", "The MCP server for AI agents", AT.agents, "config to copy"),
  c(SET, "Your machine", "stackvitals editor vscode", "Mark flaky tests in VS Code, Cursor or VSCodium", AT.agents, "Editor section"),
];

const link = (a: InApp) => <a class="hp-go" href={a.to}>{a.label}</a>;

const CMD_COLS: Column<Cmd>[] = [
  { key: "cmd", label: "Command", primary: true, raw: (r) => r.cmd,
    render: (r) => <span class="hp-cmd"><code>{r.cmd}</code><CopyButton text={r.cmd} small label="Copy" /></span> },
  { key: "what", label: "What it does" },
  { key: "area", label: "Use", filter: true },
  { key: "where", label: "Where it runs", filter: true },
  { key: "app", label: "In the app", raw: (r) => r.app?.label || "", render: (r) => r.app
    ? <span class="hp-app">{link(r.app)}{r.same ? <span class="hp-same">{r.same}</span> : null}</span> : <span class="muted">Command only</span> },
];

export function CommandTable() {
  return <Table rows={COMMANDS} columns={CMD_COLS} name="stackvitals-commands" caption="Commands" limit={60} />;
}

interface Auto { id: string; task: string; at: InApp; replaces: string; noToken: string; withToken: string }
const AUTOS: Auto[] = [
  { id: "install", task: "Add StackVitals to a repo", at: AT.setup, replaces: "stackvitals init",
    noToken: "The workflow file opens on GitHub, ready to commit", withToken: "Commits it, starts the first run, turns on Pages" },
  { id: "decide", task: "Quarantine, mute, snooze or acknowledge", at: AT.decide, replaces: "stackvitals propose --decide",
    noToken: "A prefilled issue you submit on GitHub", withToken: "Starts the workflow, which checks your access and records it" },
  { id: "ci", task: "Add retry, burn-in, impact, shards or quarantine to your tests", at: AT.ciSetup, replaces: "stackvitals ci retry, burn-in, impact, ...",
    noToken: "The test workflow opens on GitHub as a new file", withToken: "Opens a pull request with the file" },
  { id: "settings", task: "Change a setting", at: AT.settings, replaces: "stackvitals propose --set",
    noToken: "A prefilled issue, or the TOML to paste", withToken: "Commits it or opens a pull request" },
  { id: "connect", task: "Test a connector's key", at: AT.connections, replaces: "stackvitals connectors check",
    noToken: "Not available: the check runs in your workflow", withToken: "Runs the workflow's check and shows the result" },
  { id: "sql", task: "Query the summaries", at: AT.explore, replaces: "stackvitals sql, stackvitals export",
    noToken: "Runs in your browser; tables download as CSV", withToken: "Not needed" },
];
const AUTO_COLS: Column<Auto>[] = [
  { key: "task", label: "Task", primary: true },
  { key: "at", label: "Where in the app", raw: (r) => r.at.label, render: (r) => link(r.at) },
  { key: "replaces", label: "Instead of", render: (r) => <code class="hp-id">{r.replaces}</code> },
  { key: "noToken", label: "Without a token" },
  { key: "withToken", label: "With a GitHub token" },
];

export function AutoTable() {
  return <Table rows={AUTOS} columns={AUTO_COLS} name="done-in-the-app" caption="Done in the app" search={false} />;
}

const PRINT: Record<string, string> = { "ci.html": "CI Health", "flow.html": "Team Flow", "delivery.html": "Delivery", "insights.html": "Insights",
  "community.html": "Community", "portal.html": "Portal", "explore.html": "Explore" };
interface Printed { id: string; title: string; file: string; note: string }

export function printed(app: AppJson | null): Printed[] {
  return (app?.pages || []).filter((x) => x.endsWith(".html")).map((x) => ({ id: x, title: PRINT[x] || x, file: x,
    note: x === "explore.html" ? "SQL over the summaries in your browser" : "One page, no JavaScript needed; ready to print or attach" }));
}

export function PrintTable({ rows }: { rows: Printed[] }) {
  return <Table rows={rows} name="printable-pages" caption="Printable pages" search={false} columns={[
    { key: "title", label: "Page", primary: true, render: (r) => <a href={r.file} target="_blank" rel="noopener noreferrer">{r.title}</a> },
    { key: "file", label: "File", nowrap: true, render: (r) => <code class="hp-id">{r.file}</code> },
    { key: "note", label: "What it is" }]} />;
}
