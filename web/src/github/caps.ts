// What a pasted token is and what it can do: the account, the repos it reaches, and each permission setup needs.
import { explain, type Api } from "./client";
import type { Account } from "./token";

export const TOKEN_RE = /\b(github_pat_[A-Za-z0-9_]{22,255}|gh[pousr]_[A-Za-z0-9]{30,255})\b/;

export function kindOf(token: string): Account["kind"] {
  return token.startsWith("github_pat_") ? "fine" : token.startsWith("ghp_") ? "classic" : token.startsWith("ghu_") ? "app" : "oauth";
}

// The permissions setup and Connections use, in plain words.
export const PERMS = [
  { id: "contents", says: "Read the code and add the workflow file" },
  { id: "workflows", says: "Change files in .github/workflows" },
  { id: "actions", says: "Start the first run and watch it" },
  { id: "pull_requests", says: "Open a pull request when the branch is protected" },
  { id: "variables", says: "Set the every-CI-run switch" },
  { id: "secrets", says: "Save keys for Connections" },
  { id: "pages", says: "Turn on the web page" },
  { id: "administration", says: "Read the repo's Actions settings" },
] as const;
export type PermId = (typeof PERMS)[number]["id"];

export function tokenPageUrl(): string {
  const q = new URLSearchParams({ name: "StackVitals", description: "Lets the StackVitals app set up and run StackVitals in the repos you pick", expires_in: "90" });
  for (const p of PERMS) q.set(p.id, "write");
  return `https://github.com/settings/personal-access-tokens/new?${q}`;
}

export interface Check { id: PermId; says: string; ok: boolean | null }
export interface Inspection {
  login: string; avatar: string; name: string | null; kind: Account["kind"];
  repos: number | null; probe: string | null; checks: Check[]; missing: Check[];
}

// Read-only probes on one repo the token reaches: 403 means the permission is missing; 2xx or 404 means it's there.
const PROBES: Partial<Record<PermId, (r: string) => string>> = {
  contents: (r) => `/repos/${r}/contents/`,
  actions: (r) => `/repos/${r}/actions/workflows?per_page=1`,
  pull_requests: (r) => `/repos/${r}/pulls?per_page=1`,
  variables: (r) => `/repos/${r}/actions/variables?per_page=1`,
  secrets: (r) => `/repos/${r}/actions/secrets/public-key`,
  pages: (r) => `/repos/${r}/pages`,
  administration: (r) => `/repos/${r}/actions/permissions`,
};

export async function inspect(api: Api, token: string): Promise<Inspection> {
  const me = await api.call("GET", "/user");
  if (!me.ok) throw explain(me, true);
  const kind = kindOf(token);
  const base = { login: me.data.login as string, avatar: me.data.avatar_url as string, name: (me.data.name as string) || null, kind };
  if (kind === "classic" || kind === "oauth") {
    // Classic tokens say their scopes in a header: repo and workflow are what setup needs.
    const scopes = (me.headers.get("x-oauth-scopes") || "").split(",").map((s) => s.trim());
    const has = (s: string) => scopes.includes(s);
    const checks: Check[] = PERMS.map((p) => ({ id: p.id, says: p.says, ok: p.id === "workflows" ? has("workflow") : has("repo") }));
    return { ...base, repos: null, probe: null, checks, missing: checks.filter((c) => c.ok === false) };
  }
  const list = await api.call<any[]>("GET", "/user/repos?per_page=100&sort=pushed");
  if (!list.ok) throw explain(list, true);
  const repos = list.data || [];
  // A private repo tells more: public ones answer reads for anyone.
  const probe = (repos.find((r) => r.private) || repos[0])?.full_name || null;
  const checks: Check[] = await Promise.all(PERMS.map(async (p): Promise<Check> => {
    const path = probe && PROBES[p.id]?.(probe);
    if (!path) return { id: p.id, says: p.says, ok: null };
    const r = await api.call("GET", path);
    return { id: p.id, says: p.says, ok: r.status === 403 ? false : r.ok || r.status === 404 ? true : null };
  }));
  return { ...base, repos: repos.length, probe, checks, missing: checks.filter((c) => c.ok === false) };
}
