// "Check a planned pull request" in the browser: a port of flow/preflight.py's file kinds and gaps() rule, run against
// the habits flow.json publishes (per folder when it can). No runtime imports, so node tests compare it with the Python.

// Same patterns as flow/preflight.py (TEST_FILE, CHANGELOG_FILE, DOCS_FILE) and flow/knowledge.py (LOCK_FILES, area).
const TEST_FILE = /(^|\/)(tests?|__tests__|spec|testing)(\/|$)|(_test|\.test|\.spec|_spec)\.[a-z]+$|(^|\/)test_[^/]+$/i;
const CHANGELOG_FILE = /(^|\/)(CHANGELOG|CHANGES|HISTORY|NEWS)(\.[a-z]+)?$|(^|\/)(changelog\.d|changes|news|\.changeset|changelog)\//i;
const DOCS_FILE = /(^|\/)docs?\/|\.(md|rst|adoc)$/i;
const LOCK_FILES = new Set(["Cargo.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "go.sum",
  "Gemfile.lock", "composer.lock", "Pipfile.lock", "bun.lockb", "flake.lock", "mix.lock", "pubspec.lock"]);
// A habit is something at least this share of merged PRs do (HABIT in preflight.py).
export const HABIT = 0.6;
export const KINDS = ["tests", "changelog", "docs"] as const;
export type Kind = (typeof KINDS)[number];
const LABEL: Record<Kind, string> = { tests: "test files", changelog: "a changelog entry", docs: "docs" };

export interface Habits {
  scope?: string; merged_prs?: number; include?: Partial<Record<Kind, number | null>>;
  size?: { median_lines?: number | null; p75_lines?: number | null; p90_lines?: number | null };
}
export interface Ask { ask: string; share: number; prs: number }
// One folder's habits as flow/preflight.py's folder_habits() publishes them (folders with 10+ merged PRs, busiest first).
export interface Folder extends Habits { area: string; reviewed_prs?: number; asks?: Ask[] }
export type Published = Habits & { asks?: Ask[]; folders?: Folder[] };
// Fewer merged PRs than this in the planned folders and the CLI compares with the whole repo (MIN_SCOPE_PRS).
export const MIN_SCOPE_PRS = 10;

// File paths from free text: one per line, or separated by commas or spaces; "./" and a leading "/" dropped.
export function parsePaths(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split(/[\s,]+/)) {
    const p = raw.trim().replace(/\\/g, "/").replace(/^\.\//, "").replace(/^\/+/, "");
    if (p && !out.includes(p)) out.push(p);
  }
  return out;
}

export function kinds(paths: string[]): Set<Kind> {
  const out = new Set<Kind>();
  for (const p of paths) {
    if (TEST_FILE.test(p)) out.add("tests");
    if (CHANGELOG_FILE.test(p)) out.add("changelog");
    else if (DOCS_FILE.test(p)) out.add("docs");
  }
  return out;
}

export function area(path: string): string {
  const parts = path.split("/");
  if (parts.length === 1) return "(root)";
  return parts.length === 2 ? parts[0]! : parts.slice(0, 2).join("/");
}

export function areas(paths: string[]): string[] {
  return [...new Set(paths.filter((p) => !LOCK_FILES.has(p.split("/").pop() || "")).map(area))].sort();
}

export interface Row { what: Kind; share: number | null; have: boolean; verdict: "missing" | "included" | "optional" | "expected" }
export interface Check { rows: Row[]; lines: number | null; size: "unusual" | "big" | "usual" | null; gaps: { what: string; why: string }[] }

// What a planned PR includes against the habits, and the same gap sentences the workflow's note uses.
export function check(paths: string[], lines: number | null, h: Habits): Check {
  const have = kinds(paths), scope = h.scope || "whole repo";
  const rows: Row[] = KINDS.map((k) => {
    const share = h.include?.[k] ?? null, got = have.has(k);
    return { what: k, share, have: got, verdict: got ? "included" : share != null && share >= HABIT ? "missing" : "optional" };
  });
  const gaps: { what: string; why: string }[] = [];
  if (h.merged_prs) {
    // Kinds are judged only when files were named, as the workflow judges only the files it could read.
    if (paths.length) for (const r of rows) if (r.verdict === "missing") gaps.push({ what: r.what, why: `${Math.round((r.share ?? 0) * 100)}% of merged PRs in ${scope} include ${LABEL[r.what]}` });
    const p90 = h.size?.p90_lines;
    if (lines != null && p90 != null && lines > p90) gaps.push({ what: "size", why: `${lines} lines; 90% of merged PRs in ${scope} have at most ${p90}` });
  }
  const p75 = h.size?.p75_lines, p90 = h.size?.p90_lines;
  const size = lines == null || p90 == null ? null : lines > p90 ? "unusual" : p75 != null && lines > p75 ? "big" : "usual";
  // With no files named, a habit is only "expected", never "missing".
  return { rows: paths.length ? rows : rows.map((r) => ({ ...r, verdict: r.verdict === "missing" ? "expected" : r.verdict })), lines, size, gaps };
}

export interface Basis { h: Habits; asks: Ask[]; kind: "folder" | "folders" | "repo"; used: string[]; left: string[] }

// Which published habits a planned PR is compared with, as the CLI narrows it: the one folder it touches exactly; several
// folders combined (an estimate: the CLI pools their PRs, which per-folder figures can't); else the whole repo.
// `history` names folders known to have merged PRs (the knowledge map); others count as new folders without history.
export function basis(paths: string[], h: Published, history: string[] = []): Basis {
  const planned = areas(paths), pub = (h.folders || []).filter((f) => planned.includes(f.area));
  const left = planned.filter((a) => !pub.some((f) => f.area === a) && history.includes(a));
  const repo: Basis = { h, asks: h.asks || [], kind: "repo", used: [], left };
  if (!pub.length) return repo;
  const used = pub.map((f) => f.area).sort();
  if (pub.length === 1 && !left.length) {
    const f = pub[0]!;
    // Asks narrow only where 10+ reviewed PRs were read, as flow/preflight.py's preflight() does.
    return { h: { ...f, scope: f.area }, asks: (f.reviewed_prs ?? 0) >= MIN_SCOPE_PRS ? f.asks || [] : h.asks || [], kind: "folder", used, left };
  }
  const n = pub.reduce((s, f) => s + (f.merged_prs || 0), 0);
  if (!n) return repo;
  const mean = (get: (f: Folder) => number | null | undefined, digits: number) => {
    const have = pub.filter((f) => get(f) != null), w = have.reduce((s, f) => s + (f.merged_prs || 0), 0);
    if (!w) return null;
    const v = have.reduce((s, f) => s + get(f)! * (f.merged_prs || 0), 0) / w, k = 10 ** digits;
    return Math.round(v * k) / k;
  };
  const include = Object.fromEntries(KINDS.map((k) => [k, mean((f) => f.include?.[k], 4)])) as Record<Kind, number | null>;
  const size = { median_lines: mean((f) => f.size?.median_lines, 0), p75_lines: mean((f) => f.size?.p75_lines, 0), p90_lines: mean((f) => f.size?.p90_lines, 0) };
  // Asks combine by counts: PRs where it came up over reviewed PRs, across the folders that published them.
  const asked = pub.filter((f) => (f.reviewed_prs ?? 0) >= MIN_SCOPE_PRS), reviewed = asked.reduce((s, f) => s + (f.reviewed_prs || 0), 0);
  const counts = new Map<string, number>();
  for (const f of asked) for (const a of f.asks || []) counts.set(a.ask, (counts.get(a.ask) || 0) + a.prs);
  const asks = reviewed ? [...counts].map(([ask, c]) => ({ ask, prs: c, share: Math.round((c / reviewed) * 10000) / 10000 })).sort((a, b) => b.prs - a.prs) : h.asks || [];
  return { h: { scope: used.join(", "), merged_prs: n, include, size }, asks, kind: "folders", used, left };
}
