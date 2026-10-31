// Where a repo's files come from: beside this page, another Pages site, or the repo's stackvitals-data branch.
import { repoPath } from "../github/names";

export type Source =
  | { kind: "here" }
  | { kind: "pages"; url: string }
  | { kind: "branch"; owner: string; repo: string; token?: string };

export const DATA_BRANCH = "stackvitals-data";

export function sourceKey(s: Source): string {
  return s.kind === "here" ? "here" : s.kind === "pages" ? `pages:${s.url}` : `branch:${s.owner}/${s.repo}`;
}

export function describe(s: Source): string {
  return s.kind === "here" ? "Files beside this page" : s.kind === "pages" ? `Pages site ${s.url}` : `${s.owner}/${s.repo}, ${DATA_BRANCH} branch${s.token ? " (private)" : ""}`;
}

// Joins a docs-relative path ("app.json", "../summary/x.jsonl") onto a folder, resolving "..".
export function joinPath(base: string, path: string): string {
  const parts = (base + path).split("/");
  const out: string[] = [];
  for (const p of parts) {
    if (p === "..") out.pop();
    else if (p !== "." && p !== "") out.push(p);
  }
  return out.join("/");
}

export function request(s: Source, path: string): { url: string; init: RequestInit } {
  if (s.kind === "here") return { url: path, init: { cache: "no-cache" } };
  if (s.kind === "pages") {
    const base = new URL(s.url.endsWith("/") ? s.url : s.url + "/", location.href);
    return { url: new URL(path, base).href, init: { cache: "no-cache" } };
  }
  const file = joinPath("docs/", path);
  // Throws on an odd owner or repo, so nothing is fetched (with or without a token).
  const where = repoPath(`${s.owner}/${s.repo}`);
  if (s.token) {
    return {
      url: `https://api.github.com/repos/${where}/contents/${file.split("/").map(encodeURIComponent).join("/")}?ref=${DATA_BRANCH}`,
      init: { cache: "no-cache", headers: { Accept: "application/vnd.github.raw+json", Authorization: `Bearer ${s.token}`, "X-GitHub-Api-Version": "2022-11-28" } },
    };
  }
  return { url: `https://raw.githubusercontent.com/${where}/${DATA_BRANCH}/${file.split("/").map(encodeURIComponent).join("/")}`, init: { cache: "no-cache" } };
}

export async function fetchText(s: Source, path: string): Promise<string | null> {
  try {
    const { url, init } = request(s, path);
    const r = await fetch(url, init);
    return r.ok ? await r.text() : null;
  } catch {
    return null;
  }
}

// "owner/repo", a GitHub URL or a Pages address, typed by a person, as a source.
export function parseSource(text: string, token?: string): Source | null {
  const t = text.trim();
  if (!t) return null;
  const gh = t.match(/^(?:https?:\/\/github\.com\/)?([A-Za-z0-9-]+)\/([A-Za-z0-9._-]+?)(?:\.git)?\/?$/);
  if (gh && !/\.github\.io/i.test(t)) return gh[2] === "." || gh[2] === ".." ? null : { kind: "branch", owner: gh[1]!, repo: gh[2]!, ...(token ? { token } : {}) };
  if (/^https?:\/\//.test(t) || t.startsWith("/") || t.startsWith("./")) return { kind: "pages", url: t.endsWith("/") ? t : t + "/" };
  return null;
}
