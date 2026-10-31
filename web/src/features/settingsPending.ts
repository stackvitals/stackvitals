// The settings change sent from this device for each repo, kept until the published settings show it.
import { prefs } from "../data/store";
import { same, valueAt, type Changes, type SettingDef } from "./settingsModel";

export interface Run { id: number; run_number: number; html_url: string; status: string; conclusion?: string | null }
export interface Pending { settings: Changes; via: "issue" | "copy" | "committed" | "pr" | "compare" | "dispatch"; at: string; url?: string; run?: Run }
const KEY = (repo: string) => `settings-pending:${repo}`;
export const loadPending = (repo: string) => prefs.get<Pending | null>(KEY(repo), null);
export const savePending = (repo: string, p: Pending | null) => prefs.set(KEY(repo), p);

// True once every sent value is what the last run published (null: back to its default).
export function applied(p: Pending, defs: SettingDef[], values: unknown): boolean {
  return Object.entries(p.settings).every(([k, v]) => same(valueAt(values, k), v === null ? defs.find((d) => d.key === k)?.default : v));
}
