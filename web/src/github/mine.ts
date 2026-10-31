// The connected account's repos and, checked lazily and cached for this tab, whether each already runs StackVitals.
import { paged, type Api } from "./client";
import { FILE } from "./workflow";

export interface GhRepo { full_name: string; owner: string; name: string; private: boolean; default_branch: string; pushed_at: string | null; archived: boolean; description: string | null }

export async function myRepos(api: Api, maxPages = 5): Promise<GhRepo[]> {
  const raw = await paged<any>(api, "/user/repos?sort=pushed", maxPages);
  return raw.map((r) => ({ full_name: r.full_name, owner: r.owner?.login || r.full_name.split("/")[0], name: r.name, private: !!r.private,
    default_branch: r.default_branch || "main", pushed_at: r.pushed_at || null, archived: !!r.archived, description: r.description || null }));
}

// Grouped by owner (the signed-in account first), filtered by a search.
export function groupRepos(list: GhRepo[], query: string, me?: string): [string, GhRepo[]][] {
  const q = query.trim().toLowerCase();
  const groups = new Map<string, GhRepo[]>();
  for (const r of list) {
    if (q && !r.full_name.toLowerCase().includes(q)) continue;
    if (!groups.has(r.owner)) groups.set(r.owner, []);
    groups.get(r.owner)!.push(r);
  }
  return [...groups.entries()].sort(([a], [b]) => (a === me ? -1 : b === me ? 1 : a.localeCompare(b)));
}

export type SetupState = "data" | "workflow" | "none";
const KEY = "sv:setupcheck";
const TTL = 10 * 60000;
const memo = new Map<string, Promise<SetupState>>();

function cached(): Record<string, [SetupState, number]> {
  try { return JSON.parse(sessionStorage.getItem(KEY) || "{}"); } catch { return {}; }
}
export function remember(repo: string, s: SetupState): void {
  try { const all = cached(); all[repo] = [s, Date.now()]; sessionStorage.setItem(KEY, JSON.stringify(all)); } catch { /* memory only */ }
}

// The data branch means set up; the workflow file alone means installed and waiting for its first run.
export function setupState(api: Api, repo: string): Promise<SetupState> {
  const hit = cached()[repo];
  if (hit && Date.now() - hit[1] < TTL) return Promise.resolve(hit[0]);
  if (!memo.has(repo)) {
    const p = (async (): Promise<SetupState> => {
      const branch = await api.call("GET", `/repos/${repo}/branches/stackvitals-data`);
      const s: SetupState = branch.ok ? "data"
        : (await api.call("GET", `/repos/${repo}/contents/${FILE}`)).ok ? "workflow" : "none";
      remember(repo, s);
      return s;
    })();
    p.catch(() => memo.delete(repo));
    memo.set(repo, p);
  }
  return memo.get(repo)!;
}

// At most a few checks at once, so a long list never bursts the API.
export function limiter(n: number) {
  let active = 0;
  const queue: (() => void)[] = [];
  return async <T>(job: () => Promise<T>): Promise<T> => {
    if (active >= n) await new Promise<void>((r) => queue.push(r));
    active++;
    try { return await job(); } finally { active--; queue.shift()?.(); }
  };
}
