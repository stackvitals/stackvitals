// What a repo has, so setup can suggest a plan: CI workflows, deployments or releases, lockfiles, visibility, and what's installed.
import { fromBase64, type Api } from "./client";
import { repoPath } from "./names";
import { pagesFrom } from "./setup";
import { FILE, ciGuess, type Module } from "./workflow";

export interface Detected {
  repo: string; private: boolean; branch: string; hasPages: boolean; canPush: boolean | null;
  workflows: string[]; off: string[]; ciNames: string[]; installed: boolean; dataBranch: boolean;
  deployments: boolean; releases: boolean; lockfiles: string[];
  // pages: what an existing Pages site serves (null: none, or unreadable); existing: the StackVitals file there now.
  pages: { ours: boolean; says: string } | null; existing: string | null;
}

const LOCKS = /^(package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?|poetry\.lock|uv\.lock|Pipfile\.lock|pdm\.lock|requirements[\w.-]*\.txt|pylock[\w.-]*\.toml|Cargo\.lock|go\.mod|go\.sum|Gemfile\.lock|gems\.locked|composer\.lock|pom\.xml|gradle\.lockfile|Package\.resolved|mix\.lock|pubspec\.lock|packages\.lock\.json)$/;

// Six reads (fewer when the repo isn't found): fine on the 60-an-hour limit too.
export async function detect(api: Api, name: string): Promise<Detected | null> {
  const repo = repoPath(name);
  const info = await api.get<any>(`/repos/${repo}`);
  if (!info) return null;
  const branch = info.default_branch || "main";
  const [flows, deps, rels, root, data] = await Promise.all([
    api.get<any>(`/repos/${repo}/actions/workflows?per_page=100`).catch(() => null),
    api.get<any[]>(`/repos/${repo}/deployments?per_page=1`).catch(() => null),
    api.get<any[]>(`/repos/${repo}/releases?per_page=1`).catch(() => null),
    api.get<any[]>(`/repos/${repo}/contents/?ref=${encodeURIComponent(branch)}`).catch(() => null),
    api.call("GET", `/repos/${repo}/branches/stackvitals-data`).then((r) => r.ok, () => false),
  ]);
  const all: any[] = flows?.workflows || [];
  const installed = all.some((w) => w.path === FILE);
  // Two more reads only when there is something to read: the Pages site's source and the StackVitals file.
  const [site, file] = await Promise.all([
    info.has_pages ? api.get<any>(`/repos/${repo}/pages`).catch(() => null) : null,
    installed ? api.get<any>(`/repos/${repo}/contents/${FILE}?ref=${encodeURIComponent(branch)}`).catch(() => null) : null,
  ]);
  const own = all.filter((w) => w.path !== FILE && !String(w.path).startsWith("dynamic/"));
  const workflows = own.filter((w) => w.state === "active").map((w) => String(w.name));
  // Workflows someone turned off never finish a run, so StackVitals can't read them until they're back on.
  const off = own.filter((w) => w.state !== "active").map((w) => String(w.name));
  return {
    repo: info.full_name || name, private: !!info.private, branch, hasPages: !!info.has_pages,
    canPush: info.permissions ? !!(info.permissions.push || info.permissions.admin) : null,
    workflows, off, ciNames: ciGuess(workflows), installed, dataBranch: !!data,
    deployments: !!deps?.length, releases: !!rels?.length,
    pages: info.has_pages ? (site ? pagesFrom(site) : { ours: false, says: "another source" }) : null,
    existing: file?.content ? fromBase64(file.content) : null,
    lockfiles: Array.isArray(root) ? root.filter((f) => f.type === "file" && LOCKS.test(f.name)).map((f) => String(f.name)) : [],
  };
}

export type PagesMode = "public" | "artifact" | "local";
export interface Plan {
  modules: Module[]; names: string[]; days: number; budget: number; pages: PagesMode; everyCiRun: boolean;
  // Asked for explicitly: point an existing Pages site at the dashboard; commit over a different workflow file.
  pagesSwitch: boolean; replace: boolean;
}

// ci and flow always; deps when there are lockfiles; community when the repo is public. Private repos are viewed in the app.
export function suggest(d: Detected): Plan {
  const modules: Module[] = ["ci", "flow"];
  if (d.lockfiles.length) modules.push("deps");
  if (!d.private) modules.push("community");
  return { modules, names: d.ciNames, days: 90, budget: 800, pages: d.private ? "local" : "public", everyCiRun: false, pagesSwitch: false, replace: false };
}
