// In-app links to the docs: helpHref("dora-guide.md", "Change failure rate") is "#/help/dora-guide#change-failure-rate".
// Use it for an InfoButton's doc ({ doc: helpHref(...) }) so "Learn more" opens the Help page at that section.
const slug = (t: string) => t.trim().toLowerCase().replace(/[^\p{L}\p{N}\p{M}\s_-]/gu, "").replace(/\s/g, "-");

export function helpHref(doc: string, heading?: string): string {
  const [file = "", anchor] = doc.split("#");
  const id = file.replace(/^docs\//, "").replace(/\.md$/, "").replace(/\//g, "-");
  const h = heading ? slug(heading) : anchor;
  return `#/help/${id}${h ? "#" + h : ""}`;
}
