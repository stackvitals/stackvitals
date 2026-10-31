// The workflow file, exactly as `stackvitals ci init` writes it (a port of workflow_template in ci/cli.py; a test compares).
export const ACTION_REF = "stackvitals/stackvitals@v0";
export const FILE = ".github/workflows/stackvitals.yml";
export const MODULES = ["ci", "flow", "deps", "community"] as const;
export type Module = (typeof MODULES)[number];

const WORKFLOW = `name: StackVitals
on:
  workflow_run:
    workflows: {names}   # your CI workflows; each finished run is read right away
    types: [completed]
  schedule:
    - cron: "17 */3 * * *"   # Team Flow every 3 hours, and a CI catch-up
  repository_dispatch:
    # Sent by \`stackvitals record\` from any deploy tool, or as CDEvents (0.4 and 0.5); for Flux add your
    # "Kustomization/<name>.<namespace>" here.
    types: [stackvitals-deployment, stackvitals-incident,
            dev.cdevents.service.deployed.0.3.0, dev.cdevents.service.upgraded.0.3.0, dev.cdevents.service.rolledback.0.3.0,
            dev.cdevents.incident.detected.0.3.0, dev.cdevents.incident.resolved.0.3.0,
            dev.cdevents.service.deployed.0.2.0, dev.cdevents.service.upgraded.0.2.0, dev.cdevents.service.rolledback.0.2.0,
            dev.cdevents.incident.detected.0.2.0, dev.cdevents.incident.resolved.0.2.0]
  workflow_dispatch:
    inputs:
      request:
        description: "A change sent from the StackVitals app (leave empty for a normal run)"
        required: false
        default: ""
  push:                      # your settings file applies at once; adding this file starts the first run
    paths: [".github/stackvitals.toml", ".github/workflows/stackvitals.yml"]
  issues:
    types: [opened, closed, reopened]  # requests from the app; flaky-test issues closed as not planned, or reopened
  issue_comment:
    types: [created]         # /stackvitals commands
  pull_request:              # the dependency check, only when a lockfile changes (never runs the PR's code)
    paths: ["**/*.lock", "**/*lock.json", "**/*lock.yaml", "**/npm-shrinkwrap.json", "**/requirements*.txt", "**/go.mod",
            "**/*.lockfile", "**/pom.xml", "**/pylock*.toml", "**/Package.resolved", "**/gems.locked",
            "**/verification-metadata.xml", "**/*.freeze"]
permissions:
  contents: write        # saves history to the stackvitals-data branch; settings changes asked for from the app
  actions: read          # reads your CI runs, jobs and test reports (write: [automation] rerun_flaky re-runs known flakes)
  checks: read           # Team Flow: sees which PRs have failing checks (write: [automation] verdict_check)
  statuses: read
  deployments: read      # Team Flow: delivery from deployments
  issues: write          # the weekly digest, answers to /stackvitals commands, flaky-test and alert issues
  pull-requests: write   # reads PRs for Team Flow; one comment on failed PR runs (set to read to turn comments off)
jobs:
  vitals:
    # Only what concerns StackVitals starts a runner: settings pushed to the default branch, requests and commands from
    # people with access to the repo, and flaky-test issues being closed or reopened.
    if: >-
      (github.event_name != 'push' || github.ref_name == github.event.repository.default_branch) &&
      (github.event_name != 'issues' ||
        (github.event.action == 'opened' && contains(github.event.issue.body, '\`\`\`stackvitals') &&
         contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.issue.author_association)) ||
        (github.event.action != 'opened' && contains(github.event.issue.labels.*.name, 'flaky-test'))) &&
      (github.event_name != 'issue_comment' ||
        (contains(github.event.comment.body, '/stackvitals') &&
         contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.comment.author_association))) &&
      (github.event_name != 'workflow_run' || !github.event.repository.private ||
        github.event.workflow_run.conclusion != 'success' || vars.STACKVITALS_EVERY_CI_RUN == 'true')
    # Private repos pay for Actions minutes: a CI run that passed starts no job (the 3-hourly run reads it), unless the
    # repo variable STACKVITALS_EVERY_CI_RUN is "true" (the verdict check needs it). On the job, so events it skips never
    # wait in (or cancel) the queue; PR checks and Test connection runs never wait for (or get dropped behind) data runs.
    concurrency:
      group: stackvitals-\${{ github.event.pull_request.number || (contains(github.event.inputs.request, '"check"') && format('check-{0}', github.run_id)) || 'data' }}
      cancel-in-progress: false
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: {ref}
        env:
          STACKVITALS_EVERY_CI_RUN: \${{ vars.STACKVITALS_EVERY_CI_RUN }}
        with:
          modules: ci,flow,deps,community
          jira-email: \${{ secrets.JIRA_EMAIL }}        # optional: Jira Cloud (see Integrations); unused while unset
          jira-token: \${{ secrets.JIRA_API_TOKEN }}
          linear-token: \${{ secrets.LINEAR_API_KEY }}  # optional: Linear
          pagerduty-token: \${{ secrets.PAGERDUTY_API_KEY }}       # optional: PagerDuty or incident.io incidents
          incident-io-token: \${{ secrets.INCIDENT_IO_API_KEY }}
          triage-key: \${{ secrets.GEMINI_API_KEY }}     # optional: a model's view on undecided failures ([ci.triage])
          # traffic-token: \${{ steps.app.outputs.token }}   # optional: keep traffic past GitHub's 14 days (see docs/modules.md)
`;

// Python's json.dumps: non-ASCII characters escaped as \uXXXX.
export function pyJson(s: string): string {
  return JSON.stringify(s).replace(/[\u007f-￿]/g, (c) => c === "\u007f" ? c : "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
}

// The line without its YAML comment; a "#" inside quotes (a workflow name) stays.
function uncommented(line: string): string {
  let quote: string | null = null;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]!;
    if ((ch === '"' || ch === "'") && (quote === null || quote === ch)) quote = quote ? null : ch;
    else if (ch === "#" && quote === null && (i === 0 || /\s/.test(line[i - 1]!))) return line.slice(0, i).replace(/\s+$/, "");
  }
  return line;
}

const lead = (l: string) => l.length - l.replace(/^\s+/, "").length;

// Only the chosen modules' triggers and the permissions they use (a port of _for_modules).
function forModules(text: string, modules: readonly string[]): string {
  const has = new Set(modules);
  const some = (...m: string[]) => m.some((x) => has.has(x));
  const lines = text.match(/[^\n]*\n|[^\n]+$/g) || [];
  const out: string[] = [];
  let skip: number | null = null;
  for (let line of lines) {
    const key = line.trim().split(":", 1)[0];
    const indent = lead(line);
    if (skip !== null) {
      if (indent > skip || !line.trim()) continue;
      skip = null;
    }
    if (indent === 2 && ((key === "workflow_run" && !has.has("ci")) || (key === "pull_request" && !has.has("deps")))) { skip = indent; continue; }
    if (indent === 2 && ["actions", "checks", "statuses", "deployments", "pull-requests"].includes(key!)) {
      const needs = { actions: has.has("ci"), checks: some("ci", "flow"), statuses: some("ci", "flow"), deployments: has.has("flow"), "pull-requests": true }[key as "actions"];
      if (!needs) continue;
      if (key === "pull-requests" && !some("ci", "flow")) line = "  pull-requests: read    # the dependency check reads the files a pull request changes\n";
    }
    if (line.trim().startsWith("modules:")) line = line.split("modules:")[0] + "modules: " + MODULES.filter((m) => has.has(m)).join(",") + "\n";
    out.push(line);
  }
  return out.join("");
}

export function workflowTemplate(names?: string[] | null, opts: { compact?: boolean; modules?: readonly string[]; ref?: string } = {}): string {
  const list = "[" + (names && names.length ? names : ["CI"]).map(pyJson).join(", ") + "]";
  let text = WORKFLOW.replace("{names}", list).replace("{ref}", opts.ref || ACTION_REF);
  const mods = opts.modules || MODULES;
  if (mods.join(",") !== MODULES.join(",")) text = forModules(text, mods);
  if (!opts.compact) return text;
  // Without comments, for a prefilled GitHub link (GitHub refuses links much over 6,500 characters); the CDEvents
  // dispatch types are left out too, so it fits (docs/connectors.md says to add them).
  text = text.replace(/types: \[stackvitals-deployment, stackvitals-incident,[^\]]*\]/, "types: [stackvitals-deployment, stackvitals-incident]");
  return text.split(/\r?\n/).map(uncommented).filter((l) => l.trim()).join("\n") + "\n";
}

export interface Inputs { days?: number; budget?: number; pages?: "branch" | "artifact" }

// Advanced choices as Action inputs under `with:`, only when they differ from the Action's defaults.
export function withInputs(yaml: string, inp: Inputs): string {
  const extra: string[] = [];
  if (inp.days && inp.days !== 90) extra.push(`days: "${Math.round(inp.days)}"`);
  if (inp.budget && inp.budget !== 800) extra.push(`budget: "${Math.round(inp.budget)}"`);
  if (inp.pages === "artifact") extra.push("pages: artifact");
  if (!extra.length) return yaml;
  return yaml.replace(/^( *)modules: .*$/m, (m, sp: string) => [m, ...extra.map((e) => sp + e)].join("\n"));
}

// The workflows that look like CI (tests, builds, checks); with none recognised, all of them (as ci_guess).
const CI = /\b(test|tests|testing|ci|build|builds|lint|check|checks|pre-commit|e2e|unit|integration|verify|validate)\b/i;
const CHORE = /\b(lock|stale|label|labeler|greet|welcome|release|publish|deploy|pages|codeql|scorecard|zizmor|dependabot|triage|sync|review)\b/i;
export function ciGuess(names: string[]): string[] {
  const picked = names.filter((n) => CI.test(n) && !CHORE.test(n));
  return picked.length ? picked : names.slice();
}

export function cliCommand(repo: string, modules: readonly string[]): string {
  const m = MODULES.filter((x) => modules.includes(x));
  return `stackvitals init ${repo}${m.length === MODULES.length ? "" : ` --modules ${m.join(",")}`}`;
}

// StackVitals inside another workflow before it is on PyPI: the Action's own code and pinned packages (its uv.lock),
// run from their own folder; a `stackvitals` command goes on the PATH. Steps at `indent`, with `# vN` notes when `notes`.
export const SETUP_GO = "actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e # v7.0.0";
export const SETUP_UV = "astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7 # v10.2.0";
export function installSteps(indent = 6, notes = true): string[] {
  const [repo, ref] = ACTION_REF.split("@") as [string, string];
  const i = " ".repeat(indent), r = i + "    ";
  return [
    `${i}- uses: ${notes ? SETUP_UV : SETUP_UV.split(" # ")[0]}`,
    `${i}  with:`,
    `${i}    cache-dependency-glob: ""`,
    `${i}- name: Install StackVitals`,
    ...(notes ? [`${i}  # The same code and pinned packages as the StackVitals Action (its uv.lock), run from their own folder.`] : []),
    `${i}  run: |`,
    ...[`git clone -q --depth 1 --branch ${ref} https://github.com/${repo}.git "$RUNNER_TEMP/stackvitals"`,
      'uv sync --quiet --frozen --only-group action --project "$RUNNER_TEMP/stackvitals"',
      'mkdir -p "$RUNNER_TEMP/bin"',
      'cat > "$RUNNER_TEMP/bin/stackvitals" <<EOF',
      "#!/bin/sh",
      'PYTHONPATH="$RUNNER_TEMP/stackvitals/src" exec "$RUNNER_TEMP/stackvitals/.venv/bin/python" -m stackvitals "\\$@"',
      "EOF",
      'chmod +x "$RUNNER_TEMP/bin/stackvitals"',
      'echo "$RUNNER_TEMP/bin" >> "$GITHUB_PATH"'].map((l) => r + l)];
}
