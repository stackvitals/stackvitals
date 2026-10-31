// A small GitHub REST client. The token only ever goes to api.github.com; fetch is injectable for tests.
export const API = "https://api.github.com";

export interface Res<T = any> { status: number; ok: boolean; data: T; headers: Headers }

export class GhError extends Error {
  constructor(message: string, readonly status: number, readonly limited = false) { super(message); }
}

export type Fetch = (url: string, init?: RequestInit) => Promise<Response>;

export interface Api {
  authed: boolean;
  call<T = any>(method: string, path: string, body?: unknown): Promise<Res<T>>;
  // The body on 2xx, null on 404; anything else throws a GhError with a plain reason.
  get<T = any>(path: string): Promise<T | null>;
}

export function isLimited(r: { status: number; headers: Headers }): boolean {
  return r.status === 429 || (r.status === 403 && r.headers.get("x-ratelimit-remaining") === "0");
}

export function makeApi(token?: string | null, fetchImpl: Fetch = (u, i) => fetch(u, i)): Api {
  const call = async <T>(method: string, path: string, body?: unknown): Promise<Res<T>> => {
    if (!path.startsWith("/")) throw new Error("API paths start with /");
    // A "." or ".." segment (plain or encoded) would let the URL point at another repo: refuse it.
    if (path.split(/[?#]/, 1)[0]!.split("/").some((p) => /^(\.|%2e){1,2}$/i.test(p))) throw new Error("That address has a ./.. part; nothing was sent.");
    const headers: Record<string, string> = { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let res: Response;
    try {
      res = await fetchImpl(API + path, { method, headers, cache: "no-store", ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
    } catch {
      throw new GhError("GitHub didn't answer; check your connection and try again.", 0);
    }
    const text = res.status === 204 ? "" : await res.text().catch(() => "");
    let data: any = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    return { status: res.status, ok: res.ok, data: data as T, headers: res.headers };
  };
  return {
    authed: !!token,
    call,
    async get<T>(path: string): Promise<T | null> {
      const r = await call<T>("GET", path);
      if (r.ok) return r.data;
      if (r.status === 404) return null;
      throw explain(r, !!token);
    },
  };
}

export function explain(r: Res, authed: boolean): GhError {
  const msg = typeof r.data === "object" && r.data?.message ? String(r.data.message) : "";
  if (isLimited(r)) {
    return new GhError(authed ? "GitHub's hourly limit for this token is used up; try again in a while."
      : "GitHub's limit for visitors without a token is reached (60 requests an hour). Connect GitHub, or try again later.", r.status, true);
  }
  if (r.status === 401) return new GhError("GitHub refused the token: it may be expired, revoked or mistyped.", 401);
  if (r.status === 403) return new GhError(`The token isn't allowed to do this${msg ? ` (GitHub: ${msg})` : ""}.`, 403);
  return new GhError(`GitHub answered ${r.status}${msg ? `: ${msg}` : ""}.`, r.status);
}

// Every page of a list endpoint, up to `max` pages of 100.
export async function paged<T>(api: Api, path: string, max = 5, pick?: (body: any) => T[]): Promise<T[]> {
  const out: T[] = [];
  for (let page = 1; page <= max; page++) {
    const r = await api.call("GET", `${path}${path.includes("?") ? "&" : "?"}per_page=100&page=${page}`);
    if (!r.ok) throw explain(r, api.authed);
    const items = (pick ? pick(r.data) : r.data) as T[];
    out.push(...items);
    if (items.length < 100) break;
  }
  return out;
}

export function toBase64(text: string): string {
  let bin = "";
  for (const b of new TextEncoder().encode(text)) bin += String.fromCharCode(b);
  return btoa(bin);
}
export function fromBase64(b64: string): string {
  const bin = atob(b64.replace(/\s/g, ""));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

export const encPath = (p: string) => p.split("/").map(encodeURIComponent).join("/");

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
