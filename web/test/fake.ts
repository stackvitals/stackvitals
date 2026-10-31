// A fake api.github.com for tests: routes by "METHOD /path" (query ignored unless the route has one) and records each call.
export type Handler = (body: any, url: URL) => [number, unknown] | [number, unknown, Record<string, string>];

export function fakeGitHub(routes: Record<string, Handler | [number, unknown] | [number, unknown, Record<string, string>]>) {
  const calls: { method: string; path: string; body: any; auth: string | null; url: string }[] = [];
  const fetchImpl = async (url: string, init: RequestInit = {}): Promise<Response> => {
    const u = new URL(url);
    const method = (init.method || "GET").toUpperCase();
    const headers = new Headers(init.headers as HeadersInit);
    const body = init.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path: u.pathname + u.search, body, auth: headers.get("Authorization"), url });
    const route = routes[`${method} ${u.pathname}${u.search}`] || routes[`${method} ${u.pathname}`];
    if (!route) return new Response(JSON.stringify({ message: "Not Found" }), { status: 404 });
    const [status, data, extra] = typeof route === "function" ? route(body, u) : route;
    return new Response(status === 204 ? null : JSON.stringify(data), { status, headers: { "Content-Type": "application/json", ...(extra || {}) } });
  };
  return { calls, fetchImpl, writes: () => calls.filter((c) => c.method !== "GET") };
}

// An in-memory Web Storage, installed as a browser global for modules that read it.
export function fakeStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() { return m.size; },
    key: (i: number) => [...m.keys()][i] ?? null,
    getItem: (k: string) => (m.has(k) ? m.get(k)! : null),
    setItem: (k: string, v: string) => { m.set(k, String(v)); },
    removeItem: (k: string) => { m.delete(k); },
    clear: () => m.clear(),
  };
}

export function browserGlobals(hostname = "127.0.0.1"): { local: Storage; session: Storage } {
  const local = fakeStorage(), session = fakeStorage();
  const g = globalThis as any;
  for (const [k, v] of Object.entries({ localStorage: local, sessionStorage: session,
    location: { search: "", href: `https://${hostname}/`, hostname, hash: "", origin: `https://${hostname}`, pathname: "/", reload() {} } })) {
    Object.defineProperty(g, k, { value: v, configurable: true, writable: true });
  }
  g.self ??= g;
  return { local, session };
}
