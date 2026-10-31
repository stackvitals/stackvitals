// Portal's setup files and links, as the CLI prints them (ports of portal/cli.py WORKFLOW and app_link; a test compares).
import { ACTION_REF } from "../../github/workflow";

export const PORTAL_FILE = ".github/workflows/stackvitals-portal.yml";

const WORKFLOW = `name: StackVitals Portal
on:
  schedule:
    - cron: "41 5 * * *"   # once a day
  workflow_dispatch:
    inputs:
      request:
        description: "A request from the StackVitals app, like a golden path (leave empty for a normal run)"
        required: false
        default: ""
  issues:
    types: [opened]          # golden path requests from the app, run at once
  issue_comment:
    types: [created]         # "/stackvitals approve" on a golden path that needs an approval
permissions:
  contents: write          # keeps the catalog, its history and the pages in this repo's stackvitals-data branch
  issues: write            # one tracking issue per campaign, and answers to requests, in this repo only
concurrency:
  group: stackvitals-portal
  cancel-in-progress: false
jobs:
  portal:
    # Request issues start a run only when someone with access to this repo opened one with a StackVitals block.
    if: >-
      (github.event_name != 'issues' ||
       (contains(github.event.issue.body, '\`\`\`stackvitals') &&
        contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.issue.author_association))) &&
      (github.event_name != 'issue_comment' ||
       (startsWith(github.event.comment.body, '/stackvitals approve') &&
        contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.comment.author_association)))
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      # Private repos: create an org-owned read-only GitHub App (see docs/modules.md), store its client ID and key, then switch on.
      # - uses: actions/create-github-app-token@64ab729a6294000f5aa4a4bc0b73d1f32bc45510 # v3
      #   id: app
      #   with:
      #     client-id: \${{ vars.PORTAL_CLIENT_ID }}
      #     private-key: \${{ secrets.PORTAL_PRIVATE_KEY }}
      #     owner: \${{ github.repository_owner }}
      - uses: {ref}
        with:
          modules: portal
          # portal-token: \${{ steps.app.outputs.token }}
`;

// The workflow `stackvitals portal init` prints; with `app`, the org App's token step is switched on (private repos).
export function portalWorkflow(opts: { app?: boolean; ref?: string } = {}): string {
  const text = WORKFLOW.replace("{ref}", opts.ref || ACTION_REF);
  if (!opts.app) return text;
  return text.split("\n").map((l) => (/^ *# (- uses: actions\/create-github-app-token| {2}id: app| {2}with:| {4}(client-id|private-key|owner):|portal-token:)/.test(l)
    ? l.replace("# ", "") : l)).join("\n").replace("Private repos: create an org-owned read-only GitHub App (see docs/modules.md), store its client ID and key, then switch on.",
    "Private repos: the org App's token (its client ID in the variable PORTAL_CLIENT_ID, its key in the secret PORTAL_PRIVATE_KEY).");
}

// GitHub's "register an App" form for the org, filled in: read-only, no webhook, private; `writes` adds what golden paths
// and required checks need. Same parameters, in the same order, as app_link in portal/cli.py.
export function appLink(org: string, writes = false): string {
  const p: [string, string][] = [["name", `${org} portal ${writes ? "" : "reader"}`.trim().slice(0, 34)],
    ["description", "StackVitals Portal: the org catalog, owners and scorecards" + (writes ? "; required checks and golden paths." : " (read-only).")],
    ["url", `https://github.com/${org}`], ["public", "false"], ["webhook_active", "false"], ["actions", "read"], ["contents", writes ? "write" : "read"],
    ["metadata", "read"], ["members", "read"], ["organization_custom_properties", "read"]];
  if (writes) p.push(["checks", "write"], ["pull_requests", "write"], ["administration", "write"], ["workflows", "write"]);
  return `https://github.com/organizations/${encodeURIComponent(org)}/settings/apps/new?${p.map(([k, v]) => `${k}=${plus(v)}`).join("&")}`;
}
// Python's urlencode: spaces as +, the rest percent-encoded except letters, digits and _.-~
const plus = (s: string) => encodeURIComponent(s).replace(/[!'()*]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase()).replace(/%20/g, "+");

// GitHub's new-repo form, filled in (private by default).
export function newRepoLink(owner: string, name = "portal"): string {
  return `https://github.com/new?owner=${encodeURIComponent(owner)}&name=${encodeURIComponent(name)}&visibility=private` +
    `&description=${encodeURIComponent("StackVitals Portal: the org's catalog, owners and scorecards")}`;
}

// A CODEOWNERS that gives every file to the suggested people: "* @a @b".
export function codeowners(people: string[]): string {
  return `# Owners suggested by StackVitals Portal from recent activity; narrow the paths as teams take parts over.\n* ${people.map((p) => (p.startsWith("@") ? p : "@" + p)).join(" ")}\n`;
}

export interface CatalogForm { name: string; title?: string; description?: string; type: string; lifecycle: string; owner: string; system?: string }

// A Backstage catalog-info.yaml (the format Backstage, Port and Cortex read); values quoted when YAML would misread them.
export function catalogYaml(f: CatalogForm): string {
  const q = (s: string) => (/^[A-Za-z0-9][A-Za-z0-9 _./:@-]*$/.test(s) && !/: |\s$/.test(s) && !/^(true|false|null|yes|no|on|off|~)$/i.test(s) ? s : JSON.stringify(s));
  const lines = ["apiVersion: backstage.io/v1alpha1", "kind: Component", "metadata:", `  name: ${q(f.name)}`];
  if (f.title?.trim()) lines.push(`  title: ${q(f.title.trim())}`);
  if (f.description?.trim()) lines.push(`  description: ${q(f.description.trim())}`);
  lines.push("spec:", `  type: ${q(f.type)}`, `  lifecycle: ${q(f.lifecycle)}`, `  owner: ${q(f.owner)}`);
  if (f.system?.trim()) lines.push(`  system: ${q(f.system.trim())}`);
  return lines.join("\n") + "\n";
}

// Backstage's entity name rule: letters, digits and - _ . between letters or digits, at most 63.
export const entityName = (s: string) => s.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, "").slice(0, 63) || "component";

// A CODEOWNERS owner (@org/team or @person) as a catalog owner: group:team or user:person.
export function ownerRef(o: string | undefined): string {
  if (!o) return "";
  const s = o.replace(/^@/, "");
  return s.includes("/") ? `group:${s.split("/").pop()}` : `user:${s}`;
}
