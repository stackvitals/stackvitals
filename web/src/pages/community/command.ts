// The community report command for any public repo, with only the flags the CLI takes. No UI here.
export const REPO = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
export type Out = "text" | "json" | "html";

export function reportCommand(repo: string, months: number, out: Out): string {
  const r = REPO.test(repo.trim()) ? repo.trim() : "owner/name";
  const m = Math.round(months);
  return `stackvitals community report ${r}${m && m !== 12 ? ` --months ${m}` : ""}${out === "json" ? " --json > community.json" : out === "html" ? " --html ./community" : ""}`;
}
