// "Check a package" in the app: everything this repo's own files say about one package name (open vulnerabilities, update
// pull requests, the licence rule, licence changes, Scorecards, reachability). No UI here.
import type { DepsFull, SupplyJson, VulnsJson } from "../../data/types";

export interface Hit { id: string; where: string; detail: string; tone: "bad" | "watch" | "neutral" | "good"; state: string; href?: string; area: string }

// "npm:lodash" or "pypi:requests" names the ecosystem; a bare name matches any.
export function parseSpec(spec: string): { eco: string | null; name: string } {
  const s = spec.trim();
  const m = /^(npm|pypi|go|maven|cargo|crates\.io|nuget|rubygems|packagist|pub|hex):(.+)$/i.exec(s);
  return m ? { eco: m[1]!.toLowerCase(), name: m[2]!.trim() } : { eco: null, name: s };
}

const norm = (s: string | undefined | null) => (s || "").trim().toLowerCase().replace(/_/g, "-");
const ecoOk = (want: string | null, have?: string) => !want || !have || norm(have).replace("crates.io", "cargo") === want.replace("crates.io", "cargo");

export function lookup(spec: string, f: { deps?: DepsFull | null; supply?: SupplyJson | null; vulns?: VulnsJson | null }, repo: string): Hit[] {
  const { eco, name } = parseSpec(spec);
  const n = norm(name);
  if (!n) return [];
  const out: Hit[] = [];
  const same = (x?: string | null) => norm(x) === n;
  for (const v of f.vulns?.open || []) {
    if (!same(v.package) || !ecoOk(eco, v.ecosystem)) continue;
    const sev = v.malware ? "malware" : v.severity || "unrated";
    out.push({ id: `v-${v.id}-${v.file}`, area: "Known vulnerability", where: v.id, href: `https://osv.dev/vulnerability/${encodeURIComponent(v.id)}`,
      detail: `${v.version || "?"} in ${v.file || "a lockfile"}; ${v.fixed ? `fixed in ${v.fixed}` : "no fix yet"}${v.ignored ? "; ignored in osv-scanner.toml" : ""}`,
      tone: v.malware || sev === "critical" || sev === "high" ? "bad" : sev === "moderate" ? "watch" : "neutral", state: sev });
  }
  const overdue = new Set((f.deps?.security_overdue || []).map((x) => x.pr));
  for (const u of f.deps?.open || []) {
    if (!same(u.package) || !ecoOk(eco, u.ecosystem)) continue;
    out.push({ id: `pr-${u.pr}`, area: "Update pull request", where: `#${u.pr}`, href: `https://github.com/${repo}/pull/${u.pr}`,
      detail: `${u.from || "?"} to ${u.to || "?"}${u.bump ? ` (${u.bump})` : ""}${u.decision ? `; accepted until ${u.decision.until}` : ""}`,
      tone: overdue.has(u.pr) ? "bad" : u.security ? "watch" : "neutral", state: overdue.has(u.pr) ? "security, overdue" : u.security ? "security update" : "open" });
  }
  for (const d of f.supply?.licences?.denied || []) {
    if (!same(d.name) || !ecoOk(eco, d.system)) continue;
    out.push({ id: `lic-${d.name}`, area: "Licence rule", where: d.licence || "?", detail: `${d.version || ""} is under a licence this repo's rule denies`.trim(), tone: "bad", state: "against the rule" });
  }
  for (const d of f.supply?.drift || []) {
    if (!same(d.name)) continue;
    out.push({ id: `drift-${d.name}`, area: "Licence change", where: `${d.from} to ${d.to}`, detail: `between ${d.from_quarter || "?"} and ${d.to_quarter || "?"}`, tone: "watch", state: "changed" });
  }
  const sc = f.supply?.scorecards || {};
  const cards: [string, { project: string; packages: string[]; score?: number; before?: number; after?: number }[]][] = [["fell", sc.drops || []], ["low", sc.low || []], ["policy", sc.below_policy || []]];
  for (const [kind, list] of cards) for (const x of list) {
    if (!x.packages.some(same)) continue;
    const now = kind === "fell" ? x.after : x.score;
    out.push({ id: `sc-${kind}-${x.project}`, area: "Scorecard", where: x.project.replace("github.com/", ""), href: `https://${x.project}`,
      detail: kind === "fell" ? `fell from ${x.before} to ${now}` : kind === "policy" ? `${now}, under this repo's minimum` : `${now}, under 4`, tone: "watch", state: kind === "fell" ? "dropped" : "low" });
  }
  for (const r of f.supply?.reachability?.findings || []) {
    if (!same(r.module)) continue;
    out.push({ id: `reach-${r.id}`, area: "Reachability (Go)", where: r.id, href: `https://pkg.go.dev/vuln/${r.id}`,
      detail: r.reach === "called" ? `your code calls it${(r.path || []).length ? ` via ${(r.path || []).join(" → ")}` : ""}` : r.reach === "imported" ? "your code imports the package" : "only required by the module",
      tone: r.reach === "called" ? "bad" : "neutral", state: r.reach });
  }
  return out;
}

// Names the page can suggest: every package one of its files mentions.
export function knownNames(f: { deps?: DepsFull | null; supply?: SupplyJson | null; vulns?: VulnsJson | null }): string[] {
  const s = new Set<string>();
  for (const v of f.vulns?.open || []) s.add(v.package);
  for (const u of f.deps?.open || []) if (u.package) s.add(u.package);
  for (const d of f.supply?.licences?.denied || []) s.add(d.name);
  for (const d of f.supply?.drift || []) s.add(d.name);
  const sc = f.supply?.scorecards || {};
  for (const x of [...(sc.drops || []), ...(sc.low || []), ...(sc.below_policy || [])]) for (const p of x.packages) s.add(p);
  return [...s].sort((a, b) => a.localeCompare(b));
}

// The CLI only knows npm and PyPI; anything else goes bare.
export function checkCommand(spec: string): string {
  const { eco, name } = parseSpec(spec);
  const n = name.replace(/[^\w@./:-]/g, "") || "<package>";
  return `stackvitals deps check ${eco === "npm" || eco === "pypi" ? `${eco}:${n}` : n}`;
}
