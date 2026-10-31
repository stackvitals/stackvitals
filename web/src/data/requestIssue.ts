// A StackVitals request (data/write.ts) as a prefilled GitHub issue, kept under GitHub's link length (github/links.ts).
import { newIssue, type PrefillLink } from "../github/links";
import { isRepo } from "../github/names";
import type { AppJson } from "./types";
import { requestBody, type Req } from "./write";

// Null when the repo name isn't plain; the body goes to the clipboard when it doesn't fit (see PrefillLink).
export function issueUrl(app: AppJson, title: string, req: Req, note?: string): PrefillLink | null {
  return isRepo(app.repo) ? newIssue(app.repo, title, requestBody(req, note)) : null;
}
