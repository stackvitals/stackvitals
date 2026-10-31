// One-click setup as a resumable list of steps: commit the workflow (or a PR), set the variable, start and watch the first run,
// wait for the data branch, turn on Pages. State is saved after every change, so a reload picks up where it stopped.
import { explain, fromBase64, sleep as realSleep, toBase64, type Api, type Res } from "./client";
import { isRepo, repoPath } from "./names";
import { FILE } from "./workflow";

export type StepId = "commit" | "variable" | "run" | "data" | "pages";
export type Status = "pending" | "running" | "done" | "failed" | "skipped" | "waiting";
export interface Step { id: StepId; status: Status; note?: string; fix?: string; link?: string; fixLink?: string }
export interface Job { name: string; status: string; conclusion: string | null; steps: { name: string; status: string; conclusion: string | null }[] }

// replace: commit straight over a different workflow file (asked for explicitly); else such a file changes through a pull request.
// pagesSwitch: point a Pages site that serves something else at the dashboard (asked for explicitly); else it is kept.
export interface Target {
  repo: string; branch: string; private: boolean; yaml: string; everyCiRun: boolean; pages: "public" | "artifact" | "local";
  replace?: boolean; pagesSwitch?: boolean;
}
export interface SetupRun {
  target: Target; steps: Step[]; started: number; pr?: { number: number; url: string }; runId?: number; runUrl?: string;
  jobs?: Job[]; siteUrl?: string; finished?: boolean; reenabled?: boolean; headSha?: string;
}

export const TITLES: Record<StepId, string> = {
  commit: "Add the workflow file", variable: "Read every CI run", run: "First run", data: "Data branch written", pages: "Turn on the web page",
};
export const DATA_BRANCH = "stackvitals-data";
export const SETUP_BRANCH = "stackvitals-setup";

export function newRun(target: Target, now = Date.now()): SetupRun {
  const steps: Step[] = (["commit", "variable", "run", "data", "pages"] as StepId[]).map((id) => ({ id, status: "pending" }));
  return { target, steps, started: now };
}

export interface Deps {
  api: Api; save?: (r: SetupRun) => void; sleep?: (ms: number) => Promise<void>; now?: () => number;
  tokenPage?: string; pollMs?: number; maxPollMin?: number;
}

export function siteUrl(repo: string): string {
  const [owner = "", name = ""] = repo.split("/");
  return name.toLowerCase() === `${owner.toLowerCase()}.github.io` ? `https://${owner.toLowerCase()}.github.io/` : `https://${owner.toLowerCase()}.github.io/${name}/`;
}

// What a Pages site is built from, in words; ours is the data branch's /docs folder.
export function pagesFrom(p: any): { ours: boolean; says: string } {
  if (p?.build_type === "workflow") return { ours: false, says: "a GitHub Actions workflow" };
  const b = p?.source?.branch, path = p?.source?.path || "/";
  return { ours: b === DATA_BRANCH && path === "/docs", says: b ? `the ${b} branch (${path})` : "another source" };
}

const msgOf = (r: Res) => (typeof r.data === "object" && r.data?.message ? String(r.data.message) : "");
// Branch protection or a ruleset: GitHub says so in the message (403, 422, or 409 for rule violations).
const protectedBranch = (r: Res) => [403, 409, 422].includes(r.status) && /protect|rule|pull request/i.test(msgOf(r));

class Stop extends Error {}

// Runs (or resumes) every step not yet done; `emit` gets a fresh copy after each change. Returns the final state.
export async function runSetup(start: SetupRun, emit: (r: SetupRun) => void, deps: Deps): Promise<SetupRun> {
  const { api } = deps;
  const sleep = deps.sleep || realSleep, now = deps.now || Date.now;
  const t = start.target, name = t.repo;
  let run: SetupRun = JSON.parse(JSON.stringify(start));
  const put = (patch: Partial<SetupRun>) => { run = { ...run, ...patch }; deps.save?.(run); emit(run); };
  // A workflow that was turned off and turned back on is said in every note of the run step.
  const told = (id: StepId, s: Partial<Step>) => (id === "run" && run.reenabled && s.note ? { ...s, note: `${s.note} The workflow had been turned off, so it was turned back on.` } : s);
  const step = (id: StepId, s: Partial<Step>) => put({ steps: run.steps.map((x) => (x.id === id ? { id, status: s.status || x.status, ...pick(told(id, s)) } : x)) });
  const pick = (s: Partial<Step>) => Object.fromEntries(Object.entries(s).filter(([k, v]) => k !== "id" && k !== "status" && v !== undefined));
  const fail = (id: StepId, note: string, fix?: string, fixLink?: string): never => { step(id, { status: "failed", note, fix, fixLink }); throw new Stop(); };
  const tokenFix = (what: string) => `The token needs ${what} on ${name}. Make a new token with the button below and pick this repo.`;
  const state = (id: StepId) => run.steps.find((x) => x.id === id)!.status;
  // Nothing is sent for a name that isn't plainly owner/name.
  if (!isRepo(name)) { step("commit", { status: "failed", note: `"${String(t.repo).slice(0, 80)}" isn't a repo name (owner/name); nothing was written.` }); return run; }
  const repo = repoPath(name), branchQ = encodeURIComponent(t.branch);

  try {
    // 1. The workflow file on the default branch; a pull request when the branch is protected or a different file is there.
    if (state("commit") !== "done") {
      step("commit", { status: "running", note: `Writing ${FILE} on ${t.branch} in ${name}` });
      for (let attempt = 0; ; attempt++) {
        const onDefault = await api.call("GET", `/repos/${repo}/contents/${FILE}?ref=${branchQ}`);
        const same = onDefault.ok && fromBase64(onDefault.data?.content || "") === t.yaml;
        if (same) {
          if (run.pr) await mergedHead(api, repo, branchQ).then((sha) => sha && put({ headSha: sha }));
          step("commit", { status: "done", note: run.pr ? `Pull request #${run.pr.number} is merged.` : "The workflow file is already there." });
          break;
        }
        if (run.pr && onDefault.ok) { step("commit", { status: "done", note: `Pull request #${run.pr.number} is merged.` }); break; }
        if (run.pr) {
          const pr = await api.call("GET", `/repos/${repo}/pulls/${run.pr.number}`);
          if (pr.ok && pr.data?.state === "closed" && !pr.data?.merged) { put({ pr: undefined }); return await runSetup(run, emit, deps); }
          step("commit", { status: "waiting", note: `Pull request #${run.pr.number} is open: merge it, then press Continue.`, link: run.pr.url });
          return run;
        }
        // A different StackVitals file is there: it changes only through a pull request unless a direct commit was confirmed.
        if (onDefault.ok && !t.replace) {
          const pr = await openPr(api, t, true);
          put({ pr });
          step("commit", { status: "waiting", note: `${FILE} is already there and differs, so pull request #${pr.number} has the new one: review and merge it, then press Continue.`, link: pr.url });
          return run;
        }
        const body = { message: onDefault.ok ? "Update the StackVitals workflow" : "Add the StackVitals workflow", content: toBase64(t.yaml), branch: t.branch,
          ...(onDefault.ok ? { sha: onDefault.data.sha } : {}) };
        const r = await api.call("PUT", `/repos/${repo}/contents/${FILE}`, body);
        if (r.ok) {
          put({ started: now(), ...(r.data?.commit?.sha ? { headSha: String(r.data.commit.sha) } : {}) });
          step("commit", { status: "done", note: `Committed to ${t.branch} in ${name}.`, link: r.data?.commit?.html_url });
          break;
        }
        if (protectedBranch(r)) {
          const pr = await openPr(api, t, onDefault.ok);
          put({ pr });
          step("commit", { status: "waiting", note: `${t.branch} is protected, so a pull request has the file: merge #${pr.number}, then press Continue.`, link: pr.url });
          return run;
        }
        // 409 without a protection message: the file changed since it was read. Read it again, once.
        if (r.status === 409 && attempt === 0) continue;
        if (r.status === 409) fail("commit", `${FILE} changed on GitHub while setting up.`, "Press Continue to read it again.");
        if (r.status === 403 || r.status === 404) fail("commit", "GitHub refused to add the file.", tokenFix("Contents and Workflows: read and write"), deps.tokenPage);
        fail("commit", explain(r, true).message);
      }
    }

    // 2. The repo variable that makes private repos read every CI run (optional).
    if (!["done", "skipped", "failed"].includes(state("variable"))) {
      if (!t.everyCiRun) step("variable", { status: "skipped", note: t.private ? "Off: passing CI runs are read every 3 hours." : "Not needed for a public repo." });
      else {
        step("variable", { status: "running" });
        let r = await api.call("POST", `/repos/${repo}/actions/variables`, { name: "STACKVITALS_EVERY_CI_RUN", value: "true" });
        if (r.status === 409) r = await api.call("PATCH", `/repos/${repo}/actions/variables/STACKVITALS_EVERY_CI_RUN`, { name: "STACKVITALS_EVERY_CI_RUN", value: "true" });
        if (r.ok) step("variable", { status: "done", note: "STACKVITALS_EVERY_CI_RUN is true." });
        // Not worth stopping for: the rest still works.
        else step("variable", { status: "failed", note: "Couldn't set the variable.", fix: tokenFix("Variables: read and write"), fixLink: deps.tokenPage });
      }
    }

    // 3. The first run: the commit's own push run (matched by its commit), a run already going, else a dispatch.
    if (state("run") !== "done") {
      step("run", { status: "running", note: run.runId ? "Watching the run" : "Waiting for GitHub to start it" });
      const runs = `/repos/${repo}/actions/workflows/stackvitals.yml/runs`;
      if (!run.runId && !run.reenabled) {
        // A StackVitals workflow someone turned off can't run or be started: turn it back on first.
        const wf = await api.call("GET", `/repos/${repo}/actions/workflows/stackvitals.yml`);
        if (wf.ok && wf.data?.state && wf.data.state !== "active") {
          const on = await api.call("PUT", `/repos/${repo}/actions/workflows/stackvitals.yml/enable`);
          if (!on.ok) fail("run", "The StackVitals workflow is turned off and GitHub refused to turn it on.", tokenFix("Actions: read and write"), deps.tokenPage);
          put({ reenabled: true });
        }
      }
      if (!run.runId) {
        const sha = run.headSha;
        // GitHub can take half a minute to list a push run; a run of the new commit is ours whatever the clocks say.
        let found = sha ? await findRun(api, runs, (x) => x.head_sha === sha, 12, sleep) : null;
        // A run already queued or going (another tab, another device): watch it instead of starting a second one.
        if (!found) found = await findRun(api, runs, (x) => x.status === "queued" || x.status === "in_progress", 1, sleep);
        if (found) put({ runId: found.id, runUrl: found.html_url });
        else {
          const sent = await dispatch(api, repo, t.branch, sleep);
          if (sent === "refused") fail("run", "GitHub refused to start the workflow.", tokenFix("Actions: read and write"), deps.tokenPage);
          if (sent === "missing") fail("run", "GitHub hasn't registered the workflow yet.", "Wait a minute and press Continue. If it stays, open the Actions tab: the file may have a problem.");
          // GitHub's own clock from the dispatch answer, a little early; the browser's only when GitHub didn't say.
          const since = typeof sent === "number" ? sent - 5000 : now() - 60000;
          const later = await findRun(api, runs, (x) => x.event === "workflow_dispatch" && Date.parse(x.created_at) >= since, 12, sleep);
          if (!later) { step("run", { status: "waiting", note: "Started; GitHub hasn't listed the run yet. Press Continue in a moment." }); return run; }
          put({ runId: later.id, runUrl: later.html_url });
        }
      }
      step("run", { status: "running", note: "Running", link: run.runUrl });
      const until = now() + (deps.maxPollMin ?? 30) * 60000;
      for (;;) {
        const [r, j] = await Promise.all([api.call("GET", `/repos/${repo}/actions/runs/${run.runId}`), api.call("GET", `/repos/${repo}/actions/runs/${run.runId}/jobs?per_page=50`)]);
        if (!r.ok) fail("run", explain(r, true).message);
        if (j.ok) put({ jobs: (j.data?.jobs || []).map((x: any) => ({ name: x.name, status: x.status, conclusion: x.conclusion,
          steps: (x.steps || []).map((s: any) => ({ name: s.name, status: s.status, conclusion: s.conclusion })) })) });
        if (r.data.status === "completed") {
          if (r.data.conclusion === "success") { step("run", { status: "done", note: `Run #${r.data.run_number} finished.`, link: r.data.html_url }); break; }
          fail("run", `Run #${r.data.run_number} ended: ${r.data.conclusion}.`, "Open the run: its summary names what to fix (often a permission in the file). Fix it, then press Continue to run again.", r.data.html_url);
        }
        if (now() > until) { step("run", { status: "waiting", note: "Still running after 30 minutes. Press Continue to keep watching." }); return run; }
        step("run", { status: "running", note: r.data.status === "queued" ? "Queued: waiting for a runner" : "Running", link: r.data.html_url });
        await sleep(deps.pollMs ?? 5000);
      }
    }

    // 4. The data branch the run writes.
    if (state("data") !== "done") {
      step("data", { status: "running" });
      let ok = false;
      for (let i = 0; i < 4 && !ok; i++) {
        ok = (await api.call("GET", `/repos/${repo}/branches/${DATA_BRANCH}`)).ok;
        if (!ok) await sleep(3000);
      }
      if (!ok) fail("data", "The run finished but no stackvitals-data branch is there.", "Open the run's summary: it says why nothing was written.", run.runUrl);
      step("data", { status: "done", note: `${DATA_BRANCH} has the first data.` });
    }

    // 5. GitHub Pages from the data branch, for public repos that want it. A site serving something else is kept unless asked.
    if (!["done", "skipped"].includes(state("pages"))) {
      if (t.private || t.pages !== "public") {
        step("pages", { status: "skipped", note: t.pages === "artifact" ? "Artifact mode: each run uploads the app to download." : "Private: open it here in the app with your token." });
      } else {
        step("pages", { status: "running" });
        const source = { branch: DATA_BRANCH, path: "/docs" };
        const cur = await api.call("GET", `/repos/${repo}/pages`);
        const from = cur.ok ? pagesFrom(cur.data) : null;
        let r: Res = cur;
        if (from && !from.ours && !t.pagesSwitch) {
          step("pages", { status: "skipped", note: `Pages already serves ${from.says}: kept as it is. The dashboard opens here in the app.` });
        } else {
          if (cur.status === 404) r = await api.call("POST", `/repos/${repo}/pages`, { source });
          else if (from && !from.ours) r = await api.call("PUT", `/repos/${repo}/pages`, { build_type: "legacy", source });
          if (r.ok || r.status === 409) {
            const url = (r.data?.html_url as string) || (cur.data?.html_url as string) || siteUrl(name);
            put({ siteUrl: url });
            step("pages", { status: "done", note: from && !from.ours ? `Pages now serves the dashboard instead of ${from.says}.` : "GitHub publishes it within a minute or two.", link: url });
          } else if (r.status === 403 || r.status === 404) step("pages", { status: "failed", note: "Couldn't turn on Pages.", fix: tokenFix("Pages: read and write"), fixLink: deps.tokenPage });
          else step("pages", { status: "failed", note: explain(r, true).message, fix: "Turn it on in Settings, Pages: branch stackvitals-data, folder /docs.", fixLink: `https://github.com/${name}/settings/pages` });
        }
      }
    }
    put({ finished: true });
  } catch (e) {
    if (!(e instanceof Stop)) {
      const cur = run.steps.find((x) => x.status === "running")?.id || "commit";
      step(cur, { status: "failed", note: e instanceof Error ? e.message : String(e), fix: "Press Continue to try again." });
    }
  }
  return run;
}

// The default branch's head after a merged pull request: the commit whose push run is ours.
async function mergedHead(api: Api, repo: string, branchQ: string): Promise<string | undefined> {
  const r = await api.call("GET", `/repos/${repo}/git/ref/heads/${branchQ}`);
  return r.ok ? r.data?.object?.sha : undefined;
}

async function openPr(api: Api, t: Target, update: boolean): Promise<{ number: number; url: string }> {
  return filePr(api, { repo: t.repo, base: t.branch, branch: SETUP_BRANCH, file: FILE, content: t.yaml,
    message: update ? "Update the StackVitals workflow" : "Add the StackVitals workflow", title: update ? "Update StackVitals" : "Add StackVitals",
    body: update ? "Updates `.github/workflows/stackvitals.yml` from the StackVitals app. Review the changes; merging starts a run."
      : "Adds `.github/workflows/stackvitals.yml`, set up from the StackVitals app. Merging it starts the first run." });
}

export interface FilePr { repo: string; base: string; branch: string; file: string; content: string; message: string; title: string; body: string }

// One file on its own branch off `base`, and a pull request for it (the open one is reused); returns the pull request.
export async function filePr(api: Api, p: FilePr): Promise<{ number: number; url: string }> {
  const repo = repoPath(p.repo), owner = p.repo.split("/")[0];
  const open = await api.call<any[]>("GET", `/repos/${repo}/pulls?state=open&head=${encodeURIComponent(`${owner}:${p.branch}`)}`);
  const ref = await api.call("GET", `/repos/${repo}/git/ref/heads/${encodeURIComponent(p.base)}`);
  if (!ref.ok) throw explain(ref, true);
  const made = await api.call("POST", `/repos/${repo}/git/refs`, { ref: `refs/heads/${p.branch}`, sha: ref.data.object.sha });
  // The branch may be left from an earlier try; any other refusal stops here.
  if (!made.ok && !(made.status === 422 && /already exists/i.test(msgOf(made)))) throw explain(made, true);
  const there = await api.call("GET", `/repos/${repo}/contents/${p.file}?ref=${p.branch}`);
  if (!(there.ok && fromBase64(there.data?.content || "") === p.content)) {
    const put = await api.call("PUT", `/repos/${repo}/contents/${p.file}`, { message: p.message, content: toBase64(p.content), branch: p.branch,
      ...(there.ok ? { sha: there.data.sha } : {}) });
    if (!put.ok) throw explain(put, true);
  }
  if (open.ok && open.data?.length) return { number: open.data[0].number, url: open.data[0].html_url };
  const pr = await api.call("POST", `/repos/${repo}/pulls`, { title: p.title, head: p.branch, base: p.base, body: p.body });
  if (!pr.ok) throw explain(pr, true);
  return { number: pr.data.number, url: pr.data.html_url };
}

async function findRun(api: Api, path: string, match: (x: any) => boolean, tries: number, sleep: (ms: number) => Promise<void>): Promise<{ id: number; html_url: string } | null> {
  for (let i = 0; i < tries; i++) {
    const r = await api.call("GET", `${path}?per_page=10`);
    const runs: any[] = r.ok ? r.data?.workflow_runs || [] : [];
    const hit = runs.filter(match).sort((a, b) => a.id - b.id)[0];
    if (hit) return { id: hit.id, html_url: hit.html_url };
    if (i < tries - 1) await sleep(3000);
  }
  return null;
}

// GitHub needs a few seconds to register a new workflow; until then a dispatch answers 404 or 422.
// Sent: GitHub's clock at the dispatch (ms), or true when it gave no Date header.
async function dispatch(api: Api, repo: string, branch: string, sleep: (ms: number) => Promise<void>): Promise<number | true | "refused" | "missing"> {
  for (let i = 0; i < 6; i++) {
    const r = await api.call("POST", `/repos/${repo}/actions/workflows/stackvitals.yml/dispatches`, { ref: branch });
    if (r.ok) return Date.parse(r.headers.get("date") || "") || true;
    if (r.status === 403) return "refused";
    await sleep(2000 * (i + 1));
  }
  return "missing";
}

// Continue after a stop: failed and waiting steps go back to pending; a failed run is started afresh.
export function retry(r: SetupRun, now = Date.now()): SetupRun {
  const runFailed = r.steps.find((s) => s.id === "run")?.status === "failed";
  return { ...r, finished: false, ...(runFailed ? { runId: undefined, runUrl: undefined, jobs: undefined, headSha: undefined, started: now } : {}),
    steps: r.steps.map((s) => (s.status === "failed" || s.status === "waiting" ? { id: s.id, status: "pending" } : s)) };
}

// Saved per repo in this tab (names are case-insensitive on GitHub), so a reload resumes.
const key = (repo: string) => `sv:setup:${repo.toLowerCase()}`;
export function loadRun(repo: string): SetupRun | null {
  try { return JSON.parse(sessionStorage.getItem(key(repo)) || "null"); } catch { return null; }
}
export function saveRun(r: SetupRun): void {
  try { sessionStorage.setItem(key(r.target.repo), JSON.stringify(r)); } catch { /* memory only */ }
}
export function clearRun(repo: string): void {
  try { sessionStorage.removeItem(key(repo)); } catch { /* ignore */ }
}

// One tab at a time sets up a repo: a lock in this browser that lapses if the tab stops renewing it.
const LOCK_MS = 90000;
const lockKey = (repo: string) => `sv:setup-lock:${repo.toLowerCase()}`;
const local = (): Storage | null => { try { return localStorage; } catch { return null; } };
export function takeLock(repo: string, tab: string, now = Date.now(), s: Storage | null = local()): boolean {
  if (!s) return true;
  try {
    const cur = JSON.parse(s.getItem(lockKey(repo)) || "null") as { tab: string; until: number } | null;
    if (cur && cur.tab !== tab && cur.until > now) return false;
    s.setItem(lockKey(repo), JSON.stringify({ tab, until: now + LOCK_MS }));
  } catch { /* storage refused: no lock */ }
  return true;
}
export function releaseLock(repo: string, tab: string, s: Storage | null = local()): void {
  try { if (s && JSON.parse(s.getItem(lockKey(repo)) || "null")?.tab === tab) s.removeItem(lockKey(repo)); } catch { /* ignore */ }
}
