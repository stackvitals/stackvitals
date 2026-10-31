// Settings without the page: the groups, labels, formats, field checks and the TOML lines to paste. No imports, so node tests load it.

export interface SettingDef { key: string; kind: string; default: unknown; help: string; module: string; choices?: string[]; unit?: string }
export interface SettingsFile { file?: string; settings?: SettingDef[]; values?: Record<string, unknown>; notes?: string[] }
export interface WorkflowInput { name: string; help: string; default: string; kind: string; choices?: string[]; secret?: boolean }
export type Changes = Record<string, unknown>;

export const GROUPS: [id: string, title: string, icon: string][] = [
  ["alerts", "Alerts", "warn"], ["agreements", "Working agreements", "prs"], ["digest", "Weekly digest", "clock"],
  ["automation", "Automation", "bolt"], ["ci", "CI health", "ci"], ["delivery", "Delivery", "delivery"],
  ["people", "People and teams", "portal"], ["deps", "Dependencies", "deps"], ["community", "Community", "community"],
  ["integrations", "Integrations", "connections"], ["benchmarks", "Benchmarks", "investment"], ["workflow", "Workflow", "setup"],
  ["appearance", "Appearance", "sun"], ["account", "Account", "lock"],
];

// The docs page for each group's "Learn more".
export const GROUP_DOC: Record<string, string> = { integrations: "connectors", workflow: "install", benchmarks: "coverage", appearance: "app", account: "privacy" };

export const groupOf = (s: SettingDef): string => (s.key.startsWith("benchmarks.") ? "benchmarks" : s.module);

export function valueAt(values: unknown, key: string): unknown {
  return key.split(".").reduce<unknown>((node, part) => (node && typeof node === "object" ? (node as Record<string, unknown>)[part] : undefined), values);
}

export const same = (a: unknown, b: unknown): boolean => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

const WORDS: Record<string, string> = {
  p75: "P75", p50: "P50", ms: "ms", pr: "PR", prs: "PRs", ci: "CI", jql: "JQL", url: "URL", utc: "UTC", io: "io", dora: "DORA",
};
const LABELS: Record<string, string> = {
  "alerts.pickup_p75_hours": "Pickup time", "alerts.review_p75_hours": "Review time", "alerts.cycle_p75_hours": "Cycle time",
  "alerts.change_failure_rate": "Change failure rate", "alerts.channels": "Send alerts to", "digest.channels": "Send the digest to",
  "digest.enabled": "Weekly digest", "digest.pulse": "Pulse questions", "ci.mute": "Muted tests", "ci.coverage.min_patch": "Patch coverage at least",
  "identity.teams": "Teams", "identity.aliases": "Renamed logins", "investment.labels": "Labels per kind of work",
  "deps.policy.min_scorecard": "Lowest Scorecard", "deps.policy.max_severity": "Highest advisory severity", "deps.licenses.deny": "Licences not allowed",
};

export function label(key: string): string {
  if (LABELS[key]) return LABELS[key]!;
  const leaf = key.split(".").pop()!.replace(/^wf:/, "");
  const words = leaf.split(/[_-]/).map((w) => WORDS[w] ?? w);
  const text = words.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// The sub-heading a setting sits under inside its group (CI monitors, one connector...).
export function sub(key: string): string {
  const parts = key.split(".");
  if (parts[0] === "connectors") return parts[1]!.replace("incident_io", "incident.io").replace(/^./, (c) => c.toUpperCase());
  if (parts[1] === "monitors") return label(parts[2]!) + " monitor";
  if (parts[0] === "ci") return ({ mute: "Mute and quarantine", quarantine: "Mute and quarantine", coverage: "Coverage", triage: "Model triage" } as Record<string, string>)[parts[1]!] || "";
  if (parts[0] === "deps") return parts[1] === "policy" || parts[1] === "licenses" ? "Policy" : "Lookups";
  return "";
}

export const brief = (help: string): string => (help.match(/^.*?[.;](?=\s|$)/)?.[0] || help).replace(/;$/, ".");

// A choice reads as a word ("monday" as "Monday", "ci" as "CI").
const word = (v: unknown, kind: string): unknown => (typeof v === "string" && kind.startsWith("choice") ? (v === "ci" ? "CI" : v.charAt(0).toUpperCase() + v.slice(1)) : v);

export function fmt(value: unknown, kind: string, unit = ""): string {
  if (value === null || value === undefined || value === "") return kind === "switch" ? "Workflow input" : "Not set";
  if (typeof value === "boolean") return value ? "On" : "Off";
  if (kind === "share" && typeof value === "number") return `${Math.round(value * 1000) / 10}%`;
  if (Array.isArray(value)) return value.length ? value.map((v) => word(v, kind)).join(", ") : "None";
  if (kind === "choice") return String(word(value, kind));
  if (typeof value === "object") {
    const e = Object.entries(value as Record<string, unknown>);
    return e.length ? e.map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join("; ") : "None";
  }
  if (typeof value === "number" && (kind === "hours" || unit)) return `${value} ${unit || "h"}`;
  return String(value);
}

// A field's problem in words, or "" when the value can be sent.
export function check(key: string, kind: string, value: unknown): string {
  if (typeof value === "number" && (Number.isNaN(value) || value < 0)) return "A number, 0 or more.";
  if (kind === "share" && typeof value === "number" && value > 1) return "A share from 0 to 100%.";
  if (typeof value !== "string" || !value) return "";
  if (kind === "regex") { try { new RegExp(value.replace(/^\(\?i\)/, "")); } catch { return "This pattern doesn't compile."; } }
  if (key === "connectors.jira.url" && !/^https:\/\/[A-Za-z0-9][A-Za-z0-9-]*\.atlassian\.net\/?$/.test(value)) return "Only a Jira Cloud site like https://acme.atlassian.net, so the key can't go elsewhere.";
  if ((key === "connectors.discourse.url" || key === "ci.triage.url") && !/^https:\/\//.test(value)) return "Needs an https address.";
  if (key === "connectors.jira.email" && !/^[^\s@]+@[^\s@]+$/.test(value)) return "That doesn't look like an email address.";
  if (kind === "date" && !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "A date like 2027-10-21.";
  return "";
}

const MAPS = ["dates", "map", "teams"];
const tomlValue = (v: unknown): string => (Array.isArray(v) ? `[${v.map((x) => JSON.stringify(x)).join(", ")}]` : typeof v === "string" ? JSON.stringify(v) : String(v));

// The TOML lines for changed settings, grouped by table, for pasting by hand (as the old app's write.js wrote them).
export function tomlSnippet(changes: Changes, kinds: Record<string, string>): string {
  const tables: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(changes)) {
    const kind = kinds[key] || "";
    if (MAPS.includes(kind)) {
      tables[key] = Object.entries((value || {}) as Record<string, unknown>).map(([k, v]) => `${JSON.stringify(k)} = ${kind === "dates" ? v : JSON.stringify(v)}`);
      continue;
    }
    const at = key.lastIndexOf(".");
    (tables[key.slice(0, at)] ||= []).push(value === null ? `# ${key.slice(at + 1)}: back to its default (remove the line)` : `${key.slice(at + 1)} = ${tomlValue(value)}`);
  }
  return Object.entries(tables).map(([t, lines]) => `[${t}]\n${lines.join("\n")}`).join("\n\n") + "\n";
}
