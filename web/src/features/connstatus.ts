// A connection's status from what the last run wrote (connectors.json), the repo's secret names (with a token) and
// whether its settings are filled in. Pure, so a test can walk every case.
import { parseStamp } from "../data/format";

export type Status = "connected" | "key" | "failed" | "off" | "builtin" | "recorded";
export type Bucket = "on" | "attention" | "available";

export interface Check { ok: boolean; as?: string | null; detail?: string; checked_at?: string; fix?: string | null }
export interface Entry {
  name?: string; as_of?: string; error?: string | null; expiring?: boolean; key_expires?: string | null;
  rows?: Record<string, number>; complete?: boolean | null; scope?: string | null; check?: Check | null;
}
export interface Shape { kind: "builtin" | "key" | "nokey" | "local"; secrets?: { name: string; kind?: string; optional?: boolean }[] }

export const WORDS: Record<Status, string> = {
  connected: "Connected", key: "Needs a key", failed: "Check failed", off: "Not set up", builtin: "Built in", recorded: "Recorded only",
};
export const BUCKET: Record<Status, Bucket> = {
  connected: "on", builtin: "on", key: "attention", failed: "attention", recorded: "attention", off: "available",
};

// Secret names a run needs from this repo (variables and GitLab's own token can't be listed here).
export function needed(c: Shape): string[] {
  return (c.secrets || []).filter((s) => !s.kind || s.kind === "secret").filter((s) => !s.optional).map((s) => s.name);
}

export function missing(c: Shape, secrets: string[] | null): string[] {
  if (!secrets) return [];
  const have = new Set(secrets.map((s) => s.toUpperCase()));
  return needed(c).filter((n) => !have.has(n));
}

// A failed check counts until a later pull went through without an error.
function checkFailed(e: Entry): boolean {
  if (!e.check || e.check.ok) return false;
  const pulled = parseStamp(e.as_of), checked = parseStamp(e.check.checked_at);
  return !(e.as_of && !e.error && pulled > checked);
}

export function statusOf(c: Shape, entry: Entry | null | undefined, secrets: string[] | null, configured: boolean): Status {
  if (c.kind === "builtin") return "builtin";
  if (c.kind === "local") return "off";
  const gone = missing(c, secrets);
  if (entry) {
    if (checkFailed(entry) || entry.error) return "failed";
    const pulled = !!entry.as_of || !!entry.check?.ok;
    // History was read with a key the repo no longer has.
    if (pulled && gone.length && secrets) return entry.as_of ? "recorded" : "key";
    if (entry.expiring) return "key";
    if (pulled) return "connected";
  }
  const asked = needed(c);
  if (secrets && asked.length && !gone.length) return "connected";
  if (c.kind === "nokey") return configured ? "connected" : "off";
  if (configured || (secrets && asked.length && gone.length < asked.length)) return "key";
  return "off";
}

// Newest check first: a result written after `since` (an ISO time) or null while it hasn't come.
export function newerCheck(entry: Entry | null | undefined, since: string | null): Check | null {
  const c = entry?.check;
  if (!c?.checked_at) return null;
  return !since || parseStamp(c.checked_at) > parseStamp(since) ? c : null;
}

// Whether any of a connector's settings differ from their defaults.
export function isConfigured(values: Record<string, unknown> | null | undefined, defaults: Record<string, unknown>): boolean {
  if (!values) return false;
  return Object.entries(values).some(([k, v]) => {
    if (k === "key_expires" || k === "write_back") return false;
    const d = defaults[k];
    return JSON.stringify(v ?? null) !== JSON.stringify(d ?? null) && !(v === "" || (Array.isArray(v) && !v.length));
  });
}
