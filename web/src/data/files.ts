// Every file is fetched once per visit and source; a missing file is null, never an error screen.
import { useEffect, useState } from "preact/hooks";
import { current, nameRepo } from "./repos";
import { fetchText, sourceKey, type Source } from "./source";
import { store, useStore } from "./store";
import type { AppJson, Decision } from "./types";

const cache = new Map<string, Promise<unknown>>();

function get<T>(s: Source, path: string, parse: (text: string) => T): Promise<T | null> {
  const key = sourceKey(s) + "|" + path;
  if (!cache.has(key)) cache.set(key, fetchText(s, path).then((t) => (t === null ? null : parse(t))));
  return cache.get(key) as Promise<T | null>;
}

const parseJSON = (text: string): unknown => { try { return JSON.parse(text); } catch { return null; } };

// Demo files carry times as tokens ("NOW-12m", "NOW+5d", "MON-3"), so the demo always looks current.
function demoTime(key: string, v: unknown): unknown {
  if (typeof v !== "string") return v;
  let m = v.match(/^NOW([+-])(\d+)([mhd])$/);
  if (m) {
    const ms = +m[2]! * { m: 6e4, h: 3.6e6, d: 8.64e7 }[m[3] as "m" | "h" | "d"] * (m[1] === "-" ? -1 : 1);
    const iso = new Date(Date.now() + ms).toISOString().replace(/\.\d+Z$/, "Z");
    return key === "until" || key === "oldest" || key === "newest" ? iso.slice(0, 10) : iso;
  }
  m = v.match(/^MON-(\d+)$/);
  if (m) { const d = new Date(); d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() - +m[1]!); return d.toISOString().slice(0, 7); }
  return v;
}
const isDemo = (s: Source) => s.kind === "pages" && s.url.includes("demo/");
const parserFor = (s: Source) => (isDemo(s) ? (text: string): unknown => { try { return JSON.parse(text, demoTime); } catch { return null; } } : parseJSON);

interface Packed { packed?: boolean; repos?: { score?: { rows?: [number, number | string, number][]; results?: unknown[] } }[]; rule_index: [string, string][]; result_codes: string[]; evidence_index: string[] }

// The portal file is packed (each rule named once); rows become the {id, level, result, evidence} results.
export function unpack<T>(p: T): T {
  const q = p as unknown as Packed;
  if (!q || !q.packed) return p;
  for (const r of q.repos || []) {
    if (!r.score?.rows) continue;
    r.score.results = r.score.rows.map(([i, code, e]) => ({ id: q.rule_index[i]![0], level: q.rule_index[i]![1],
      result: typeof code === "number" ? q.result_codes[code] : code, evidence: q.evidence_index[e] }));
    delete r.score.rows;
  }
  return p;
}

// Module files the manifest doesn't list were never written: no request, so no 404 in the console.
const MODULE_FILES = ["data.json", "flow.json", "delivery.json", "insights.json", "community.json", "portal.json", "alerts.json", "deps.json", "supply.json", "vulns.json", "security.json"];

// The demo repos share one copy of these files, one folder up.
const DEMO_SHARED = ["settings.json", "portal.json"];

export async function json<T = unknown>(name: string, s: Source = current.get().source): Promise<T | null> {
  if (MODULE_FILES.includes(name)) {
    const app = await get(s, "app.json", parserFor(s)) as AppJson | null;
    if (app && !Object.values(app.modules || {}).some((m) => m.file === name)) return null;
  }
  const parse = parserFor(s);
  if (isDemo(s) && DEMO_SHARED.includes(name)) name = "../" + name;
  return get(s, name, name.endsWith("portal.json") ? (t) => unpack(parse(t)) : parse) as Promise<T | null>;
}

function lines(text: string): unknown[] {
  return text.split("\n").filter((l) => l.trim()).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
}

// Summary tables sit beside the page on public repos, next to the data branch's docs otherwise (app.json says which).
export async function table<T = Record<string, unknown>>(name: string, s: Source = current.get().source): Promise<T[] | null> {
  const app = await get(s, "app.json", parserFor(s)) as AppJson | null;
  const bases = app && app.summary === null ? ["../summary/"] : ["summary/", "../summary/"];
  for (const base of bases) {
    const rows = await get(s, base + name + ".jsonl", lines);
    if (rows) return rows as T[];
  }
  return null;
}

// Bumped by refresh(), so every page fetches its files again.
export const reloads = store(0);
export function refresh(): void { cache.clear(); reloads.set((n) => n + 1); }

export type Files<S> = { ready: boolean } & { [K in keyof S]: S[K] | null };

// The files a page needs, as one object with `ready` once all have answered; follows the open repo.
export function useFiles<S extends Record<string, unknown>>(spec: { [K in keyof S]: string }): Files<S> {
  const repo = useStore(current);
  const gen = useStore(reloads);
  const key = repo.id + gen + JSON.stringify(spec);
  const [state, setState] = useState<{ key: string; data: Files<S> }>({ key: "", data: { ready: false } as Files<S> });
  useEffect(() => {
    let live = true;
    const names = Object.keys(spec) as (keyof S)[];
    Promise.all(names.map((k) => { const f = spec[k]; return f.startsWith("table:") ? table(f.slice(6), repo.source) : json(f, repo.source); }))
      .then((values) => {
        if (!live) return;
        const data = { ready: true } as Files<S>;
        names.forEach((k, i) => { (data as Record<keyof S, unknown>)[k] = values[i] ?? null; });
        setState({ key, data });
      });
    return () => { live = false; };
  }, [key]);
  return state.key === key ? state.data : ({ ready: false } as Files<S>);
}

// The open repo's manifest; undefined while loading, null when there is none.
export function useApp(): AppJson | null | undefined {
  const repo = useStore(current);
  const gen = useStore(reloads);
  const [state, setState] = useState<{ id: string; app: AppJson | null } | null>(null);
  useEffect(() => {
    let live = true;
    json<AppJson>("app.json", repo.source).then((app) => {
      if (!live) return;
      setState({ id: repo.id, app });
      if (app?.repo) nameRepo(repo.id, app.repo);
    });
    return () => { live = false; };
  }, [repo.id, gen]);
  return state && state.id === repo.id ? state.app : undefined;
}

// The newest time any module's file was written: how fresh the page is.
export function freshest(app: AppJson | null | undefined): string | null {
  const times = Object.values(app?.modules || {}).map((m) => m.updated).filter((x): x is string => !!x)
    .map((s) => String(s).replace(" UTC", "Z").replace(" ", "T")).sort();
  return times.length ? times[times.length - 1]! : null;
}

// A decision that still changes something (an unmute or a reopen only undoes one).
export const inForce = (d: Decision | null | undefined): boolean =>
  !!d && d.kind !== "setting" && d.kind !== "golden" && !["unmute", "unquarantine", "reopen", "include", "confirm", "dispute"].includes(d.verb);
