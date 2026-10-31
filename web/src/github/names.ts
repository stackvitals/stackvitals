// Names that end up in GitHub API paths: repos, workflow files, branches. Anything odd is refused before a request is made.
const REPO_RE = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const WORKFLOW_RE = /^[A-Za-z0-9_.-]+\.ya?ml$/;
const dots = (p: string) => p === "." || p === "..";

export function isRepo(s: unknown): s is string {
  return typeof s === "string" && REPO_RE.test(s) && !s.split("/").some(dots);
}

export function checkRepo(s: unknown): string {
  if (!isRepo(s)) throw new Error(`"${String(s).slice(0, 80)}" isn't a repo name (owner/name).`);
  return s;
}

export function isWorkflowFile(s: unknown): s is string {
  return typeof s === "string" && WORKFLOW_RE.test(s) && !dots(s);
}

export function checkWorkflow(s: unknown): string {
  if (!isWorkflowFile(s)) throw new Error(`"${String(s).slice(0, 80)}" isn't a workflow file name.`);
  return s;
}

// "owner/name" with each part encoded, for an API path.
export const repoPath = (repo: unknown): string => checkRepo(repo).split("/").map(encodeURIComponent).join("/");
export const wfPath = (wf: unknown): string => encodeURIComponent(checkWorkflow(wf));
