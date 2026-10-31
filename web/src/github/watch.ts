// Watching a setup without a token (GitHub's open API, 60 requests an hour per visitor): each check asks only about the
// first step still to do, about once every 75 seconds, for at most 15 minutes (the old wizard's pacing).
import type { Api } from "./client";
import { FILE } from "./workflow";

export const POLL_MS = 75000;
export const POLL_FOR_MS = 15 * 60000;

export interface Watched {
  exists: boolean; public?: boolean; branch?: string; installed?: boolean;
  run?: { id: number; html_url: string; status: string; conclusion: string | null; run_number: number } | null;
  dataBranch?: boolean; site?: boolean;
}

export async function check(api: Api, repo: string, prev: Watched | null = null): Promise<Watched> {
  const out: Watched = { ...(prev?.exists ? prev : { exists: false }) };
  let fresh: any = null;
  if (!out.exists) {
    fresh = await api.get(`/repos/${repo}`);
    if (!fresh) return { exists: false };
    Object.assign(out, { exists: true, public: !fresh.private, branch: fresh.default_branch || "main" });
  }
  if (!out.installed) {
    const flows: any[] = (await api.get(`/repos/${repo}/actions/workflows?per_page=100`))?.workflows || [];
    out.installed = flows.some((w) => w.path === FILE);
    if (!out.installed) return out;
  }
  if (!out.dataBranch) {
    out.run = (await api.get(`/repos/${repo}/actions/workflows/stackvitals.yml/runs?per_page=1`))?.workflow_runs?.[0] || null;
    // The first run writes the data branch; until one finishes there is nothing to look for.
    out.dataBranch = out.run?.status === "completed" && !!(await api.get(`/repos/${repo}/branches/stackvitals-data`));
    if (!out.dataBranch) return out;
  }
  if (!out.site) out.site = !!(fresh || (await api.get(`/repos/${repo}`)))?.has_pages;
  return out;
}

export function watchSteps(w: Watched | null): { title: string; state: "done" | "now" | "later" }[] {
  const done = [!!w?.installed, !!w?.run, !!w?.dataBranch, !!w?.site];
  const now = done.indexOf(false);
  return ["Workflow file committed", "First run started", "Data branch written", "Web page on"].map((title, i) => ({
    title, state: done[i] ? "done" : i === now ? "now" : "later" }));
}
