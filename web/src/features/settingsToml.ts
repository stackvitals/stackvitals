// Writing settings: a checked edit of .github/stackvitals.toml (a port of core/tomledit.py) and of the workflow's
// `with:` block. Only type imports, so node tests load it.
import type { Changes } from "./settingsModel";

const MAPS = ["dates", "map", "teams"];

// ---- A checked edit of the settings file, line for line as core/tomledit.py does it ----
const QUOTED = /"(?:[^"\\]|\\.)*"|'[^']*'/g;
const HEADER = /^\s*\[\[?\s*([^[\]]+?)\s*\]\]?\s*(#.*)?$/;

function render(value: unknown, kind: string): string {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") {
    if (kind === "dates") { if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error(`"${value}" isn't a date like 2026-12-31.`); return value; }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return "[" + value.map((x) => render(x, "list")).join(", ") + "]";
  throw new Error(`${JSON.stringify(value)} can't be written as a setting.`);
}

const depth = (line: string): number => { const bare = line.replace(QUOTED, "").split("#")[0]!; return bare.split("[").length - bare.split("]").length; };

function tables(lines: string[]): [string, number, number][] {
  const heads: [string, number][] = [];
  let d = 0;
  lines.forEach((line, i) => {
    const m = d === 0 ? HEADER.exec(line) : null;
    if (m) { heads.push([m[1]!.replace(/ /g, ""), i]); return; }
    if (d || /^\s*[\w"'.-]+\s*=/.test(line)) d = Math.max(d + depth(line), 0);
  });
  return heads.map(([name, start], k) => [name, start, k + 1 < heads.length ? heads[k + 1]![1] : lines.length]);
}

function comment(line: string): string {
  const at = line.replace(QUOTED, (m) => " ".repeat(m.length)).indexOf("#");
  return at >= 0 ? line.slice(at).trimEnd() : "";
}

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function keySpan(lines: string[], start: number, end: number, leaf: string): [number, number] | null {
  const re = new RegExp(`^\\s*(?:${esc(leaf)}|"${esc(leaf)}"|'${esc(leaf)}')\\s*=`);
  for (let i = start; i < end; i++) {
    if (!re.test(lines[i]!)) continue;
    let j = i, d = depth(lines[i]!);
    while (d > 0 && j + 1 < end) { j++; d += depth(lines[j]!); }
    return [i, j + 1];
  }
  return null;
}

function put(lines: string[], table: string, body: string[] | null, leaf: string | null): string[] {
  const found = tables(lines).find(([name]) => name === table);
  if (!found) {
    if (body === null) return lines;
    return [...lines, ...(lines.length && lines[lines.length - 1]!.trim() ? [""] : []), `[${table}]`, ...body];
  }
  const [, start, end] = found;
  let tail = end;
  while (tail > start + 1 && !lines[tail - 1]!.trim()) tail--;
  if (leaf === null) return [...lines.slice(0, start + 1), ...(body || []), ...lines.slice(tail)];
  const span = keySpan(lines, start + 1, end, leaf);
  if (span) {
    const note = body && body.length === 1 && span[1] - span[0] === 1 ? comment(lines[span[0]]!) : "";
    return [...lines.slice(0, span[0]), ...(note ? [`${body![0]}  ${note}`] : body || []), ...lines.slice(span[1])];
  }
  if (body === null) return lines;
  return [...lines.slice(0, tail), ...body, ...lines.slice(tail)];
}

// The file with `changes` applied (null puts a default back); throws with a sentence when it can't.
export function tomlEdit(text: string | null, changes: Changes, kinds: Record<string, string>): string {
  let lines = (text || "").replace(/\r\n/g, "\n").split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines = lines.slice(0, -1);
  for (const [key, value] of Object.entries(changes)) {
    const kind = kinds[key];
    if (!kind) throw new Error(`${key} is not a setting StackVitals knows.`);
    if (MAPS.includes(kind)) {
      if (value !== null && (typeof value !== "object" || Array.isArray(value))) throw new Error(`${key} takes a table of entries.`);
      lines = put(lines, key, value === null ? null : Object.entries(value as Record<string, unknown>).map(([k, v]) => `${JSON.stringify(k)} = ${render(v, kind)}`), null);
    } else {
      const at = key.lastIndexOf(".");
      const leaf = key.slice(at + 1);
      lines = put(lines, key.slice(0, at), value === null ? null : [`${leaf} = ${render(value, kind)}`], leaf);
    }
  }
  return lines.join("\n").replace(/^\n+|\n+$/g, "") + "\n";
}

// ---- The workflow file: the StackVitals step's `with:` inputs ----
interface WithBlock { lines: string[]; at: number; col: number; withAt: number; end: number }

function stepOf(text: string): WithBlock | null {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const at = lines.findIndex((l) => /^\s*(-\s+)?uses:\s*["']?[^"'\s]*(merge-scout|stackvitals)/i.test(l) && !/\.github\/workflows\//.test(l));
  if (at < 0) return null;
  const col = lines[at]!.indexOf("uses:");
  const indent = (l: string) => l.length - l.trimStart().length;
  // The step's own keys sit at `col`; it ends at the first line less indented (or the next "- ").
  let start = at;
  while (start > 0 && !/^\s*-\s/.test(lines[start]!) && (indent(lines[start - 1]!) >= col || !lines[start - 1]!.trim())) start--;
  let end = at + 1;
  while (end < lines.length && (!lines[end]!.trim() || lines[end]!.trimStart().startsWith("#") || indent(lines[end]!) >= col)) end++;
  while (end > at + 1 && !lines[end - 1]!.trim()) end--;
  const withAt = lines.findIndex((l, i) => i >= start && i < end && indent(l) === col && /^\s*with:\s*(#.*)?$/.test(l));
  return { lines, at, col, withAt, end };
}

function entries(b: WithBlock): { key: string; line: number; value: string }[] {
  if (b.withAt < 0) return [];
  const out: { key: string; line: number; value: string }[] = [];
  for (let i = b.withAt + 1; i < b.end; i++) {
    const l = b.lines[i]!;
    if (!l.trim() || l.trimStart().startsWith("#")) continue;
    if (l.length - l.trimStart().length <= b.col) break;
    const m = /^\s+([\w-]+):\s*(.*)$/.exec(l);
    if (m) out.push({ key: m[1]!, line: i, value: m[2]! });
  }
  return out;
}

function unyaml(raw: string): string {
  const v = raw.trim();
  if (v.startsWith('"')) { try { return JSON.parse(v.slice(0, v.lastIndexOf('"') + 1)) as string; } catch { return v; } }
  if (v.startsWith("'")) return v.slice(1, v.lastIndexOf("'")).replace(/''/g, "'");
  return v.replace(/\s+#.*$/, "");
}

// The inputs the StackVitals step sets now, or null when the file has no StackVitals step.
export function workflowValues(text: string): Record<string, string> | null {
  const b = stepOf(text);
  return b ? Object.fromEntries(entries(b).map((e) => [e.key, /^[|>]/.test(e.value.trim()) ? "(several lines)" : unyaml(e.value)])) : null;
}

export const yamlScalar = (v: string): string => (/^[\w.,/@+-]*$/.test(v) && v !== "" ? v : JSON.stringify(v));

// The workflow with these inputs set (null removes one, so its default applies); throws when there is no step to edit.
export function workflowEdit(text: string, changes: Record<string, string | null>): string {
  const b = stepOf(text);
  if (!b) throw new Error("this workflow has no StackVitals step to edit.");
  const lines = b.lines;
  const pad = " ".repeat(b.col);
  if (b.withAt < 0) { lines.splice(b.at + 1, 0, `${pad}with:`); b.withAt = b.at + 1; b.end++; }
  for (const [key, value] of Object.entries(changes)) {
    const list = entries(b);
    const hit = list.find((e) => e.key === key);
    const inner = hit ? lines[hit.line]!.slice(0, lines[hit.line]!.length - lines[hit.line]!.trimStart().length) : list[0] ? " ".repeat(lines[list[0].line]!.length - lines[list[0].line]!.trimStart().length) : pad + "  ";
    if (hit && /^[|>]/.test(hit.value.trim())) throw new Error(`${key} spans several lines; change it on GitHub.`);
    if (hit) {
      if (value === null) { lines.splice(hit.line, 1); b.end--; } else lines[hit.line] = `${inner}${key}: ${yamlScalar(value)}`;
    } else if (value !== null) {
      const after = list.length ? list[list.length - 1]!.line + 1 : b.withAt + 1;
      lines.splice(after, 0, `${inner}${key}: ${yamlScalar(value)}`);
      b.end++;
    }
  }
  return lines.join("\n");
}
