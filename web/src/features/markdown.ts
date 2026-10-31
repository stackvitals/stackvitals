// A tiny, safe Markdown renderer for the bundled docs: headings, paragraphs, lists, quotes, code, tables and links.
// Every bit of text is escaped (raw HTML shows as text); links keep only http(s), mailto and doc paths.

// titles: doc id to title, so a link whose text is a file name ("accuracy.md") reads as the doc's title.
export interface MdContext { file: string; docs: Record<string, string>; blob?: string; titles?: Record<string, string> }
export interface Heading { level: number; text: string; id: string }

const BLOB = "https://github.com/stackvitals/stackvitals/blob/main/";

export const esc = (s: string): string => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
const unesc = (s: string): string => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");

// GitHub's heading anchors: lower case, punctuation dropped, each space a hyphen.
export const slugify = (text: string): string => text.trim().toLowerCase().replace(/[^\p{L}\p{N}\p{M}\s_-]/gu, "").replace(/\s/g, "-");

// A heading or paragraph as plain text (for anchors, search and summaries).
export const plain = (s: string): string => s.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/`+([^`]*)`+/g, "$1")
  .replace(/\*\*|__|~~/g, "").replace(/(^|\W)[*_](\S[^*_]*?)[*_](?=\W|$)/g, "$1$2").replace(/\\(.)/g, "$1").trim();

export const docId = (file: string): string => file.replace(/^docs\//, "").replace(/\.md$/, "").replace(/\//g, "-");

// Where a link in a doc goes: another doc in the app, an anchor in this one, GitHub, or nowhere (a scheme we don't allow).
export function resolve(href: string, ctx: MdContext): { href: string; external: boolean } | null {
  const h = href.trim();
  if (/^(https?:|mailto:)/i.test(h)) return { href: h, external: true };
  if (h.startsWith("#")) return { href: `#/help/${docId(ctx.file)}${h}`, external: false };
  if (/^[a-z][\w+.-]*:/i.test(h) || h.startsWith("//") || !h) return null;
  const [path = "", anchor] = h.split("#");
  const parts = ["docs", ...ctx.file.split("/").slice(0, -1)];
  for (const p of path.split("/")) { if (p === "..") parts.pop(); else if (p && p !== ".") parts.push(p); }
  const full = parts.join("/");
  const inDocs = full.startsWith("docs/") ? full.slice(5) : null;
  if (inDocs && ctx.docs[inDocs]) return { href: `#/help/${ctx.docs[inDocs]}${anchor ? "#" + anchor : ""}`, external: false };
  return { href: (ctx.blob || BLOB) + full + (anchor ? "#" + anchor : ""), external: true };
}

function inline(src: string, ctx: MdContext): string {
  const keep: string[] = [];
  const hold = (html: string) => `\u0000${keep.push(html) - 1}\u0000`;
  let s = src.replace(/\\([\\`*_{}[\]()#+\-.!|<>~])/g, (_, c: string) => hold(esc(c)));
  s = s.replace(/(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)/g, (_, _t, c: string) => hold(`<code>${esc(c.replace(/^ (.*) $/, "$1"))}</code>`));
  s = s.replace(/<(https?:\/\/[^\s<>]+)>/g, (_, u: string) => hold(`<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(u)}</a>`));
  s = esc(s);
  const link = (text: string, url: string) => {
    const to = resolve(unesc(url), ctx);
    const bare = text.replace(/^\u0000(\d+)\u0000$/, (_, i: string) => keep[+i]!.replace(/^<code>(.*)<\/code>$/, "$1"));
    const title = to && !to.external && /^[\w./-]+\.md(#[\w-]*)?$/.test(bare) ? ctx.titles?.[to.href.slice(7).split("#")[0]!] : undefined;
    const body = title ? esc(title) : emphasis(text);
    if (!body) return "";
    return to ? hold(`<a href="${esc(to.href)}"${to.external ? ' target="_blank" rel="noopener noreferrer"' : ""}>${body}</a>`) : body;
  };
  // A link target may hold balanced brackets, like a Wikipedia page or javascript:alert(1) (which is then dropped).
  const url = String.raw`((?:[^()\s]|\([^()\s]*\))+)(?:\s+&quot;.*?&quot;)?\)`;
  // Images in the docs are badges: their alt text shows instead (nothing is loaded from elsewhere).
  s = s.replace(new RegExp(String.raw`!\[([^\]]*)\]\(` + url, "g"), (_, alt: string) => (alt ? hold(`<span class="md-alt">${alt}</span>`) : ""));
  s = s.replace(new RegExp(String.raw`\[((?:[^[\]]|\[[^\]]*\])*)\]\(` + url, "g"), (_, text: string, u: string) => link(text, u));
  s = emphasis(s);
  while (/\u0000\d+\u0000/.test(s)) s = s.replace(/\u0000(\d+)\u0000/g, (_, i: string) => keep[+i]!);
  return s;
}

function emphasis(s: string): string {
  return s.replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, "<strong>$1</strong>").replace(/__(?=\S)([\s\S]*?\S)__/g, "<strong>$1</strong>")
    .replace(/~~(?=\S)([\s\S]*?\S)~~/g, "<del>$1</del>")
    .replace(/(^|[^\w*])\*(?=\S)([^*]*?\S)\*(?![\w*])/g, "$1<em>$2</em>").replace(/(^|[^\w])_(?=\S)([^_]*?\S)_(?!\w)/g, "$1<em>$2</em>");
}

const FENCE = /^\s*(`{3,}|~{3,})\s*([\w+-]*)/;
const HEAD = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const HR = /^\s*([-*_])(\s*\1){2,}\s*$/;
const ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const SEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
const indentOf = (l: string) => l.length - l.trimStart().length;
const starts = (l: string, next?: string) => FENCE.test(l) || HEAD.test(l) || HR.test(l) || ITEM.test(l) || /^\s*>/.test(l) || (l.includes("|") && !!next && SEP.test(next));

function cells(row: string): string[] {
  const out: string[] = [];
  let cur = "", tick = false;
  const s = row.trim().replace(/^\|/, "").replace(/\|$/, "");
  for (let i = 0; i < s.length; i++) {
    const c = s[i]!;
    if (c === "\\" && s[i + 1] === "|") { cur += "|"; i++; continue; }
    if (c === "`") tick = !tick;
    if (c === "|" && !tick) { out.push(cur.trim()); cur = ""; } else cur += c;
  }
  out.push(cur.trim());
  return out;
}

class Renderer {
  seen = new Map<string, number>();
  headings: Heading[] = [];
  ctx: MdContext;
  constructor(ctx: MdContext) { this.ctx = ctx; }

  id(text: string): string {
    const base = slugify(text);
    const n = this.seen.get(base);
    this.seen.set(base, (n ?? -1) + 1);
    return n === undefined ? base : `${base}-${n + 1}`;
  }

  blocks(lines: string[]): string {
    const out: string[] = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i]!;
      if (!line.trim()) { i++; continue; }
      const fence = FENCE.exec(line);
      if (fence) {
        const mark = fence[1]!, pad = indentOf(line), body: string[] = [];
        i++;
        const close = new RegExp(`^\\s*${mark[0] === "`" ? "`" : "~"}{${mark.length},}\\s*$`);
        while (i < lines.length && !close.test(lines[i]!)) { const l = lines[i++]!; body.push(l.slice(Math.min(pad, indentOf(l)))); }
        i++;
        out.push(`<pre class="md-code"${fence[2] ? ` data-lang="${esc(fence[2])}"` : ""}><code>${esc(body.join("\n"))}</code></pre>`);
        continue;
      }
      const head = HEAD.exec(line);
      if (head) {
        const level = head[1]!.length, text = plain(head[2]!), id = this.id(text), tag = `h${Math.max(2, level)}`;
        this.headings.push({ level, text, id });
        // Ids carry a prefix so a heading never clashes with the app's own ids; links use the bare anchor.
        out.push(`<${tag} id="h-${esc(id)}">${inline(head[2]!, this.ctx)}</${tag}>`);
        i++;
        continue;
      }
      if (HR.test(line)) { out.push("<hr>"); i++; continue; }
      if (line.includes("|") && i + 1 < lines.length && SEP.test(lines[i + 1]!)) {
        const align = cells(lines[i + 1]!).map((c) => (/^:-+:$/.test(c) ? "center" : /-:$/.test(c) ? "right" : ""));
        const cell = (tag: string, c: string, k: number) => `<${tag}${align[k] ? ` class="is-${align[k]}"` : ""}>${inline(c, this.ctx)}</${tag}>`;
        const headRow = cells(line).map((c, k) => cell("th", c, k)).join("");
        const rows: string[] = [];
        i += 2;
        while (i < lines.length && lines[i]!.trim() && lines[i]!.includes("|")) rows.push(`<tr>${cells(lines[i++]!).map((c, k) => cell("td", c, k)).join("")}</tr>`);
        out.push(`<div class="md-table"><table><thead><tr>${headRow}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`);
        continue;
      }
      if (/^\s*>/.test(line)) {
        const body: string[] = [];
        while (i < lines.length && lines[i]!.trim() && (/^\s*>/.test(lines[i]!) || !starts(lines[i]!))) body.push(lines[i++]!.replace(/^\s*> ?/, ""));
        out.push(`<blockquote>${this.blocks(body)}</blockquote>`);
        continue;
      }
      if (ITEM.test(line)) {
        const base = indentOf(line), block: string[] = [], start = i;
        while (i < lines.length) {
          const l = lines[i]!;
          if (!l.trim()) {
            const next = lines.slice(i + 1).find((x) => x.trim());
            if (!next || (indentOf(next) <= base && !ITEM.test(next))) break;
          } else if (indentOf(l) <= base && !ITEM.test(l) && (starts(l) || !lines[i - 1]!.trim())) break;
          else if (indentOf(l) < base && ITEM.test(l)) break;
          else if (indentOf(l) === base && ITEM.test(l) && /\d/.test(ITEM.exec(l)![2]!) !== /\d/.test(ITEM.exec(lines[start]!)![2]!)) break;
          block.push(l);
          i++;
        }
        out.push(this.list(block, base));
        continue;
      }
      const para: string[] = [];
      while (i < lines.length && lines[i]!.trim() && !(para.length && starts(lines[i]!, lines[i + 1]))) para.push(lines[i++]!.trim());
      out.push(`<p>${inline(para.join("\n"), this.ctx)}</p>`);
    }
    return out.join("\n");
  }

  list(lines: string[], base: number): string {
    const first = ITEM.exec(lines[0]!)!;
    const ordered = /\d/.test(first[2]!);
    const items: { lines: string[]; loose: boolean }[] = [];
    let width = 0;
    for (const l of lines) {
      const m = ITEM.exec(l);
      if (m && indentOf(l) === base && /\d/.test(m[2]!) === ordered) {
        items.push({ lines: [m[3]!], loose: false });
        width = m[1]!.length + m[2]!.length + 1;
      } else if (items.length) {
        const item = items[items.length - 1]!;
        if (!l.trim()) item.loose = true;
        item.lines.push(indentOf(l) >= width ? l.slice(width) : l.trimStart());
      }
    }
    const start = ordered ? parseInt(first[2]!, 10) : 1;
    const body = items.map((it) => {
      while (it.lines.length && !it.lines[it.lines.length - 1]!.trim()) it.lines.pop();
      const html = this.blocks(it.lines);
      return `<li>${it.loose ? html : html.replace(/^<p>([\s\S]*?)<\/p>/, "$1")}</li>`;
    }).join("");
    return ordered ? `<ol${start !== 1 ? ` start="${start}"` : ""}>${body}</ol>` : `<ul>${body}</ul>`;
  }
}

// The doc as HTML plus its headings (with the ids the HTML carries).
export function markdown(src: string, ctx: MdContext): { html: string; headings: Heading[] } {
  const r = new Renderer(ctx);
  const html = r.blocks(src.replace(/\r\n?/g, "\n").replace(/\u0000/g, "").split("\n"));
  return { html, headings: r.headings };
}
