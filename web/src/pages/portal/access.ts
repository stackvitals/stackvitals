// `stackvitals portal check ORG` in the browser: what a token (or no token) can read in an org, one line per kind of data.
import { encPath, type Api } from "../../github/client";

export interface Line { what: string; ok: boolean | null; detail: string }
interface GhRepo { full_name: string; private?: boolean; default_branch?: string }

// The body on 2xx, null when GitHub refuses or hides it (401, 403, 404), as portal/github.py's read() does.
async function read<T>(api: Api, path: string): Promise<T | null> {
  const r = await api.call<T>("GET", path);
  if (r.ok) return r.data;
  if ([401, 403, 404, 451].includes(r.status) && !(r.status === 403 && r.headers.get("x-ratelimit-remaining") === "0")) return null;
  throw new Error(r.status === 403 || r.status === 429 ? "GitHub's rate limit is used up; try again later or with a token" : `GitHub answered ${r.status}`);
}

async function repos(api: Api, org: string, pages: number): Promise<{ list: GhRepo[]; more: boolean }> {
  const list: GhRepo[] = [];
  let base = `/orgs/${encodeURIComponent(org)}/repos?type=all`;
  for (let page = 1; page <= pages; page++) {
    let body = await read<GhRepo[]>(api, `${base}&per_page=100&page=${page}`);
    if (body === null && page === 1) {
      base = `/users/${encodeURIComponent(org)}/repos?type=owner`;
      body = await read<GhRepo[]>(api, `${base}&per_page=100&page=${page}`);
    }
    const batch = (body || []).filter((r) => r && r.full_name);
    list.push(...batch);
    if (batch.length < 100) return { list, more: false };
  }
  return { list, more: true };
}

export async function checkAccess(api: Api, org: string, pages = 10): Promise<Line[]> {
  const { list, more } = await repos(api, org, pages);
  const priv = list.filter((r) => r.private);
  const out: Line[] = [{ what: "Repos", ok: list.length > 0,
    detail: `${list.length}${more ? "+" : ""} visible (${priv.length} private)${more ? `; stopped after ${pages * 100}` : ""}` }];
  const sample = priv[0] || list[0];
  if (sample) {
    const ref = sample.default_branch ? `?ref=${encodeURIComponent(sample.default_branch)}` : "";
    let found = false;
    for (const p of [".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"]) {
      if (await read(api, `/repos/${encPath(sample.full_name)}/contents/${encPath(p)}${ref}`) !== null) { found = true; break; }
    }
    out.push({ what: "CODEOWNERS", ok: found, detail: found ? `readable (tried ${sample.full_name})` : `none found in ${sample.full_name}` });
    const rules = sample.default_branch ? await read(api, `/repos/${encPath(sample.full_name)}/rules/branches/${encodeURIComponent(sample.default_branch)}`) : null;
    out.push({ what: "Branch rules", ok: rules !== null, detail: rules !== null ? "readable" : "not available" });
  }
  const teams = await read(api, `/orgs/${encodeURIComponent(org)}/teams?per_page=1`);
  out.push({ what: "Teams", ok: teams !== null, detail: teams !== null ? "readable" : "not available" });
  const props = await read(api, `/orgs/${encodeURIComponent(org)}/properties/values?per_page=1`);
  out.push({ what: "Custom properties", ok: props !== null, detail: props !== null ? "readable" : "not available" });
  return out;
}
