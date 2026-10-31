// Sign-in settings: the relay address and GitHub App client id, set at build time (SV_RELAY, SV_CLIENT_ID) or by app.json `auth`.
import type { AppJson } from "../data/types";

declare const __SV_AUTH__: { relay?: string; clientId?: string };

export interface AuthConfig { relay: string; clientId: string }

// The page's Content-Security-Policy must allow the relay, or the browser would block the call anyway.
function allowed(origin: string): boolean {
  const csp = document.querySelector<HTMLMetaElement>('meta[http-equiv="Content-Security-Policy"]')?.content;
  if (!csp) return true;
  const connect = csp.split(";").map((d) => d.trim()).find((d) => d.startsWith("connect-src")) || "";
  return connect.split(/\s+/).includes(origin);
}

export function authConfig(app?: (AppJson & { auth?: { relay?: string; client_id?: string } }) | null): AuthConfig | null {
  const relay = app?.auth?.relay || __SV_AUTH__.relay || "";
  const clientId = app?.auth?.client_id || __SV_AUTH__.clientId || "";
  if (!relay || !clientId || !/^https:\/\//.test(relay)) return null;
  try { return allowed(new URL(relay).origin) ? { relay: relay.replace(/\/$/, ""), clientId } : null; } catch { return null; }
}
