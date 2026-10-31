// StackVitals sign-in relay: a Cloudflare Worker that adds the GitHub App's client secret to two calls only, the OAuth code
// exchange (with PKCE) and the token refresh. GitHub's login endpoints have no CORS, so the browser can't call them itself.
// It keeps nothing, logs no bodies and answers only the origins listed in ALLOWED_ORIGINS.

const GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token";
const MAX_BODY = 4096;
const PASS = ["access_token", "token_type", "scope", "expires_in", "refresh_token", "refresh_token_expires_in", "error", "error_description"];

export function origins(env) {
  return String(env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim().replace(/\/$/, "")).filter(Boolean);
}

function cors(origin) {
  return { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "600", Vary: "Origin" };
}

function reply(status, body, origin, extra = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff", ...(origin ? cors(origin) : {}), ...extra } });
}

const str = (v, max) => typeof v === "string" && v.length > 0 && v.length <= max;

// The two grants the app needs, with every field checked; anything else is refused before GitHub is called.
export function validate(body, allowed) {
  if (!body || typeof body !== "object") return { error: "bad_request" };
  if (body.grant_type === "authorization_code") {
    if (!str(body.code, 512) || !str(body.redirect_uri, 2048)) return { error: "bad_request" };
    // PKCE is required: a verifier of 43 to 128 unreserved characters (RFC 7636).
    if (typeof body.code_verifier !== "string" || !/^[A-Za-z0-9._~-]{43,128}$/.test(body.code_verifier)) return { error: "pkce_required" };
    let redirect;
    try { redirect = new URL(body.redirect_uri); } catch { return { error: "bad_redirect" }; }
    if (!allowed.includes(redirect.origin)) return { error: "bad_redirect" };
    return { form: { code: body.code, redirect_uri: body.redirect_uri, code_verifier: body.code_verifier } };
  }
  if (body.grant_type === "refresh_token") {
    if (!str(body.refresh_token, 1024)) return { error: "bad_request" };
    return { form: { grant_type: "refresh_token", refresh_token: body.refresh_token } };
  }
  return { error: "unsupported_grant_type" };
}

export default {
  async fetch(request, env, _ctx, fetchImpl = fetch) {
    const url = new URL(request.url);
    const allowed = origins(env);
    const origin = request.headers.get("Origin") || "";
    const ok = allowed.includes(origin);
    if (request.method === "GET" && url.pathname === "/") return new Response("StackVitals sign-in relay.", { status: 200 });
    if (url.pathname !== "/token") return reply(404, { error: "not_found" }, ok ? origin : null);
    if (request.method === "OPTIONS") return ok ? new Response(null, { status: 204, headers: cors(origin) }) : new Response(null, { status: 403 });
    if (request.method !== "POST") return reply(405, { error: "method_not_allowed" }, ok ? origin : null, { Allow: "POST, OPTIONS" });
    if (!ok) return reply(403, { error: "origin_not_allowed" }, null);
    if (!env.CLIENT_ID || !env.CLIENT_SECRET) return reply(500, { error: "relay_not_configured" }, origin);
    // Optional Cloudflare rate limit binding, one key per caller address.
    if (env.LIMITER) {
      const { success } = await env.LIMITER.limit({ key: request.headers.get("CF-Connecting-IP") || "anon" });
      if (!success) return reply(429, { error: "slow_down" }, origin, { "Retry-After": "60" });
    }
    const text = await request.text();
    if (text.length > MAX_BODY) return reply(413, { error: "too_large" }, origin);
    let body;
    try { body = JSON.parse(text); } catch { return reply(400, { error: "bad_json" }, origin); }
    const checked = validate(body, allowed);
    if (checked.error) return reply(400, { error: checked.error }, origin);
    const form = new URLSearchParams({ client_id: env.CLIENT_ID, client_secret: env.CLIENT_SECRET, ...checked.form });
    let res;
    try {
      res = await fetchImpl(GITHUB_TOKEN_URL, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "stackvitals-relay" }, body: form.toString() });
    } catch {
      return reply(502, { error: "github_unreachable" }, origin);
    }
    // GitHub's own limit passes through with its wait; no retries here.
    if (res.status === 429 || res.status >= 500) return reply(res.status === 429 ? 429 : 502, { error: "github_busy" }, origin, res.headers.get("Retry-After") ? { "Retry-After": res.headers.get("Retry-After") } : {});
    let data;
    try { data = await res.json(); } catch { return reply(502, { error: "github_bad_reply" }, origin); }
    const out = Object.fromEntries(PASS.filter((k) => data && data[k] !== undefined).map((k) => [k, data[k]]));
    return reply(out.error || !res.ok ? 400 : 200, out, origin);
  },
};
