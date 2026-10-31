// Prefilled github.com links (a new file in GitHub's editor, a new issue), kept under the length GitHub accepts.
// No runtime imports: the first screen loads it (ui/bits), and tests run it on its own.

// Measured 2026-10-30: GitHub answers 500 past ~5,700 characters of link signed out (the cap is link + cookies + headers; signed in sends more).
export const GH_LINK_MAX = 4000;

// `paste` is set when the content didn't fit: the link then prefills only the file name (or the title) and the content is pasted.
export interface PrefillLink { url: string; kind: "file" | "issue"; paste: string | null }

export const PASTE_FILE = "The file is too long for a GitHub link: it's copied; paste it into GitHub's editor (Ctrl+V or Cmd+V), then commit.";
export const PASTE_ISSUE = "The request is too long for a GitHub link: it's copied; paste it into the issue's description (Ctrl+V or Cmd+V), then submit.";
export const PASTE_FILE_BEFORE = "The file is too long for a GitHub link, so this button copies it first: paste it into GitHub's editor (Ctrl+V or Cmd+V), then commit.";
export const PASTE_ISSUE_BEFORE = "The request is too long for a GitHub link, so this button copies it first: paste it into the issue's description (Ctrl+V or Cmd+V), then submit.";

// Spaces as "+" (GitHub reads the query as a form, like URLSearchParams), which keeps the link about a third shorter.
const q = (s: string) => encodeURIComponent(s).replace(/%20/g, "+");

// GitHub's editor on a new file: filled in when it fits, else only the file name, with `paste` (default: the same content) to paste.
export function newFile(repo: string, branch: string, file: string, content: string, paste: string = content): PrefillLink {
  const base = `https://github.com/${repo}/new/${encodeURIComponent(branch)}?filename=${q(file)}`;
  const url = `${base}&value=${q(content)}`;
  return url.length <= GH_LINK_MAX ? { url, kind: "file", paste: null } : { url: base, kind: "file", paste };
}

// A new issue: title and body when they fit, else the title only and the body to paste.
export function newIssue(repo: string, title: string, body: string): PrefillLink {
  const base = `https://github.com/${repo}/issues/new?title=${encodeURIComponent(title.slice(0, 200))}`;
  const url = `${base}&body=${encodeURIComponent(body)}`;
  return url.length <= GH_LINK_MAX ? { url, kind: "issue", paste: null } : { url: base, kind: "issue", paste: body };
}

