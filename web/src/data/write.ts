// How a change reaches the repo: the page never writes itself; the StackVitals workflow checks who asked and applies it,
// from a prefilled issue (default), a dispatch with your own token (opt-in), or lines you paste.
import type { AppJson } from "./types";

// No runtime imports: this file also runs on its own in tests. Same rules as github/names.ts.
const isRepo = (s: unknown): s is string => typeof s === "string" && /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(s) && !s.split("/").some((p) => p === "." || p === "..");
function repoPath(s: unknown): string {
  if (!isRepo(s)) throw new Error(`"${String(s).slice(0, 80)}" isn't a repo name (owner/name)`);
  return s.split("/").map(encodeURIComponent).join("/");
}
function wfPath(s: unknown): string {
  if (typeof s !== "string" || !/^[A-Za-z0-9_.-]+\.ya?ml$/.test(s)) throw new Error(`"${String(s).slice(0, 80)}" isn't a workflow file name`);
  return encodeURIComponent(s);
}
// Sign-out hooks live on a shared global (see github/signout.ts), so no import is needed.
const onSignOut = (fn: () => void) => ((globalThis as any)[Symbol.for("sv.signout")] ??= new Set<() => void>()).add(fn);

let memoryToken: string | null = null;

export interface Change { verb: string; kind: string; id: string; until?: string | null; reason?: string }
export interface Req { version: 1; changes: Change[]; settings: Record<string, unknown> }

// An item in a /stackvitals command, quoted when it has spaces, quotes or backslashes so the Action reads it back exactly.
export function target(kind: string, id: string): string {
  return `${kind}:${/[\s"'\\]/.test(id) ? JSON.stringify(id) : id}`;
}

export function request(changes: Change[] = [], settings: Record<string, unknown> = {}): Req {
  return { version: 1, changes, settings };
}

export function requestBody(req: Req, note = ""): string {
  return `${note ? note + "\n\n" : ""}Sent from the StackVitals app. The StackVitals workflow applies this when someone with access opens it, ` +
    `answers here and closes it.\n\n\`\`\`stackvitals\n${JSON.stringify(req)}\n\`\`\`\n`;
}

export function token(): string | null {
  if (memoryToken) return memoryToken;
  try { return sessionStorage.getItem("sv:token"); } catch { return null; }
}

export function setToken(value: string | null, keepForTab = false): void {
  memoryToken = value || null;
  try {
    if (value && keepForTab) sessionStorage.setItem("sv:token", value);
    else sessionStorage.removeItem("sv:token");
  } catch { /* storage refused: memory only */ }
}

// Signing out of GitHub forgets a pasted token too.
onSignOut(() => setToken(null));

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`https://api.github.com${path}`, {
    ...init, headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token()}`, "X-GitHub-Api-Version": "2022-11-28",
      ...(init.body ? { "Content-Type": "application/json" } : {}) },
  });
  if (!res.ok) {
    const refused = [401, 403, 404].includes(res.status);
    if (refused) setToken(null);
    const why = res.status === 401 ? "the token was refused" : refused
      ? "the token can't run this repo's workflows (it needs Actions: read and write on this repo)"
      : res.status === 422 ? "this repo's StackVitals workflow is older and takes no request; update it, or use the GitHub issue"
        : `GitHub answered ${res.status}`;
    throw new Error(why);
  }
  return (res.status === 204 ? null : await res.json()) as T;
}

export interface Run { id: number; run_number: number; html_url: string; status: string; conclusion?: string | null }

// Starts the StackVitals workflow with the request; resolves with the run once GitHub lists it.
export async function dispatch(app: AppJson, req: Req): Promise<Run | null> {
  if (!app.links?.workflow) throw new Error("this page doesn't know the workflow's file name yet; use the GitHub issue instead");
  const repo = repoPath(app.repo), wf = wfPath(app.links.workflow);
  const list = async () => (await api<{ workflow_runs?: Run[] }>(`/repos/${repo}/actions/workflows/${wf}/runs?event=workflow_dispatch&per_page=5`)).workflow_runs || [];
  const before = Math.max(0, ...(await list()).map((r) => r.id));
  await api(`/repos/${repo}/actions/workflows/${wf}/dispatches`, { method: "POST",
    body: JSON.stringify({ ref: app.default_branch, inputs: { request: JSON.stringify(req) } }) });
  for (let i = 0; i < 10; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const run = (await list()).filter((r) => r.id > before).sort((a, b) => a.id - b.id)[0];
    if (run) return run;
  }
  return null;
}

export function runStatus(app: AppJson, id: number): Promise<Run> {
  return api<Run>(`/repos/${repoPath(app.repo)}/actions/runs/${encodeURIComponent(id)}`);
}

export function tokenLink(app: AppJson): string {
  const owner = app.repo.split("/")[0]!;
  return `https://github.com/settings/personal-access-tokens/new?name=${encodeURIComponent("StackVitals app")}` +
    `&description=${encodeURIComponent(`Lets the StackVitals app start its workflow in ${app.repo}`)}&target_name=${encodeURIComponent(owner)}` +
    "&expires_in=30&actions=write";
}
