// Delivery's other sources: a recipe builder that writes the ready step for a deploy tool GitHub can't see (Argo CD,
// Jenkins, GitLab CI, any script) with this repo filled in, plus the two commands that must run on your machine.
import { useEffect, useState } from "preact/hooks";
import { demoMode } from "../../data/repos";
import type { AppJson } from "../../data/types";
import { workflowText } from "../../features/settingsApply";
import { Button } from "../../ui/Button";
import { CodeBlock, DOCS } from "../../ui/bits";
import { Chips, Field, Select, TextInput } from "../../ui/controls";
import { Facts, Machine, Mark, Panel } from "./blocks";

type Tool = "argo" | "jenkins" | "gitlab" | "script" | "cli";
type Kind = "deployment" | "incident";
const TOOLS: { value: Tool; label: string; kinds: Kind[]; file: string }[] = [
  { value: "argo", label: "Argo CD (notifications)", kinds: ["deployment"], file: "argocd-notifications-cm (in your cluster)" },
  { value: "jenkins", label: "Jenkins pipeline", kinds: ["deployment", "incident"], file: "Jenkinsfile (in the repo Jenkins builds)" },
  { value: "gitlab", label: "GitLab CI", kinds: ["deployment", "incident"], file: ".gitlab-ci.yml (in the GitLab project)" },
  { value: "script", label: "Any script, Spinnaker, Octopus or a webhook (curl)", kinds: ["deployment", "incident"], file: "your deploy script" },
  { value: "cli", label: "A terminal with StackVitals installed", kinds: ["deployment", "incident"], file: "a shell" },
];
const NOW = "$(date -u +%Y-%m-%dT%H:%M:%SZ)";
const q = (s: string) => s.replace(/["\\$`]/g, "");

// The ready snippet for one tool; the fields are the ones core/recorded.py accepts.
export function recipe(repo: string, tool: Tool, kind: Kind, env: string): string {
  const e = q(env.trim() || "production");
  const url = `https://api.github.com/repos/${repo}/dispatches`;
  const cli = (id: string, sha: string, name: string, extra = "") => kind === "deployment"
    ? `stackvitals record deployment ${repo} --id "${id}" --sha "${sha}" --environment "${e}"${extra} --tool ${name}`
    : `stackvitals record incident ${repo} --id "${id}" --at "$INCIDENT_STARTED_AT" --tool ${name}`;
  if (tool === "argo") return `# argocd-notifications-cm: keep the token in argocd-notifications-secret as stackvitals-token,
# then subscribe the app: notifications.argoproj.io/subscribe.on-deployed.stackvitals: ""
service.webhook.stackvitals: |
  url: ${url}
  headers:
  - name: Authorization
    value: Bearer $stackvitals-token
  - name: Accept
    value: application/vnd.github+json
template.stackvitals-deployed: |
  webhook:
    stackvitals:
      method: POST
      body: |
        {"event_type":"stackvitals-deployment","client_payload":{"id":"{{.app.metadata.name}}-{{.app.status.operationState.syncResult.revision}}","sha":"{{.app.status.operationState.syncResult.revision}}","finished_at":"{{.app.status.operationState.finishedAt}}","environment":"${e}","tool":"argo-cd"}}`;
  if (tool === "jenkins") {
    const step = (status: string) => `withCredentials([string(credentialsId: 'stackvitals-token', variable: 'GITHUB_TOKEN')]) {
        sh 'pip install --quiet stackvitals && ${cli("jenkins-$BUILD_TAG", "$GIT_COMMIT", "jenkins", status === "failure" ? " --status failure" : "")}'
      }`;
    return kind === "deployment" ? `// In the deploy stage of your Jenkinsfile; the credential is a secret text with the token.
post {
  success {
    script {
      ${step("success")}
    }
  }
  failure {
    script {
      ${step("failure")}
    }
  }
}` : `// When your pipeline opens an incident; INCIDENT_STARTED_AT is a time like 2026-10-29T09:12:00Z.
withCredentials([string(credentialsId: 'stackvitals-token', variable: 'GITHUB_TOKEN')]) {
  sh 'pip install --quiet stackvitals && ${cli("jenkins-$BUILD_TAG", "", "jenkins")}'
}`;
  }
  if (tool === "gitlab") return `# .gitlab-ci.yml: runs after your deploy job; GITHUB_TOKEN is a masked CI/CD variable holding the token.
stackvitals-record:
  stage: .post
  image: python:3.12-slim
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  script:
    - pip install --quiet stackvitals
    - ${kind === "deployment" ? cli("gitlab-$CI_PIPELINE_ID", "$CI_COMMIT_SHA", "gitlab") : cli("gitlab-$CI_PIPELINE_ID", "", "gitlab")}`;
  if (tool === "cli") return `export GITHUB_TOKEN=...   # the token below
${kind === "deployment" ? cli("deploy-1287", "$GIT_SHA", "script") : `stackvitals record incident ${repo} --id "INC-42" --at 2026-10-29T09:12:00Z --resolved-at 2026-10-29T10:03:00Z --tool script`}`;
  const payload = kind === "deployment"
    ? `{"event_type":"stackvitals-deployment","client_payload":{"id":"'"$DEPLOY_ID"'","sha":"'"$GIT_SHA"'","environment":"${e}","status":"success","finished_at":"'"${NOW}"'","tool":"script"}}`
    : `{"event_type":"stackvitals-incident","client_payload":{"id":"'"$INCIDENT_ID"'","created_at":"'"$STARTED_AT"'","tool":"script"}}`;
  return `# DEPLOY_ID / INCIDENT_ID: your tool's own id (sending it again updates the record); STACKVITALS_TOKEN: the token below.
curl -fsS -X POST "${url}" \\
  -H "Authorization: Bearer $STACKVITALS_TOKEN" -H "Accept: application/vnd.github+json" \\
  -d '${payload}'`;
}

// A fine-grained token for this one repo with Contents: write, GitHub's rule for repository_dispatch.
const tokenUrl = (repo: string) => `https://github.com/settings/personal-access-tokens/new?name=${encodeURIComponent("StackVitals deployments")}` +
  `&description=${encodeURIComponent(`Lets a deploy tool send deployments and incidents to ${repo}`)}&target_name=${encodeURIComponent(repo.split("/")[0]!)}&expires_in=90&contents=write`;

function Recorder({ app }: { app: AppJson }) {
  const [tool, setTool] = useState<Tool>("argo");
  const [kind, setKind] = useState<Kind>("deployment");
  const [env, setEnv] = useState("production");
  const [listens, setListens] = useState<boolean | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    // The demo's repos aren't on GitHub: nothing to read.
    if (demoMode) { setListens(null); return; }
    void workflowText(app).then((t) => { if (live) setListens(t == null ? null : /stackvitals-deployment/.test(t)); });
    return () => { live = false; };
  }, [app.repo]);
  const t = TOOLS.find((x) => x.value === tool)!;
  const k = t.kinds.includes(kind) ? kind : "deployment";
  return <Panel title="Record deployments and incidents from another tool" class="dl-rec"
    state={listens === false ? <Mark tone="watch">Workflow needs an update</Mark> : listens ? <Mark tone="good">Workflow listens</Mark> : <Mark tone="neutral">Ready to copy</Mark>}
    bar={<><Button size="sm" variant="tinted" href={tokenUrl(app.repo)} external iconEnd="external">Create the token</Button>
      <Button size="sm" variant="plain" href={DOCS + "connectors.md#deployments-and-incidents-from-elsewhere"} external iconEnd="external">All fields</Button></>}>
    <div class="blk-form">
      <Field label="Your tool">{(id) => <Select id={id} value={tool} onChange={(v) => setTool(v as Tool)} options={TOOLS.map((x) => ({ value: x.value, label: x.label }))} />}</Field>
      <Field label="What it sends" hint={t.kinds.length === 1 ? "Argo CD sends deployments; incidents come from a script or your pager." : undefined}>{(id) =>
        <Select id={id} value={k} onChange={(v) => setKind(v as Kind)} options={t.kinds.map((x) => ({ value: x, label: x === "deployment" ? "Deployments" : "Incidents" }))} />}</Field>
      {k === "deployment" ? <Field label="Environment" hint="Only production counts in DORA.">{(id) => <TextInput id={id} value={env} onInput={setEnv} maxLength={60} />}</Field> : null}
    </div>
    <CodeBlock title={`Paste into ${t.file}`} code={recipe(app.repo, tool, k, env)} />
    <Facts rows={[
      ["Token it needs", <>A fine-grained token for {app.repo} with <b>Contents: read and write</b> (GitHub's rule for dispatch events), kept in your tool's secret store.</>],
      ["Where it lands", "The StackVitals workflow keeps each one on the data branch (delivery/recorded.ndjson); the next scheduled run counts it like GitHub's own."],
      ["This repo's workflow", listens === undefined ? "Checking…" : listens === null ? (demoMode ? "Not checked in the demo; the current workflow template has the repository_dispatch trigger." : "Couldn't read it from here (a private repo needs a token); it needs the repository_dispatch trigger.")
        : listens ? "Has the repository_dispatch trigger for these events." : <>Set up before this trigger existed: <a href="#/setup">update the workflow</a> so it accepts them.</>],
      ["Why not a button here", "Your deploy tool has to send each one as it happens; a deployment sent from this page would be made up."],
    ]} />
  </Panel>;
}

type Host = "bitbucket" | "azure" | "gitlab";
const HOSTS: { value: Host; label: string; path: string; env: string }[] = [
  { value: "bitbucket", label: "Bitbucket Cloud", path: "workspace/repo", env: "BITBUCKET_TOKEN (an access token)" },
  { value: "azure", label: "Azure DevOps", path: "org/project/repo", env: "AZURE_DEVOPS_TOKEN (a PAT with Code: read)" },
  { value: "gitlab", label: "GitLab", path: "group/project", env: "GITLAB_TOKEN (needed for review times, even on public projects)" },
];

function OtherHost() {
  const [host, setHost] = useState<Host>("bitbucket");
  const [path, setPath] = useState("");
  const h = HOSTS.find((x) => x.value === host)!;
  const name = path.trim().replace(/\s+/g, "") || h.path;
  return <Machine title="Code on Bitbucket, Azure DevOps or GitLab"
    does="The same review phases and DORA for code hosted there, read-only."
    why="It reads another host with that host's token; nothing from there reaches this repo's data, so the app has nothing to show."
    needs={<><code>pip install stackvitals</code>; private projects take {h.env}.</>}>
    <div class="blk-form">
      <Field label="Host">{(id) => <Select id={id} value={host} onChange={(v) => setHost(v as Host)} options={HOSTS.map((x) => ({ value: x.value, label: x.label }))} />}</Field>
      <Field label="Project" hint={`Like ${h.path}`}>{(id) => <TextInput id={id} value={path} onInput={setPath} placeholder={h.path} maxLength={200} />}</Field>
    </div>
    <CodeBlock inline code={`stackvitals delivery ${name} --${host}`} />
  </Machine>;
}

function Project({ repo }: { repo: string }) {
  const [name, setName] = useState("web");
  const [others, setOthers] = useState<string[]>([]);
  const list = [repo, ...others.filter((r) => r !== repo)];
  const n = name.trim().replace(/[^\w.-]/g, "-") || "web";
  return <Machine title="One project across several repos"
    does="Pools the repos and runs DevLake's own DORA SQL on them, next to each repo's numbers."
    why="It reads every repo's history with your token and runs the SQL locally in DuckDB; this page holds one repo's data."
    needs={<>Python with <code>pip install 'stackvitals[sql]'</code> and a token (<code>GITHUB_TOKEN</code>) that can read every repo.</>}>
    <div class="blk-form">
      <Field label="Project name">{(id) => <TextInput id={id} value={name} onInput={setName} maxLength={60} />}</Field>
      <Field label="Other repos" hint={`owner/name; ${repo} is already in.`}>{(id) => <Chips id={id} values={others} onChange={(v) => setOthers(v.filter((x) => /^[\w.-]+\/[\w.-]+$/.test(x)))} placeholder="org/api" label="Other repos" />}</Field>
    </div>
    <CodeBlock title="Terminal" code={`pip install 'stackvitals[sql]'\nstackvitals project ${n} ${list.join(" ")}${others.length ? "" : " org/api org/worker"}`} />
    {others.length ? null : <p class="blk-note">Add the other repos above; org/api and org/worker are placeholders.</p>}
  </Machine>;
}

export function OtherSources({ app }: { app: AppJson }) {
  return <div class="dl-sources">
    <Recorder app={app} />
    <div class="blk-grid"><OtherHost /><Project repo={app.repo} /></div>
  </div>;
}
