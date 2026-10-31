// Keeps a signed-in token fresh: renewed through the relay shortly before it ends (at start and before each write),
// saved with every repo that used it; when renewal fails the account is signed out with a plain message.
import type { AppJson } from "../data/types";
import { current, repos, type RepoEntry } from "../data/repos";
import { toast } from "../ui/bits";
import type { Fetch } from "./client";
import { authConfig, type AuthConfig } from "./config";
import { refreshIfDue } from "./oauth";
import { onSignOut } from "./signout";
import { account, saveAccount, signOut, type Account } from "./token";

// Every entry reading with `from` reads with `to` instead (a renewed token), or with none (sign-out). Kept off the first screen.
export function retoken(from: string | null, to: string | undefined): void {
  const swap = (e: RepoEntry): RepoEntry => {
    if (e.source.kind !== "branch" || !e.source.token || (from !== null && e.source.token !== from)) return e;
    const { token: _t, ...rest } = e.source;
    return { ...e, source: to ? { ...rest, token: to } : rest };
  };
  repos.set((l) => l.map(swap));
  current.set(swap(current.get()));
  try {
    const all = JSON.parse(sessionStorage.getItem("sv:tokens") || "{}") as Record<string, string>;
    for (const k of Object.keys(all)) if (from === null || all[k] === from) { if (to) all[k] = to; else delete all[k]; }
    if (Object.keys(all).length) sessionStorage.setItem("sv:tokens", JSON.stringify(all)); else sessionStorage.removeItem("sv:tokens");
  } catch { /* nothing stored */ }
}

// Sign-out: no entry keeps a token, and the open repo reloads without one.
onSignOut(() => retoken(null, undefined));

export interface FreshOpts { cfg?: AuthConfig | null; app?: AppJson | null; fetchImpl?: Fetch; say?: (msg: string) => void }

let pending: Promise<Account | null> | null = null;

export function freshAccount(o: FreshOpts = {}): Promise<Account | null> {
  // Two writes at once share one renewal (calls with their own relay or fetch run on their own).
  if (o.cfg !== undefined || o.fetchImpl) return renew(o);
  if (!pending) pending = renew(o).finally(() => { pending = null; });
  return pending;
}

async function renew(o: FreshOpts): Promise<Account | null> {
  const a = account.get();
  if (!a) return null;
  const say = o.say || ((m: string) => toast(m, "bad"));
  const cfg = o.cfg !== undefined ? o.cfg : authConfig(o.app);
  const end = (msg: string) => { signOut(); say(msg); return null; };
  let next: Account | null;
  try { next = await refreshIfDue(cfg, a, o.fetchImpl); } catch { return end("Your GitHub sign-in couldn't be renewed. Sign in again to keep going."); }
  if (next === a) return a;
  if (!next) {
    // No way to renew here: keep the token while it still works.
    if (a.expires && a.expires > Date.now()) return a;
    return end("Your GitHub sign-in has ended. Sign in again to keep going.");
  }
  saveAccount(next);
  retoken(a.token, next.token);
  return next;
}

// The token to write with: the account's, renewed first when due.
export async function writeToken(app?: AppJson | null): Promise<string | undefined> {
  return (await freshAccount({ app }))?.token;
}
