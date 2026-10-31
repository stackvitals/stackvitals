// Opening a repo from the Welcome screen, the picker or setup: its Pages site or data branch, added to the repo list.
import { json, refresh } from "../data/files";
import { entryFor, openRepo, type RepoEntry } from "../data/repos";
import type { Source } from "../data/source";
import { prefs } from "../data/store";
import type { AppJson } from "../data/types";
import { navigate } from "../app/router";
import { makeApi, type Fetch } from "./client";
import { siteUrl } from "./setup";
import { account, welcome } from "./token";

export function parseRepo(text: string): string | null {
  const m = text.trim().replace(/^https?:\/\/github\.com\//i, "").replace(/\.git$|\/$/g, "").match(/^([A-Za-z0-9-]+)\/([A-Za-z0-9._-]+)$/);
  return m ? `${m[1]}/${m[2]}` : null;
}

// Published data for a repo: its Pages site first (no API cost), then its stackvitals-data branch.
export async function findPublished(repo: string, token?: string): Promise<{ source: Source; app: AppJson } | null> {
  const [owner = "", name = ""] = repo.split("/");
  const tries: Source[] = token ? [{ kind: "branch", owner, repo: name, token }]
    : [{ kind: "pages", url: siteUrl(repo) }, { kind: "branch", owner, repo: name }];
  for (const source of tries) {
    const app = await json<AppJson>("app.json", source);
    if (app && app.repo) return { source, app };
  }
  return null;
}

export type Lookup = { kind: "data"; source: Source; app: AppJson } | { kind: "none"; private: boolean } | { kind: "missing" };

// What typing owner/repo leads to: its dashboard, its setup, or "not found (or private)".
export async function lookup(repo: string, fetchImpl?: Fetch): Promise<Lookup> {
  const tok = account.get()?.token;
  // One API call first, so a repo that doesn't exist fails fast; if GitHub can't answer (limit), the files are tried anyway.
  const info = await makeApi(tok, fetchImpl).get<any>(`/repos/${repo}`).catch(() => undefined);
  if (info === null) return { kind: "missing" };
  const found = await findPublished(repo);
  if (found) return { kind: "data", ...found };
  if (tok) {
    const mine = await findPublished(repo, tok);
    if (mine) return { kind: "data", ...mine };
  }
  return info ? { kind: "none", private: !!info.private } : { kind: "missing" };
}

function leaveWelcome(): void {
  welcome.set(false);
  const q = new URLSearchParams(location.search);
  if (q.has("welcome")) { q.delete("welcome"); history.replaceState(null, "", location.pathname + (q.toString() ? "?" + q : "") + location.hash); }
}

export function openEntry(e: RepoEntry, hash = "#/"): void {
  refresh();
  openRepo(e);
  prefs.set("last", e.id);
  leaveWelcome();
  navigate(hash);
}

// A repo by name through its data branch; private ones read with the connected token.
export function openByName(repo: string, isPrivate: boolean, hash = "#/"): void {
  const [owner = "", name = ""] = repo.split("/");
  const tok = isPrivate ? account.get()?.token : undefined;
  const e: RepoEntry = { ...entryFor({ kind: "branch", owner, repo: name, ...(tok ? { token: tok } : {}) }, repo), ...(isPrivate ? { private: true } : {}) };
  openEntry(e, hash);
}

export const openSetup = (repo: string, isPrivate: boolean) => openByName(repo, isPrivate, `#/setup?repo=${encodeURIComponent(repo)}`);
