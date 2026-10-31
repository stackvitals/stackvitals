// Everything StackVitals can read or hand data to (from web/app/connectors.js, docs/connectors.md, action.yml and the
// GitLab template): what each unlocks, how to connect it, its secrets, its settings prefix and its Test connection name.
import { freshest } from "../data/files";
import { ago, count, day } from "../data/format";
import type { AppJson } from "../data/types";
import { DOCS } from "../ui/bits";
import { BRANDS, type BrandId } from "./brand-logos";
import { isConfigured, missing, statusOf, type Entry, type Status } from "./connstatus";
import { valueAt, type SettingsFile } from "./settingsModel";

export type Cat = "github" | "work" | "incidents" | "community" | "alerts" | "ci" | "ai" | "data" | "code" | "security";
export type Kind = "builtin" | "key" | "nokey" | "local";

export interface Step { text: string; code?: string; file?: string; href?: string; action?: string; to?: string }
export interface SecretDef { name: string; kind?: "secret" | "variable" | "gitlab"; optional?: boolean; multiline?: boolean; browser?: "linear" }
export interface Conn {
  id: string; name: string; glyph: string; cat: Cat; kind: Kind; unlocks: string[]; steps: (repo: string | null) => Step[];
  secrets?: SecretDef[]; prefix?: string; check?: string; tested?: string; doc: string; example?: boolean;
}

export { BRANDS };
// Each connection's brand marks; one without (no simple-icons mark, or not a product) keeps its letter glyph.
export const LOGOS: Record<string, BrandId[] | "chat"> = {
  github: ["github"], ghes: ["github"], sarif: ["github"], copilot: ["githubcopilot"], jira: ["jira"], linear: ["linear"], pagerduty: ["pagerduty"],
  sonar: ["sonarqubeserver"], record: ["argo"], bitbucket: ["bitbucket"], discourse: ["discourse"], discord: ["discord"], chat: "chat",
  ai_spend: ["anthropic", "cursor"], triage: ["googlegemini"], gitlab: ["gitlab"], otherci: ["jenkins", "circleci", "buildkite"],
  agents: ["modelcontextprotocol"], otel: ["opentelemetry"], backstage: ["backstage"],
};

const WF = "The StackVitals workflow";
const C = "connectors.md";

export const PERMS: [string, string][] = [
  ["CI Health", "actions: read (write to re-run flaky jobs)"], ["Team Flow and Delivery", "pull-requests, checks, statuses, deployments: read"],
  ["Community", "issues: read"], ["Dependencies", "contents: read"], ["Portal", "an org App token for private repos"],
];

export const CONNS: Conn[] = [
  { id: "github", name: "GitHub", glyph: "GH", cat: "github", kind: "builtin", tested: "Live", doc: C + "#github-built-in",
    unlocks: ["CI runs, jobs and test reports (JUnit, CTRF)", "Pull requests, reviews and checks", "Deployments, releases and issues", "Org repos, owners and scorecards (Portal)"],
    steps: () => [{ text: "Nothing to add: the workflow's own token reads them. Without a permission, that part is skipped and the job summary names the permission to add." }] },
  { id: "ghes", name: "GitHub Enterprise Server", glyph: "GE", cat: "github", kind: "builtin", tested: "Recorded", doc: "faq.md#does-it-work-on-github-enterprise-server",
    unlocks: ["The same modules on your own GitHub server", "The Action talks to your server, never github.com"],
    steps: () => [
      { text: "Nothing to add: the Action reads the API addresses GitHub Actions gives every job (GITHUB_API_URL and GITHUB_GRAPHQL_URL)." },
      { text: "From your machine, set the same two variables:", file: "Terminal", code: "export GITHUB_API_URL=https://<your-server>/api/v3\nexport GITHUB_GRAPHQL_URL=https://<your-server>/api/graphql\nstackvitals delivery owner/repo" },
      { text: "Two limits: links in the app point to github.com pages, and peer comparisons cover public github.com repos only." }] },
  { id: "scorecard", name: "OpenSSF Scorecard", glyph: "Sc", cat: "security", kind: "builtin", tested: "Live", doc: "modules.md#dependency-steward",
    unlocks: ["This repo's own Scorecard-style checks, private repos too, with a fix for each (Dependencies page)", "The Scorecard of each project behind your dependencies, with drops of a point or more",
      "Public repos' published Scorecards in the Portal rules"],
    steps: () => [
      { text: "Nothing to add. The workflow runs the checks itself; published scores come from api.scorecard.dev for public projects only, never this repo's name." },
      { text: "To keep every name in the repo, turn outside lookups off:", file: ".github/stackvitals.toml", code: "[deps]\noutside_lookups = false" },
      { text: "See this repo's checks and score.", to: "#/deps", action: "Open Dependencies" }] },
  { id: "sarif", name: "GitHub code scanning (Security tab)", glyph: "Cs", cat: "security", kind: "local", doc: "modules.md#dependency-steward",
    unlocks: ["Known vulnerabilities in every lockfile as code scanning alerts (vulns.sarif)", "Workflow security findings (security.sarif) beside CodeQL's"],
    steps: () => [
      { text: "Each run writes docs/vulns.sarif and docs/security.sarif to the stackvitals-data branch. The Dependencies page makes the workflow that uploads them (.github/workflows/stackvitals-code-scanning.yml, with github/codeql-action/upload-sarif@v4) and adds it in one click: GitHub's editor with no token, or a pull request with a token. It runs after each StackVitals run on the default branch and needs security-events: write.", to: "#/deps", action: "Open Dependencies" },
      { text: "Code scanning is free on public repos; private repos need GitHub Code Security." }] },
  { id: "licences", name: "Licence rule on pull requests", glyph: "Lc", cat: "security", kind: "nokey", tested: "Live", prefix: "deps.licenses", doc: "modules.md#dependency-steward",
    unlocks: ["Each package version a pull request brings in has its licence looked up on deps.dev", "A denied licence is named in the check, the job summary and the PR note before it merges",
      "The same rule over the whole dependency graph each week"],
    steps: () => [
      { text: "List the SPDX licences your dependencies must not use under Settings below (* is allowed, like GPL-3.0*). Empty is off." },
      { text: "Accept one package with a reason and an end date:", file: "Pull request comment", code: "/stackvitals accept package:<name> for 30d because <reason>" }] },
  { id: "jira", name: "Jira Cloud", glyph: "Ji", cat: "work", kind: "key", check: "jira", tested: "Live, write-back recorded", prefix: "connectors.jira",
    doc: C + "#issue-trackers-jira-cloud-and-linear-one-optional-key-each",
    secrets: [{ name: "JIRA_EMAIL" }, { name: "JIRA_API_TOKEN" }],
    unlocks: ["Issue lead and cycle time by type", "Sprints: scope, done, carried over, added late", "Incidents from a JQL query in DORA's failure rate and recovery",
      "Pull requests linked to issues by key", "DevLake's issue and sprint tables"],
    steps: () => [
      { text: "Create an API token for the account StackVitals reads as (a read-only account is best) and note when it expires.",
        href: "https://id.atlassian.com/manage-profile/security/api-tokens", action: "Create a Jira token" },
      { text: "Save JIRA_EMAIL (that account's email) and JIRA_API_TOKEN below." },
      { text: `${WF} passes them (new installs already have these lines):`, file: "stackvitals.yml",
        code: "jira-email: ${{ secrets.JIRA_EMAIL }}\njira-token: ${{ secrets.JIRA_API_TOKEN }}" },
      { text: "Name your site and the issues to read under Settings below." },
      { text: "The next scheduled run reads up to 180 days of issues, then only what changed." }] },
  { id: "linear", name: "Linear", glyph: "Li", cat: "work", kind: "key", check: "linear", tested: "Live sign-in and read", prefix: "connectors.linear",
    doc: C + "#issue-trackers-jira-cloud-and-linear-one-optional-key-each",
    secrets: [{ name: "LINEAR_API_KEY", browser: "linear" }],
    unlocks: ["Issue lead and cycle time", "Cycles: scope, done, carried over, added late", "Incidents from labels in DORA",
      "Pull requests linked to issues by identifier", "DevLake's issue and sprint tables"],
    steps: () => [
      { text: "In Linear, open Settings, Account, Security and access, and create a personal API key with read access.",
        href: "https://linear.app/settings/account/security", action: "Open Linear settings" },
      { text: "Save it as LINEAR_API_KEY below." },
      { text: `${WF} passes it (new installs already have this line):`, file: "stackvitals.yml", code: "linear-token: ${{ secrets.LINEAR_API_KEY }}" },
      { text: "Choose the teams to read under Settings below." }] },
  { id: "pagerduty", name: "PagerDuty", glyph: "PD", cat: "incidents", kind: "key", check: "pagerduty", tested: "Live sign-in and read", prefix: "connectors.pagerduty",
    doc: C + "#incidents-pagerduty-and-incidentio", secrets: [{ name: "PAGERDUTY_API_KEY" }],
    unlocks: ["Incidents in DORA's change failure rate and time to restore, instead of labels, reverts and hotfixes",
      "Time to resolve, linked to the deployment before each incident", "DevLake's incidents table"],
    steps: () => [
      { text: "In PagerDuty, open Integrations, API Access Keys, and create a read-only key.", href: "https://support.pagerduty.com/main/docs/api-access-keys", action: "PagerDuty's guide" },
      { text: "Save it as PAGERDUTY_API_KEY below." },
      { text: `${WF} passes it (new installs already have this line):`, file: "stackvitals.yml", code: "pagerduty-token: ${{ secrets.PAGERDUTY_API_KEY }}" },
      { text: "Optional: only some services, or low urgency too, under Settings below." }] },
  { id: "incident_io", name: "incident.io", glyph: "io", cat: "incidents", kind: "key", check: "incident_io", tested: "Recorded", prefix: "connectors.incident_io",
    doc: C + "#incidents-pagerduty-and-incidentio", secrets: [{ name: "INCIDENT_IO_API_KEY" }],
    unlocks: ["Incidents in DORA's change failure rate and time to restore, instead of labels, reverts and hotfixes",
      "Time to resolve from the incident's Resolved at", "DevLake's incidents table"],
    steps: () => [
      { text: "In incident.io, open Settings, API keys, and create a key that can view incidents.", href: "https://app.incident.io/settings/api-keys", action: "Open incident.io" },
      { text: "Save it as INCIDENT_IO_API_KEY below." },
      { text: `${WF} passes it (new installs already have this line):`, file: "stackvitals.yml", code: "incident-io-token: ${{ secrets.INCIDENT_IO_API_KEY }}" },
      { text: "Optional: only this repo's incident types, under Settings below." }] },
  { id: "sonar", name: "SonarQube or SonarCloud", glyph: "Sq", cat: "code", kind: "nokey", check: "sonar", tested: "Live read of a public SonarCloud project", prefix: "connectors.sonar",
    doc: C + "#code-quality-sonarqube-or-sonarcloud", secrets: [{ name: "SONAR_TOKEN", optional: true }],
    unlocks: ["The quality gate, read once a day and kept day by day", "Bugs, vulnerabilities, code smells, security hotspots, coverage and duplication, with how each moved over a month",
      "Coverage by day beside the delivery numbers, on Delivery's Code quality tab"],
    steps: () => [
      { text: "Set the project key (like myorg_myrepo) under Settings below, and the server's address if it is your own SonarQube." },
      { text: "A public SonarCloud project needs nothing more. For a private project or a SonarQube server, create a token, save it as SONAR_TOKEN below and pass it:",
        file: "stackvitals.yml", code: "sonar-token: ${{ secrets.SONAR_TOKEN }}" },
      { text: "After the next run, the gate and measures show on Delivery's Code quality tab.", to: "#/delivery?tab=quality", action: "Open Code quality" }] },
  { id: "record", name: "Deployments and incidents from any tool", glyph: "CD", cat: "incidents", kind: "local", tested: "Recorded", doc: C + "#deployments-and-incidents-from-elsewhere",
    unlocks: ["Deployments from Argo CD, Jenkins, Spinnaker, Octopus or a script, counted in DORA like GitHub's own", "Incidents from Opsgenie, Rootly or any pager, in change failure rate and recovery",
      "Sending the same id again updates it (a deploy's status, an incident's resolved time)"],
    steps: (repo) => [
      { text: "Each tool sends a repository_dispatch event to this repo with a token that can write its contents; the workflow keeps it on the data branch and the next run counts it. No server of ours is involved." },
      { text: "From a pipeline step, after the deploy has finished:", file: "Terminal",
        code: `pip install stackvitals\nstackvitals record deployment ${repo || "owner/repo"} --id "jenkins-$BUILD_TAG" --sha "$GIT_COMMIT" --environment production --tool jenkins\nstackvitals record incident ${repo || "owner/repo"} --id INC-42 --at 2026-10-29T09:12:00Z --resolved-at 2026-10-29T10:03:00Z` },
      { text: "Or without StackVitals installed (Spinnaker, Octopus, any script):", file: "Terminal",
        code: `curl -X POST -H "Authorization: Bearer $TOKEN" https://api.github.com/repos/${repo || "owner/repo"}/dispatches \\\n  -d '{"event_type":"stackvitals-deployment","client_payload":{"id":"argo-1287","sha":"'"$GIT_SHA"'","finished_at":"2026-10-29T09:00:00Z"}}'` },
      { text: "Argo CD: a webhook in its notifications engine, subscribed to on-deployed. The ready template and the Jenkins and GitLab lines are in the guide.", href: `${DOCS}${C}#deployments-and-incidents-from-elsewhere`, action: "Ready recipes" },
      { text: "Workflows set up before this need the repository_dispatch trigger; the current template has it." }] },
  { id: "bitbucket", name: "Bitbucket Cloud", glyph: "Bb", cat: "code", kind: "local", tested: "Live read of a public repo", doc: C + "#bitbucket-and-azure-devops",
    unlocks: ["Review phases for merged pull requests: first answer from someone else, approvals, merge", "DORA from Bitbucket Pipelines' production deployments", "Bots (Renovate, Dependabot) left out of people's numbers"],
    steps: () => [{ text: "Read-only, from your machine or any CI. A public repo needs no token; a private one needs an access token in BITBUCKET_TOKEN:", file: "Terminal",
      code: "pip install stackvitals\nexport BITBUCKET_TOKEN=...   # private repos only\nstackvitals delivery workspace/repo --bitbucket" }] },
  { id: "azure", name: "Azure DevOps", glyph: "Az", cat: "code", kind: "local", tested: "Live read of a public project", doc: C + "#bitbucket-and-azure-devops",
    unlocks: ["Review phases for completed pull requests: first answer, votes, merge", "DORA once deployments are sent with stackvitals record (release pipelines sit outside the Git API), or with every merge counted"],
    steps: () => [
      { text: "Read-only, from your machine or any CI. A public project needs no token; a private one needs a PAT with Code read in AZURE_DEVOPS_TOKEN:", file: "Terminal",
        code: "pip install stackvitals\nexport AZURE_DEVOPS_TOKEN=...   # private projects only\nstackvitals delivery org/project/repo --azure" },
      { text: "For deployments, add a step to the release pipeline that sends each one.", to: "#/connections/record", action: "From any tool" }] },
  { id: "discourse", name: "Discourse", glyph: "Fo", cat: "community", kind: "nokey", check: "discourse", tested: "Live", prefix: "connectors.discourse",
    doc: C + "#community-channels-discourse-slack-and-discord",
    unlocks: ["How fast the team answers questions asked on the forum, with topics still waiting counted", "How many forum questions anyone answered, and how many were solved"],
    steps: () => [
      { text: "Name the forum and, if its staff aren't the only ones answering for the project, who else is, under Settings below." },
      { text: "No key is needed: its public topics are read, and only times and flags are kept." }] },
  { id: "slack", name: "Slack support channels", glyph: "Sl", cat: "community", kind: "key", check: "slack", tested: "Live sign-in and channel read", prefix: "connectors.slack",
    doc: C + "#community-channels-discourse-slack-and-discord", secrets: [{ name: "SLACK_BOT_TOKEN" }],
    unlocks: ["How fast the team answers in the support channels, with questions still waiting counted", "How many questions anyone answered"],
    steps: () => [
      { text: "Create a Slack app with the channels:history scope, install it, and invite it to each support channel.", href: "https://api.slack.com/apps", action: "Slack apps" },
      { text: "Save its bot token as SLACK_BOT_TOKEN below." },
      { text: "Pass it in the workflow:", file: "stackvitals.yml", code: "slack-token: ${{ secrets.SLACK_BOT_TOKEN }}" },
      { text: "Name the channels and who answers for the project under Settings below (only times and flags are kept)." }] },
  { id: "discord", name: "Discord support channels", glyph: "Di", cat: "community", kind: "key", check: "discord", tested: "Live sign-in and channel read", prefix: "connectors.discord",
    doc: C + "#community-channels-discourse-slack-and-discord", secrets: [{ name: "DISCORD_BOT_TOKEN" }],
    unlocks: ["How fast the team answers in the support channels, with questions still waiting counted", "How many questions anyone answered"],
    steps: () => [
      { text: "Create a Discord bot with View Channel and Read Message History (no message content needed) and add it to the server.", href: "https://discord.com/developers/applications", action: "Discord developers" },
      { text: "Save its token as DISCORD_BOT_TOKEN below." },
      { text: "Pass it in the workflow:", file: "stackvitals.yml", code: "discord-token: ${{ secrets.DISCORD_BOT_TOKEN }}" },
      { text: "Name the channels and who answers for the project under Settings below (only times and flags are kept)." }] },
  { id: "chat", name: "Chat alerts (Slack, Teams, Discord)", glyph: "Wh", cat: "alerts", kind: "key", check: "webhook", tested: "Live for Slack and Discord, Teams recorded",
    doc: C + "#chat-slack-microsoft-teams-discord", secrets: [{ name: "STACKVITALS_WEBHOOK" }, { name: "STACKVITALS_TEAM_WEBHOOKS", optional: true, multiline: true }],
    unlocks: ["A message when something newly turns flaky", "Delivery alerts when a number crosses its threshold", "The weekly digest"],
    steps: () => [
      { text: "Create an incoming webhook: a Slack app's incoming webhook, a Teams Workflows \"post to a channel\" flow, or a Discord channel webhook.",
        href: "https://api.slack.com/messaging/webhooks", action: "Slack's guide" },
      { text: "Save its address as STACKVITALS_WEBHOOK below." },
      { text: "Pass it to the workflow:", file: "stackvitals.yml", code: "webhook: ${{ secrets.STACKVITALS_WEBHOOK }}" },
      { text: "Choose what goes there under Alerts and Weekly digest in Settings.", to: "#/settings" },
      { text: "Optional, one chat per team: STACKVITALS_TEAM_WEBHOOKS with one line per CODEOWNERS team, and a team's newly flaky tests go to its own chat:",
        file: "stackvitals.yml", code: "team-webhooks: ${{ secrets.STACKVITALS_TEAM_WEBHOOKS }}\n# secret: @acme/web = https://hooks.slack.com/services/..." }] },
  { id: "copilot", name: "GitHub Copilot", glyph: "Co", cat: "github", kind: "key", check: "copilot", tested: "Recorded", prefix: "connectors.copilot",
    doc: C + "#github-copilot-usage-reports", secrets: [{ name: "COPILOT_CLIENT_ID", kind: "variable" }, { name: "COPILOT_PRIVATE_KEY", multiline: true }],
    unlocks: ["The org's active users and suggestions accepted, day by day", "Pull requests by Copilot, org-wide and in this repo", "History past GitHub's own retention, beside AI-assisted outcomes"],
    steps: (repo) => [
      { text: "An org owner registers a private GitHub App for the org, with no webhook, and under Organization permissions sets \"Copilot metrics\" to Read; then installs it on the org.",
        href: repo ? `https://github.com/organizations/${repo.split("/")[0]}/settings/apps/new` : "https://docs.github.com/apps/creating-github-apps", action: "Register an App" },
      { text: "Save its client id as the variable COPILOT_CLIENT_ID and its private key as COPILOT_PRIVATE_KEY, then let the workflow make a token:", file: "stackvitals.yml",
        code: "- uses: actions/create-github-app-token@v3\n  id: copilot\n  with:\n    client-id: ${{ vars.COPILOT_CLIENT_ID }}\n    private-key: ${{ secrets.COPILOT_PRIVATE_KEY }}\n    owner: ${{ github.repository_owner }}\n# and in the StackVitals step:\ncopilot-token: ${{ steps.copilot.outputs.token }}" },
      { text: "Optional: another org than this repo's owner, under Settings below." }] },
  { id: "ai_spend", name: "AI spend and Claude Code use (Anthropic, OpenAI, Cursor)", glyph: "$", cat: "work", kind: "key", check: "ai_spend", tested: "Live for OpenAI; Anthropic and Cursor recorded", prefix: "connectors.ai_spend",
    doc: C + "#ai-spend", secrets: [{ name: "ANTHROPIC_ADMIN_KEY" }, { name: "OPENAI_ADMIN_KEY" }, { name: "CURSOR_ADMIN_KEY" }],
    unlocks: ["What the AI tools cost each day (Cursor: this billing cycle)", "Spend per merged AI-involved pull request, beside its outcomes", "Claude Code's daily sessions, lines, commits and pull requests (Anthropic key), beside Cursor's agent requests and accepted lines"],
    steps: () => [
      { text: "Make an admin key for each tool you pay for (any one is enough): an Anthropic Admin API key in the Claude Console's organization settings, an OpenAI admin key in its organization settings, a Cursor admin API key in its team settings." },
      { text: "Save each as a repository secret below, then add these lines to the StackVitals step's with: in the workflow:", file: "stackvitals.yml",
        code: "anthropic-admin-key: ${{ secrets.ANTHROPIC_ADMIN_KEY }}\nopenai-admin-key: ${{ secrets.OPENAI_ADMIN_KEY }}\ncursor-admin-key: ${{ secrets.CURSOR_ADMIN_KEY }}" }] },
  { id: "traffic", name: "Traffic history", glyph: "Tr", cat: "github", kind: "key", doc: "install.md", example: true,
    secrets: [{ name: "TRAFFIC_CLIENT_ID", kind: "variable" }, { name: "TRAFFIC_PRIVATE_KEY", multiline: true }],
    unlocks: ["Views, clones and referrers kept past GitHub's 14 days"],
    steps: () => [
      { text: "Create your own GitHub App with the repository permission Administration: read, and install it on the repo.", href: "https://docs.github.com/apps/creating-github-apps", action: "GitHub's guide" },
      { text: "Store its id and private key, then pass a token from actions/create-github-app-token:", file: "stackvitals.yml",
        code: "- uses: actions/create-github-app-token@v3\n  id: app\n  with:\n    client-id: ${{ vars.TRAFFIC_CLIENT_ID }}\n    private-key: ${{ secrets.TRAFFIC_PRIVATE_KEY }}\n# and in the StackVitals step:\ntraffic-token: ${{ steps.app.outputs.token }}" }] },
  { id: "triage", name: "Model triage (Gemini)", glyph: "Ai", cat: "ai", kind: "key", check: "triage", tested: "Live", prefix: "ci.triage", doc: "triage.md", example: true,
    secrets: [{ name: "GEMINI_API_KEY" }],
    unlocks: ["A model's view on up to 3 failures a run that history can't decide", "Shown beside the verdict, never in it"],
    steps: () => [
      { text: "Create a free Google AI Studio key (no card).", href: "https://aistudio.google.com/apikey", action: "Google AI Studio" },
      { text: "Save it as GEMINI_API_KEY below. New installs already pass it:", file: "stackvitals.yml", code: "triage-key: ${{ secrets.GEMINI_API_KEY }}" },
      { text: "Pick the provider under Settings below. A private repo's logs are sent only with allow_private on." }] },
  { id: "gitlab", name: "GitLab (CI and merge requests)", glyph: "GL", cat: "ci", kind: "key", check: "gitlab", tested: "Live reading and token check; the job tested against a stand-in API", doc: C + "#gitlab",
    secrets: [{ name: "GITLAB_TOKEN", kind: "gitlab" }],
    unlocks: ["Flaky jobs, slow jobs and re-run share for GitLab pipelines", "History in the project's stackvitals-data branch, CI Health on GitLab Pages", "One note on a failed merge request pipeline",
      "Delivery for merge requests: review phases, and DORA from the project's production deployments"],
    steps: () => [
      { text: "In .gitlab-ci.yml, include the StackVitals job:", file: ".gitlab-ci.yml",
        code: "include:\n  - remote: https://raw.githubusercontent.com/stackvitals/stackvitals/v0/templates/gitlab/stackvitals.yml" },
      { text: "Add a masked CI/CD variable GITLAB_TOKEN in GitLab: a project access token with the api and write_repository scopes." },
      { text: "Preview: until the v0 tag exists, use main in the URL and set the STACKVITALS_REF variable to main." },
      { text: "Read-only from your machine instead:", file: "Terminal", code: "stackvitals ci gitlab group/project" },
      { text: "Delivery from merge requests and deployments (gitlab.com shows merge request notes only with GITLAB_TOKEN, even on public projects):", file: "Terminal",
        code: "stackvitals delivery group/project --gitlab" }] },
  { id: "otherci", name: "Test reports from Jenkins, CircleCI, Buildkite", glyph: "Ts", cat: "ci", kind: "local", tested: "Recorded", doc: C + "#other-ci-systems",
    unlocks: ["Flaky tests, failure groups and monitors for tests that run outside GitHub Actions"],
    steps: () => [{ text: "At the end of the job, with STACKVITALS_TOKEN set to a token that can write the repo:", file: "Terminal",
      code: 'pip install stackvitals\nstackvitals ci upload --repo owner/name --sha "$SHA" --branch "$BRANCH" --run-id "$BUILD_ID" --provider jenkins test-results/*.xml' }] },
  { id: "agents", name: "AI agents (MCP)", glyph: "Ag", cat: "ai", kind: "local", doc: "modules.md",
    unlocks: ["Agents check CI history before \"fixing\" a flaky test", "Who should review, what to fix first, package checks", "Investigation prompts per failure group"],
    steps: () => [{ text: "Pick your agent and copy its config on the Agents page.", to: "#/agents", action: "Open Agents" }] },
  { id: "s3", name: "S3-compatible storage", glyph: "S3", cat: "data", kind: "key", check: "s3", doc: "install.md", example: true,
    secrets: [{ name: "S3_KEY_ID" }, { name: "S3_SECRET" }],
    unlocks: ["History in your own bucket (AWS S3, Cloudflare R2, MinIO)", "For very busy repos and big orgs"],
    steps: () => [
      { text: "The bucket service must support replace-only-if-unchanged writes (If-Match). Switching starts a fresh history." },
      { text: "Save an access key that can read, write, delete and list the prefix as the two secrets below." },
      { text: "Set the storage inputs, and publish with pages deploy or artifact:", file: "stackvitals.yml",
        code: "storage: s3://my-bucket/stackvitals\ns3-endpoint: https://<account>.r2.cloudflarestorage.com\ns3-region: auto\ns3-key-id: ${{ secrets.S3_KEY_ID }}\ns3-secret: ${{ secrets.S3_SECRET }}\npages: artifact" },
      { text: "stackvitals ui and sql, Explore, the MCP server and the Portal org view don't read a bucket yet." }] },
  { id: "devlake", name: "DevLake and Postgres export", glyph: "DL", cat: "data", kind: "local", tested: "Recorded", doc: "scaling.md",
    unlocks: ["DevLake's own DORA dashboard SQL on your data", "Any SQL over every repo's tables", "Your tables in Neon, Supabase or any Postgres"],
    steps: () => [{ text: "Export DevLake's tables with its DORA SQL, or query the summaries directly:", file: "Terminal",
      code: 'stackvitals export owner/repo --format devlake --out ./devlake\nstackvitals sql --repo owner/repo "select role, count(*) from prs group by role"' }] },
  { id: "otel", name: "OpenTelemetry export", glyph: "OT", cat: "data", kind: "local", tested: "Recorded", doc: "modules.md",
    unlocks: ["CI runs, jobs and steps as traces", "OTLP JSON for Grafana Tempo, Honeycomb, Datadog or any collector", "Failed and flaky tests as events with --tests"],
    steps: () => [{ text: "Export from your machine; the file is written locally and sent nowhere:", file: "Terminal", code: "stackvitals export owner/repo --format otel --tests" }] },
  { id: "backstage", name: "Backstage catalog", glyph: "Bs", cat: "data", kind: "builtin", tested: "Live", doc: "modules.md",
    unlocks: ["Each repo's catalog-info.yaml as a typed catalog in Portal", "Owners checked against CODEOWNERS", "portal/entities.yaml with a Component for repos without one"],
    steps: () => [
      { text: "Portal reads catalog-info.yaml files by itself (Backstage's format, which Port and Cortex also read)." },
      { text: "To see Portal's view in Backstage, register the URL of portal/entities.yaml on the data branch as one location." }] },
];

export interface View { app: AppJson; entries: Record<string, Entry>; secrets: string[] | null; settings: SettingsFile | null }

export function entryOf(c: Conn, entries: Record<string, Entry>): Entry | null {
  return entries[c.check || c.id] || entries[c.id] || null;
}

function defaults(s: SettingsFile | null, prefix?: string): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const d of s?.settings || []) if (prefix && d.key.startsWith(prefix + ".")) out[d.key.slice(prefix.length + 1)] = d.default;
  return out;
}

export function statusFor(c: Conn, v: View): Status {
  const vals = c.prefix ? valueAt(v.settings?.values, c.prefix) as Record<string, unknown> | undefined : undefined;
  return statusOf(c, entryOf(c, v.entries), v.secrets, isConfigured(vals, defaults(v.settings, c.prefix)));
}

// One sentence under the status pill in the sheet.
export function detail(c: Conn, s: Status, e: Entry | null, v: View): string {
  if (c.id === "github") return `${Object.keys(v.app.modules || {}).length} modules ran; last run ${ago(freshest(v.app))}.`;
  if (s === "builtin") return c.id === "backstage" ? "Read by Portal on its own; nothing to add." : "Works on its own; nothing to add.";
  if (s === "failed") return e?.error || e?.check?.detail || "The last check failed.";
  const gone = missing(c, v.secrets);
  if (s === "recorded") return `History is kept, but the repo no longer has ${gone.join(" and ")}, so nothing new is read.`;
  if (s === "key") return e?.expiring ? `The key expires on ${day(e.key_expires)}: create a new one and update the secret.` : gone.length ? `Missing ${gone.join(" and ")}.` : "Settings are filled in; the key isn't there yet.";
  if (s === "connected") {
    if (!e?.as_of) return e?.check?.ok ? `The last test passed ${ago(e.check.checked_at)}.` : "Everything is in place; the next run reads it.";
    const rows = Object.values(e.rows || {}).reduce((a, b) => a + b, 0);
    return `Last read ${ago(e.as_of)}${rows ? `, ${count(rows, "record")} kept` : ""}${e.complete === false ? ", still catching up" : ""}.`;
  }
  return c.kind === "local" ? "Runs from your machine or your CI; nothing here shows whether it is set up." : "Not set up yet.";
}
