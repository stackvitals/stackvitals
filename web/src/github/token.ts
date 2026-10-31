// The GitHub account this browser is connected with: this tab only by default, or this device when asked. Tiny on purpose (first screen).
import { store } from "../data/store";
import { forgetAll } from "./signout";

export interface Account {
  token: string; kind: "fine" | "classic" | "oauth" | "app"; login?: string; avatar?: string; name?: string;
  expires?: number; refresh?: string; refreshExpires?: number; remember?: boolean;
}

const KEY = "sv:gh";
const areas = (): Storage[] => { const a: Storage[] = []; try { a.push(sessionStorage, localStorage); } catch { /* storage blocked */ } return a; };

// Every Pages site of an owner shares owner.github.io's storage, so a token kept there could be read by the others.
export const canRemember = (): boolean => !/\.github\.io$/i.test(location.hostname || "");

function read(): Account | null {
  for (const s of areas()) {
    try { const v = s.getItem(KEY); if (v) { const a = JSON.parse(v) as Account; if (a && typeof a.token === "string") return a; } } catch { /* unreadable */ }
  }
  return null;
}

export const account = store<Account | null>(read());

export function saveAccount(a: Account): void {
  const acc = a.remember && !canRemember() ? { ...a, remember: false } : a;
  for (const s of areas()) { try { s.removeItem(KEY); } catch { /* ignore */ } }
  try { (acc.remember ? localStorage : sessionStorage).setItem(KEY, JSON.stringify(acc)); } catch { /* memory only */ }
  account.set(acc);
}

export { onSignOut } from "./signout";

// Forgets every token this browser holds: the account, a pasted one, per-repo ones and setup state.
export function signOut(): void {
  for (const s of areas()) {
    try {
      const keys = Array.from({ length: s.length }, (_, i) => s.key(i) || "");
      for (const k of keys) if ([KEY, "sv:tokens", "sv:token", "sv:oauth"].includes(k) || k.startsWith("sv:setup:")) s.removeItem(k);
    } catch { /* ignore */ }
  }
  account.set(null);
  forgetAll();
}

export const accountToken = (): string | undefined => account.get()?.token;

// ?welcome, a sign-in callback, or a page with no data beside it shows the Welcome screen.
const q = new URLSearchParams(location.search);
export const welcome = store<boolean>(q.has("welcome") || (q.has("code") && q.has("state")));

// A signed-in token near its end is renewed at start; the renewal code loads only then.
const at = account.get()?.expires;
if (at && at - Date.now() < 5 * 60000) void import("./session").then((m) => m.freshAccount()).catch(() => { /* retried before each write */ });
