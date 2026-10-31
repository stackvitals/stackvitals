// The repos this viewer follows and the one open now. The list lives in localStorage; tokens only in this tab.
import { prefs, store } from "./store";
import { sourceKey, type Source } from "./source";

import { isRepo } from "../github/names";
import { accountToken } from "../github/token";

// private: read with the connected GitHub account's token when this tab has no token of its own for it.
export interface RepoEntry { id: string; label: string; source: Source; demo?: boolean; private?: boolean }

const HERE: RepoEntry = { id: "here", label: "This site", source: { kind: "here" } };
export const DEMO: RepoEntry[] = [
  { id: "demo:payments-api", label: "acme/payments-api", source: { kind: "pages", url: "app/demo/payments-api/" }, demo: true },
  { id: "demo:web-app", label: "acme/web-app", source: { kind: "pages", url: "app/demo/web-app/" }, demo: true },
  { id: "demo:mobile", label: "acme/mobile", source: { kind: "pages", url: "app/demo/mobile/" }, demo: true },
];

function tokens(): Record<string, string> {
  try { return JSON.parse(sessionStorage.getItem("sv:tokens") || "{}") as Record<string, string>; } catch { return {}; }
}
function saveToken(key: string, token: string | undefined): void {
  try {
    const all = tokens();
    if (token) all[key] = token; else delete all[key];
    sessionStorage.setItem("sv:tokens", JSON.stringify(all));
  } catch { /* storage refused: the token lives in memory only */ }
}

// Stored entries never carry a token; it is put back from this tab's session.
function withToken(e: RepoEntry): RepoEntry {
  if (e.source.kind !== "branch") return e;
  const t = tokens()[e.id] || (e.private ? accountToken() : undefined);
  return t ? { ...e, source: { ...e.source, token: t } } : e;
}
function strip(e: RepoEntry): RepoEntry {
  if (e.source.kind !== "branch" || !e.source.token) return e;
  const { token: _t, ...rest } = e.source;
  return { ...e, source: rest };
}

// A saved or linked source is used only when its names are plain: owner/name for a branch, an http(s) or relative address for Pages.
function sane(s: Source | undefined): boolean {
  if (!s) return false;
  if (s.kind === "branch") return isRepo(`${s.owner}/${s.repo}`);
  if (s.kind === "pages") return typeof s.url === "string" && safeUrl(s.url);
  return s.kind === "here";
}
function safeUrl(u: string): boolean {
  try { return ["https:", "http:"].includes(new URL(u, location.href).protocol); } catch { return false; }
}

export function entryFor(source: Source, label?: string): RepoEntry {
  const id = sourceKey(source);
  const name = label || (source.kind === "branch" ? `${source.owner}/${source.repo}` : source.kind === "pages" ? source.url.replace(/^https?:\/\//, "").replace(/\/$/, "") : HERE.label);
  return { id, label: name, source };
}

const params = new URLSearchParams(location.search);
export const demoMode = params.get("demo") === "1";

function initial(): { list: RepoEntry[]; current: RepoEntry } {
  if (demoMode) {
    // A link names the demo repo; otherwise the one picked last time.
    const pick = DEMO.find((d) => d.id === `demo:${params.get("repo")}`) || DEMO.find((d) => d.id === prefs.get<string>("demoCurrent", "")) || DEMO[0]!;
    return { list: DEMO, current: pick };
  }
  const saved = prefs.get<RepoEntry[]>("repos", []).filter((e) => e && sane(e.source) && e.id !== "here").map(withToken);
  const list = [HERE, ...saved];
  let current = list.find((e) => e.id === prefs.get<string>("current", "here")) || HERE;
  // A link can open a repo directly: ?repo=owner/name (data branch) or ?pages=<site address>.
  const repo = params.get("repo"), pages = params.get("pages");
  const linked = repo && isRepo(repo) ? entryFor({ kind: "branch", owner: repo.split("/")[0]!, repo: repo.split("/")[1]! })
    : pages && safeUrl(pages) ? entryFor({ kind: "pages", url: pages.endsWith("/") ? pages : pages + "/" }) : null;
  if (linked) {
    const known = list.find((e) => e.id === linked.id);
    if (!known) list.push(linked);
    current = known || linked;
  }
  return { list, current };
}

const start = initial();
export const repos = store<RepoEntry[]>(start.list);
export const current = store<RepoEntry>(start.current);

function persist(): void {
  if (demoMode) { prefs.set("demoCurrent", current.get().id); return; }
  prefs.set("repos", repos.get().filter((e) => e.id !== "here" && !e.demo).map(strip));
  prefs.set("current", current.get().id);
}

export function openRepo(e: RepoEntry): void {
  if (!repos.get().some((r) => r.id === e.id)) repos.set((l) => [...l, e]);
  if (e.source.kind === "branch") saveToken(e.id, e.source.token);
  current.set(e);
  persist();
}

export function forgetRepo(id: string): void {
  if (id === "here") return;
  saveToken(id, undefined);
  repos.set((l) => l.filter((e) => e.id !== id));
  if (current.get().id === id) current.set(repos.get()[0] || HERE);
  persist();
}

// The label comes from app.json once it has loaded ("owner/repo").
export function nameRepo(id: string, label: string): void {
  const l = repos.get();
  const i = l.findIndex((e) => e.id === id);
  if (i < 0 || l[i]!.label === label) return;
  const next = l.slice();
  next[i] = { ...l[i]!, label };
  repos.set(next);
  if (current.get().id === id) current.set(next[i]!);
  persist();
}
