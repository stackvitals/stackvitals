// The MCP server's tools (mcp_server.py CORE_TOOLS and each tool's docstring, in plain words), the agent clients'
// config formats, and the skills in skills/. Loaded with the Agents page as its own chunk.
export interface Tool { name: string; does: string; ask: string }
export interface Group { title: string; icon: "ci" | "prs" | "delivery" | "deps" | "community" | "portal" | "explore"; tools: Tool[] }

export const CORE = ["ci_failure", "is_known_flake", "ci_health", "repo_brief", "preflight", "who_should_review", "pr_queue",
  "check_package", "scan_lockfile", "insights", "delivery_health"];

const t = (name: string, does: string, ask: string): Tool => ({ name, does, ask });

export const GROUPS: Group[] = [
  { title: "CI", icon: "ci", tools: [
    t("ci_failure", "Explains a failed run: known flake, already failing on main, an outside failure, or likely the change.", "Why did the last CI run on my branch fail?"),
    t("is_known_flake", "Before fixing a failing test or job: is it a known flake here?", "Is test_upload a known flake in this repo?"),
    t("ci_health", "Flaky and failing jobs and tests, slower jobs, coverage and first-try green, this week against the last four.", "How healthy is our CI this week?"),
    t("test_status", "One test's state and why: the monitors holding it, labels, mutes and its failure group.", "Why is test_checkout marked flaky?"),
    t("failure_group", "Failures with one cause across tests and runs, biggest first, with an investigation prompt.", "Which failures share a cause, and where do I start?"),
    t("ci_slowest", "The slowest jobs and tests with daily medians, what got slower, new tests and skipped ones.", "Which tests got slower this week?"),
    t("propose_change", "A prefilled GitHub issue that changes settings or records a decision; nothing changes until a person submits it.", "Quarantine test_upload for 30 days."),
  ] },
  { title: "Pull Requests", icon: "prs", tools: [
    t("repo_brief", "How changes get merged in an unfamiliar repo, from its history: what PRs include, who reviews, known flakes.", "How do changes get merged in this repo?"),
    t("preflight", "What merged PRs touching these files usually include, and what this change is missing.", "Is my change ready to open as a PR?"),
    t("who_should_review", "Up to 3 reviewers: who knows the areas, code owners, open reviews and how fast each answers.", "Who should review PR 412?"),
    t("pr_queue", "Open PRs and who has to act next on each, since when, and whether that's longer than usual.", "Which PRs are waiting on me?"),
    t("flow_health", "Hours to a first review, in review and to merge; how insiders and outside contributors fare.", "How long do PRs wait for a first review?"),
    t("reviewer_load", "Each reviewer's open review requests and the PRs waiting on them.", "Who has the most reviews waiting?"),
    t("triage_pr", "For maintainers: each outside PR's chance to merge within 30 days, with the main reasons. Never stored or posted.", "Which outside PRs are likely to merge?"),
  ] },
  { title: "Delivery", icon: "delivery", tools: [
    t("insights", "What to fix first across modules, ranked by the hours of waiting or outage at stake.", "What should we fix first to ship faster?"),
    t("delivery_health", "DORA's keys with tiers, rework rate, where deployments come from, cycle time and stuck PRs.", "What are our DORA numbers?"),
    t("cycle_time", "Cycle time in four phases (coding, pickup, review, deploy) with P50, P75 and sample sizes.", "Where does our cycle time go?"),
    t("stuck_prs", "PRs stuck by LinearB's cut-offs, plus failing checks nobody acted on for a day.", "Which PRs are stuck?"),
  ] },
  { title: "Dependencies", icon: "deps", tools: [
    t("check_package", "How upgrades of an npm or PyPI package went across public repos, its advisories and a verdict.", "Is it safe to upgrade to axios 1.8?"),
    t("scan_lockfile", "Every package a lockfile pins, the ones that need a look first, each with its verdict.", "Which packages in package-lock.json need a look?"),
    t("supply_chain", "Packages by ecosystem, licence rule breaks, licence changes and Scorecard drops.", "Do any of our packages break our licence rule?"),
  ] },
  { title: "Community", icon: "community", tools: [
    t("community_health", "Newcomers and how many came back, first-answer times, and who carries the merged work.", "How welcoming is this repo to newcomers?"),
    t("newcomers_waiting", "First contributions nobody has answered yet, oldest first.", "Which newcomers are waiting for an answer?"),
  ] },
  { title: "Portal", icon: "portal", tools: [
    t("org_catalog", "An org's repos by scorecard level, owner status, the rules failing most and the typed catalog.", "How do our org's repos score?"),
    t("repo_scorecard", "One repo's scorecard level and the evidence behind each failing rule.", "Why is this repo only bronze?"),
    t("owners_health", "CODEOWNERS errors, empty teams, departed people and repos with no owners.", "Which repos have no real owner?"),
  ] },
  { title: "Finder", icon: "explore", tools: [
    t("find_issues", "Open issues an outsider can likely get merged, best first, each with its evidence.", "Find me a Rust issue I could get merged."),
    t("action_pack", "Everything to start on one issue: live status, rules as a checklist, accepted PRs to copy.", "Help me start on owner/repo#123."),
    t("repo_health", "How outsiders fare in one repo: merge rates, review time, walls and how to reach it.", "Do outside PRs get merged in this repo?"),
    t("repos_needing_help", "Repos that merge outsider PRs but have very few active maintainers.", "Which projects need more help?"),
    t("check_issue", "A live check on GitHub: open, assigned, linked PRs, recent claims.", "Is issue 123 still free?"),
    t("similar_issues", "Free issues whose titles share words with this one.", "Any issues like this one?"),
    t("explain", "The full evidence record behind an issue's score.", "Why does this issue score so high?"),
    t("track", "Track an issue on this machine and see what changed since the last look.", "What changed on the issues I track?"),
    t("report_outcome", "Record what happened to an issue you worked on, kept on this machine.", "My PR for issue 123 was merged."),
  ] },
];

export type Client = "claude" | "cursor" | "vscode" | "codex" | "desktop" | "windsurf";
export const CLIENTS: { id: Client; label: string; intro: string; file: string }[] = [
  { id: "claude", label: "Claude Code", intro: "Run it in your repo, then restart Claude Code.", file: "Terminal" },
  { id: "cursor", label: "Cursor", intro: "Add it to the project's .cursor/mcp.json, or ~/.cursor/mcp.json for every project.", file: ".cursor/mcp.json" },
  { id: "vscode", label: "VS Code / Copilot", intro: "Add it to the workspace; Copilot Chat in agent mode picks it up.", file: ".vscode/mcp.json" },
  { id: "codex", label: "Codex", intro: "Add it to Codex's config file, then start a new session.", file: "~/.codex/config.toml" },
  { id: "desktop", label: "Claude Desktop", intro: "Settings, Developer, Edit config; restart the app after saving.", file: "claude_desktop_config.json" },
  { id: "windsurf", label: "Windsurf", intro: "Add it to Cascade's MCP servers, then refresh.", file: "~/.codeium/windsurf/mcp_config.json" },
];

export function config(client: Client, all: boolean): string {
  const args = ["stackvitals", "serve", ...(all ? ["--tools", "all"] : [])];
  const list = `[${args.map((a) => JSON.stringify(a)).join(", ")}]`;
  const json = (root: string, extra = "") => `{\n  "${root}": {\n    "stackvitals": {\n${extra}      "command": "uvx",\n      "args": ${list}\n    }\n  }\n}`;
  if (client === "claude") return `claude mcp add stackvitals -- uvx ${args.join(" ")}`;
  if (client === "codex") return `[mcp_servers.stackvitals]\ncommand = "uvx"\nargs = ${list}`;
  if (client === "vscode") return json("servers", '      "type": "stdio",\n');
  return json("mcpServers");
}

export const SKILLS: { id: string; title: string; icon: Group["icon"]; does: string }[] = [
  { id: "stackvitals-ci", title: "CI failed", icon: "ci", does: "Before fixing a failed run: checks history to tell a known flake (re-run) from the change (fix)." },
  { id: "stackvitals-flow", title: "Pull requests", icon: "prs", does: "What blocks PRs, who should review, and whether a change looks like the PRs that get merged." },
  { id: "stackvitals-delivery", title: "Delivery", icon: "delivery", does: "Cycle time, DORA, stuck PRs and what to fix first to ship faster." },
  { id: "stackvitals-deps", title: "Dependencies", icon: "deps", does: "Before adding a package or merging a bot update: decide with evidence." },
  { id: "stackvitals-community", title: "Community", icon: "community", does: "Newcomers waiting, where contributors drop out, and first-answer times." },
  { id: "stackvitals-portal", title: "Portal", icon: "portal", does: "Who owns what in an org, weak owners, scorecards and campaigns." },
  { id: "stackvitals-contribute", title: "Contribute", icon: "explore", does: "Issues you can get merged, and how a repo works before your first PR." },
];

const RAW = "https://raw.githubusercontent.com/stackvitals/stackvitals/main/skills";
export function skillCommand(id: string, agent: "claude" | "codex"): string {
  const dir = `~/.${agent === "claude" ? "claude" : "codex"}/skills/${id}`;
  return `mkdir -p ${dir} && curl -fsSL ${RAW}/${id}/SKILL.md -o ${dir}/SKILL.md`;
}
