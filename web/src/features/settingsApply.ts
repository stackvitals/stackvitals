// Saving settings with a GitHub token: a commit to .github/stackvitals.toml (a pull request when the branch is protected,
// as core/requests.py does it), a run of the workflow with the request, or an edit of the workflow's inputs.
import { makeApi, toBase64, fromBase64, encPath, explain, sleep, type Api, type Res } from "../github/client";
import { repoPath, wfPath } from "../github/names";
import { writeToken } from "../github/session";
import { accountToken } from "../github/token";
import { token as tabToken, type Req } from "../data/write";
import type { AppJson } from "../data/types";
import type { Run } from "./settingsPending";
import { workflowValues } from "./settingsToml";

export const SETTINGS_FILE = ".github/stackvitals.toml";
export const tokenNow = (): string | null => accountToken() || tabToken();
// The signed-in token is renewed first when it is about to end.
const api = async (app: AppJson): Promise<Api> => makeApi((await writeToken(app)) || tabToken());

export interface Outcome { kind: "committed" | "pr" | "compare" | "same"; url?: string }

async function who(a: Api): Promise<string> {
  try { return (await a.get<{ login: string }>("/user"))?.login || "the app"; } catch { return "the app"; }
}

const msgOf = (r: Res) => (typeof r.data === "object" && r.data?.message ? String(r.data.message) : "");
// Branch protection or a ruleset: GitHub says so in the message (403, 422, or 409 for rule violations).
export const isProtected = (r: Res) => [403, 409, 422].includes(r.status) && /protect|rule|pull request/i.test(msgOf(r));

// One file changed by `edit`: committed on the default branch, else on a new branch with a pull request (or a link to open one).
export async function commitFile(app: AppJson, path: string, edit: (text: string) => string, what: string, given?: Api): Promise<Outcome> {
  const repo = repoPath(app.repo);
  const a = given || await api(app);
  const info = await a.get<{ default_branch: string }>(`/repos/${repo}`);
  if (!info) throw new Error(`the token can't see ${app.repo}.`);
  const branch = info.default_branch || app.default_branch || "main";
  const file = `/repos/${repo}/contents/${encPath(path)}`;
  const read = async (ref: string) => {
    const got = await a.get<{ sha: string; content: string }>(`${file}?ref=${encodeURIComponent(ref)}`);
    return { sha: got?.sha, text: got ? fromBase64(got.content || "") : "" };
  };
  const by = await who(a);
  const message = `chore(stackvitals): Update ${what} (asked from the StackVitals app by ${by})`;
  // A 409 that isn't protection means the file changed since it was read: read again, apply again, once.
  for (let attempt = 0; ; attempt++) {
    const got = await read(branch);
    const next = edit(got.text);
    if (next === got.text) return { kind: "same" };
    const put = await a.call<{ commit?: { html_url?: string } }>("PUT", file, { message, content: toBase64(next), branch, ...(got.sha ? { sha: got.sha } : {}) });
    if (put.ok) return { kind: "committed", url: put.data?.commit?.html_url };
    if (isProtected(put)) break;
    if (put.status === 409 && attempt === 0) continue;
    if (put.status === 409) throw new Error(`${path} changed on GitHub while saving; try again.`);
    throw explain(put, true);
  }
  // Protected branch: the same change on its own branch, then a pull request.
  const head = `stackvitals/settings-${new Date().toISOString().replace(/\D/g, "").slice(0, 14)}`;
  const base = await a.get<{ object: { sha: string } }>(`/repos/${repo}/git/ref/heads/${encPath(branch)}`);
  if (!base) throw new Error(`the branch ${branch} wasn't found.`);
  const made = await a.call("POST", `/repos/${repo}/git/refs`, { ref: `refs/heads/${head}`, sha: base.object.sha });
  if (!made.ok) throw explain(made, true);
  const there = await read(head);
  const onHead = await a.call("PUT", file, { message, content: toBase64(edit(there.text)), branch: head, ...(there.sha ? { sha: there.sha } : {}) });
  if (!onHead.ok) throw explain(onHead, true);
  const pr = await a.call<{ html_url: string }>("POST", `/repos/${repo}/pulls`, { title: `Update StackVitals ${what} (asked from the StackVitals app)`, head, base: branch,
    body: `A ${what} change asked from the StackVitals app by ${by}.` });
  if (pr.ok) return { kind: "pr", url: pr.data.html_url };
  return { kind: "compare", url: `https://github.com/${repo}/compare/${encodeURIComponent(branch)}...${encodeURIComponent(head)}?quick_pull=1` };
}

// The workflow started with the request (logged like an issue request); resolves with the run once GitHub lists it.
export async function dispatchRequest(app: AppJson, req: Req): Promise<Run | null> {
  if (!app.links?.workflow) throw new Error("this page doesn't know the workflow's file name yet; use the GitHub issue instead.");
  const repo = repoPath(app.repo), wf = wfPath(app.links.workflow);
  const a = await api(app);
  const list = async () => ((await a.get<{ workflow_runs?: Run[] }>(`/repos/${repo}/actions/workflows/${wf}/runs?event=workflow_dispatch&per_page=5`))?.workflow_runs || []);
  const before = Math.max(0, ...(await list()).map((r) => r.id));
  const r = await a.call("POST", `/repos/${repo}/actions/workflows/${wf}/dispatches`, { ref: app.default_branch || "main", inputs: { request: JSON.stringify(req) } });
  if (!r.ok) throw r.status === 422 ? new Error("this repo's StackVitals workflow is older and takes no request; update it, or use the GitHub issue.") : explain(r, true);
  for (let i = 0; i < 10; i++) {
    await sleep(2000);
    const run = (await list()).filter((x) => x.id > before).sort((x, y) => x.id - y.id)[0];
    if (run) return run;
  }
  return null;
}

export const runStatus = async (app: AppJson, id: number) => (await api(app)).get<Run>(`/repos/${repoPath(app.repo)}/actions/runs/${encodeURIComponent(id)}`);

// The workflow file as it is on the default branch: through the token when there is one, else the public raw file.
export async function workflowText(app: AppJson): Promise<string | null> {
  const branch = app.default_branch || "main";
  try {
    if (!app.links?.workflow) return null;
    const repo = repoPath(app.repo), path = `.github/workflows/${wfPath(app.links.workflow)}`;
    if (tokenNow()) {
      const got = await (await api(app)).get<{ content: string }>(`/repos/${repo}/contents/${path}?ref=${encodeURIComponent(branch)}`);
      return got ? fromBase64(got.content) : null;
    }
    if (app.visibility === "private") return null;
    const r = await fetch(`https://raw.githubusercontent.com/${repo}/${encodeURIComponent(branch)}/${path}`, { cache: "no-cache" });
    return r.ok ? await r.text() : null;
  } catch { return null; }
}

// The inputs the workflow's StackVitals step sets now, or null when the file can't be read.
export async function workflowNow(app: AppJson): Promise<Record<string, string> | null> {
  const text = await workflowText(app);
  return text === null ? null : workflowValues(text);
}
