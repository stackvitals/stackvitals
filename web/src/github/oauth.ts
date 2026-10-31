// Sign in with GitHub: the OAuth web flow with PKCE and a state check; only the code exchange and refresh go through the relay.
import type { Account } from "./token";
import type { AuthConfig } from "./config";
import type { Fetch } from "./client";

const SAVED = "sv:oauth";

function b64url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
const random = (n: number) => b64url(crypto.getRandomValues(new Uint8Array(n)));

export async function challenge(verifier: string): Promise<string> {
  return b64url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
}

export const redirectUri = () => location.origin + location.pathname;

export async function authorizeUrl(cfg: AuthConfig, remember: boolean, back: string): Promise<string> {
  const state = random(24), verifier = random(48);
  try { sessionStorage.setItem(SAVED, JSON.stringify({ state, verifier, remember, back, at: Date.now() })); } catch { /* the check below will fail safely */ }
  const q = new URLSearchParams({ client_id: cfg.clientId, redirect_uri: redirectUri(), state, code_challenge: await challenge(verifier),
    code_challenge_method: "S256", allow_signup: "true" });
  return `https://github.com/login/oauth/authorize?${q}`;
}

interface TokenReply { access_token?: string; expires_in?: number; refresh_token?: string; refresh_token_expires_in?: number; error?: string; error_description?: string }

async function relay(cfg: AuthConfig, body: Record<string, string>, fetchImpl: Fetch): Promise<TokenReply> {
  const res = await fetchImpl(`${cfg.relay}/token`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), credentials: "omit" });
  const data = (await res.json().catch(() => ({}))) as TokenReply;
  if (!res.ok || data.error || !data.access_token) throw new Error(data.error_description || data.error || `The sign-in relay answered ${res.status}.`);
  return data;
}

function toAccount(t: TokenReply, remember: boolean, now = Date.now()): Account {
  return { token: t.access_token!, kind: "app", remember, ...(t.expires_in ? { expires: now + t.expires_in * 1000 } : {}),
    ...(t.refresh_token ? { refresh: t.refresh_token } : {}), ...(t.refresh_token_expires_in ? { refreshExpires: now + t.refresh_token_expires_in * 1000 } : {}) };
}

// After GitHub sends the person back: ?code=&state= in the address. Returns the account, null when this isn't a callback.
export async function finishSignIn(cfg: AuthConfig, fetchImpl: Fetch = (u, i) => fetch(u, i)): Promise<{ account: Account; back: string } | null> {
  const q = new URLSearchParams(location.search);
  const code = q.get("code"), state = q.get("state");
  if (!code || !state) return null;
  let saved: { state: string; verifier: string; remember: boolean; back: string; at: number } | null = null;
  try { saved = JSON.parse(sessionStorage.getItem(SAVED) || "null"); sessionStorage.removeItem(SAVED); } catch { saved = null; }
  q.delete("code"); q.delete("state");
  history.replaceState(null, "", location.pathname + (q.toString() ? "?" + q : "") + location.hash);
  if (!saved || saved.state !== state || Date.now() - saved.at > 15 * 60000) throw new Error("The sign-in didn't match this tab (or took too long). Try again.");
  const t = await relay(cfg, { grant_type: "authorization_code", code, code_verifier: saved.verifier, redirect_uri: redirectUri() }, fetchImpl);
  return { account: toAccount(t, saved.remember), back: saved.back };
}

// A signed-in token lasts 8 hours; it is renewed through the relay shortly before.
export async function refreshIfDue(cfg: AuthConfig | null, a: Account, fetchImpl: Fetch = (u, i) => fetch(u, i), now = Date.now()): Promise<Account | null> {
  if (!a.expires || a.expires - now > 5 * 60000) return a;
  if (!cfg || !a.refresh || (a.refreshExpires && a.refreshExpires < now)) return null;
  const t = await relay(cfg, { grant_type: "refresh_token", refresh_token: a.refresh }, fetchImpl);
  return { ...a, ...toAccount(t, !!a.remember, now), kind: a.kind };
}
