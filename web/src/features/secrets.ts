// Connections' GitHub calls: the repo's secret names, saving a secret sealed with the repo's Actions public key (only the
// sealed value leaves the browser), starting a connection check and reading its result back from connectors.json.
import { makeApi, sleep, type Api } from "../github/client";
import { accountToken } from "../github/token";
import { current } from "../data/repos";
import { fetchText, type Source } from "../data/source";
import { isRepo, repoPath, wfPath } from "../github/names";
import { writeToken } from "../github/session";
import type { AppJson } from "../data/types";
import { token as writeTokenTab } from "../data/write";
import { newIssue, type PrefillLink } from "../github/links";
import type { Entry } from "./connstatus";

export const ghToken = (): string | null => accountToken() || writeTokenTab() || null;
const api = (): Api => makeApi(ghToken());

export const SECRET_RE = /^(?!github_)[a-z_][a-z0-9_]*$/i;

export function b64encode(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}
export function b64decode(b64: string): Uint8Array {
  return Uint8Array.from(atob(b64.replace(/\s/g, "")), (c) => c.charCodeAt(0));
}

// The value sealed for GitHub; the crypto chunk loads on the first save.
export async function sealFor(publicKey: string, value: string): Promise<string> {
  const { seal } = await import("./sealbox");
  return b64encode(seal(new TextEncoder().encode(value), b64decode(publicKey)));
}

export function newSecretUrl(repo: string, kind: "secret" | "variable" = "secret"): string {
  return `https://github.com/${repo}/settings/${kind === "variable" ? "variables" : "secrets"}/actions/new`;
}

export function tokenUrl(repo: string): string {
  const q = new URLSearchParams({ name: "StackVitals connections", description: `Lets the StackVitals app save keys and test connections in ${repo}`,
    target_name: repo.split("/")[0]!, expires_in: "30", secrets: "write", actions: "write" });
  return `https://github.com/settings/personal-access-tokens/new?${q}`;
}

// Secret names (never values); null when there is no token or it can't list them.
export async function listSecrets(repo: string): Promise<string[] | null> {
  if (!ghToken() || !isRepo(repo)) return null;
  try {
    const r = await api().call<{ secrets?: { name: string }[] }>("GET", `/repos/${repoPath(repo)}/actions/secrets?per_page=100`);
    return r.ok ? (r.data.secrets || []).map((s) => s.name) : null;
  } catch {
    return null;
  }
}

const said = (status: number, what: string) => status === 401 ? "GitHub refused the token: it may be expired or mistyped."
  : status === 403 || status === 404 ? `The token can't ${what} here; it needs Secrets: read and write on this repo.` : `GitHub answered ${status}.`;

// A signed-in token is renewed first when it is about to end.
const freshApi = async (): Promise<Api> => makeApi((await writeToken()) || writeTokenTab() || null);

export async function saveSecret(repo: string, name: string, value: string): Promise<void> {
  const where = repoPath(repo);
  if (!SECRET_RE.test(name)) throw new Error("Secret names use letters, digits and _, don't start with a digit and can't start with GITHUB_.");
  const a = await freshApi();
  const key = await a.call<{ key_id: string; key: string }>("GET", `/repos/${where}/actions/secrets/public-key`);
  if (!key.ok) throw new Error(said(key.status, "read the secrets key"));
  const sealed = await sealFor(key.data.key, value);
  const put = await a.call("PUT", `/repos/${where}/actions/secrets/${encodeURIComponent(name)}`, { encrypted_value: sealed, key_id: key.data.key_id });
  if (!put.ok) throw new Error(said(put.status, "save secrets"));
}

export interface Started { url: string | null; run?: number }
interface Asked { repo: string; source: Source; since: number; run?: number }
// The last check started per connection, so waiting for it can watch that run.
const asked = new Map<string, Asked>();

// The check's own run: a dispatch on this workflow created after GitHub's clock said the dispatch was sent.
async function findCheckRun(a: Api, repo: string, wf: string, since: number): Promise<number | undefined> {
  const r = await a.call<{ workflow_runs?: { id: number; created_at: string }[] }>("GET", `/repos/${repo}/actions/workflows/${wf}/runs?event=workflow_dispatch&per_page=10`);
  const runs = r.ok ? r.data?.workflow_runs || [] : [];
  return runs.filter((x) => Date.parse(x.created_at) >= since).sort((x, y) => x.id - y.id)[0]?.id;
}

// Starts the workflow with {"check": [name]}; the run that answers writes the result into connectors.json.
export async function startCheck(app: AppJson, name: string): Promise<Started> {
  if (!app.links?.workflow) throw new Error("This page doesn't know the workflow's file name yet; test it with the GitHub issue instead.");
  const repo = repoPath(app.repo), wf = wfPath(app.links.workflow);
  const a = await freshApi();
  const req = JSON.stringify({ version: 1, changes: [], settings: {}, check: [name] });
  const r = await a.call("POST", `/repos/${repo}/actions/workflows/${wf}/dispatches`, { ref: app.default_branch || "main", inputs: { request: req } });
  if (!r.ok) throw new Error(r.status === 422 ? "This repo's StackVitals workflow is older and takes no request; update it, or use the GitHub issue."
    : r.status === 401 ? "GitHub refused the token." : "The token can't start this repo's workflow (it needs Actions: read and write).");
  // GitHub's own clock, a little early, so the browser's clock can't miss the run.
  const since = (Date.parse(r.headers.get("date") || "") || Date.now()) - 5000;
  const job: Asked = { repo, source: current.get().source, since };
  asked.set(name, job);
  job.run = await findCheckRun(a, repo, wf, since).catch(() => undefined);
  (job as Asked & { wf?: string }).wf = wf;
  return { url: app.links?.actions || null, ...(job.run ? { run: job.run } : {}) };
}

export function checkIssueUrl(app: AppJson, name: string, label: string): PrefillLink {
  const req = JSON.stringify({ version: 1, changes: [], settings: {}, check: [name] });
  const body = `Sent from the StackVitals app: test the ${label} connection. The StackVitals workflow runs the check when someone ` +
    `with access opens this, writes the result to the app and answers here.\n\n\`\`\`stackvitals\n${req}\n\`\`\`\n`;
  return newIssue(app.repo, `StackVitals: test ${label}`, body);
}

// connectors.json read fresh (no cache), for polling after a check was asked for; from `source`, else the open repo.
export async function freshConnectors(source: Source = current.get().source): Promise<Record<string, Entry> | null> {
  const text = await fetchText(source, "connectors.json");
  try { return text ? (JSON.parse(text).connectors as Record<string, Entry>) || {} : null; } catch { return null; }
}

export const REPLACED = "The run was replaced by another StackVitals run; test again.";

// Polls the repo the check started on (even if another repo is opened meanwhile) until the entry's check is newer than
// `since`, for up to `max` tries; null if none came. Throws REPLACED when the check's run was cancelled by a newer one.
export async function waitForCheck(name: string, since: string, live: () => boolean, every = 8000, max = 75): Promise<Entry | null> {
  const job = asked.get(name) as (Asked & { wf?: string }) | undefined;
  const source = job?.source || current.get().source;
  let doneAt = -1;
  for (let i = 0; i < max && live(); i++) {
    await sleep(every);
    const e = (await freshConnectors(source))?.[name];
    if (e?.check?.checked_at && Date.parse(e.check.checked_at) > Date.parse(since)) return e;
    if (!job || !ghToken()) continue;
    const a = api();
    if (!job.run && job.wf) job.run = await findCheckRun(a, job.repo, job.wf, job.since).catch(() => undefined);
    if (!job.run) continue;
    const r = await a.call<{ status: string; conclusion: string | null }>("GET", `/repos/${job.repo}/actions/runs/${encodeURIComponent(job.run)}`).catch(() => null);
    if (r?.ok && r.data.status === "completed") {
      if (r.data.conclusion === "cancelled" || r.data.conclusion === "skipped") throw new Error(REPLACED);
      // Finished: give the published file two more reads to show the result.
      if (doneAt < 0) doneAt = i;
      else if (i - doneAt >= 2) return null;
    }
  }
  return null;
}

// Linear lets a browser call its API with a key: the key goes only to api.linear.app.
export async function testLinear(key: string): Promise<{ ok: boolean; text: string }> {
  try {
    const r = await fetch("https://api.linear.app/graphql", { method: "POST", headers: { Authorization: key, "Content-Type": "application/json" },
      body: JSON.stringify({ query: "query { viewer { name } organization { name } teams(first: 100) { nodes { key } } }" }), credentials: "omit", cache: "no-store" });
    const body = await r.json().catch(() => null) as { data?: { viewer?: { name?: string }; organization?: { name?: string }; teams?: { nodes?: { key: string }[] } }; errors?: { message?: string }[] } | null;
    if (!r.ok || !body?.data) return { ok: false, text: r.status === 401 || body?.errors?.length ? "Linear refused the key: it is wrong or expired." : `Linear answered ${r.status}.` };
    const teams = (body.data.teams?.nodes || []).map((t) => t.key);
    return { ok: true, text: `Signed in as ${body.data.viewer?.name || "the key's user"} (${body.data.organization?.name || "Linear"}), sees ${teams.length} ${teams.length === 1 ? "team" : "teams"}${teams.length ? ": " + teams.slice(0, 4).join(", ") : ""}.` };
  } catch {
    return { ok: false, text: "Linear couldn't be reached from this page." };
  }
}
