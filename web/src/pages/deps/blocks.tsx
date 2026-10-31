// Shared building blocks for Dependencies and Community: a table under its own heading strip, a framed panel with a
// header strip and an action bar, label/value facts, and the one-click "add a workflow file" card.
import "./blocks.css";
import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import type { AppJson } from "../../data/types";
import { token as tabToken } from "../../data/write";
import { makeApi } from "../../github/client";
import { writeToken } from "../../github/session";
import { account } from "../../github/token";
import { useStore } from "../../data/store";
import { filePr } from "../../github/setup";
import { newFile } from "../../github/links";
import { Button } from "../../ui/Button";
import { CodeBlock, CopyButton, toast } from "../../ui/bits";
import { PasteNote, onPrefill } from "../../ui/prefill";
import { Icon } from "../../ui/icons";

// A table (or any block) with a visible heading on its frame; the table keeps only a screen-reader caption.
export function Framed({ title, note, action, children }: { title: string; note?: ComponentChildren; action?: ComponentChildren; children: ComponentChildren }) {
  return <div class="blk-tbl"><div class="blk-tbl-h"><h3>{title}</h3>{note ? <span class="blk-tbl-note">{note}</span> : null}
    {action ? <span class="blk-tbl-act">{action}</span> : null}</div>{children}</div>;
}

// A framed card: a heading strip (title, then an optional state), the body, then an optional action bar.
export function Panel({ title, state, bar, children, class: cls }: { title: string; state?: ComponentChildren; bar?: ComponentChildren; children?: ComponentChildren; class?: string }) {
  return <section class={"blk-panel" + (cls ? " " + cls : "")}>
    <div class="blk-panel-h"><h3>{title}</h3>{state ? <span class="blk-panel-state">{state}</span> : null}</div>
    {children ? <div class="blk-panel-b">{children}</div> : null}
    {bar ? <div class="blk-bar" role="group" aria-label={`${title}: actions`}>{bar}</div> : null}
  </section>;
}

export type Fact = [string, ComponentChildren];
// Label/value cells; a falsy row is left out.
export function Facts({ rows, class: cls }: { rows: (Fact | null | false | undefined)[]; class?: string }) {
  return <dl class={"blk-facts" + (cls ? " " + cls : "")}>{rows.filter((r): r is Fact => !!r).map(([k, v]) => <div class="blk-fact"><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}

// One new workflow file: GitHub's editor prefilled (no token), or a pull request with the signed-in account or a pasted token.
export interface NewFile { file: string; content: string; branch: string; title: string; body: string; message: string }

export function AddFile({ app, f, needs }: { app: AppJson; f: NewFile; needs: string }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [pr, setPr] = useState<{ number: number; url: string } | null>(null);
  const [err, setErr] = useState("");
  const base = app.default_branch || "main";
  const link = newFile(app.repo, base, f.file, f.content);
  const a = useStore(account);
  const has = !!(a?.token || tabToken());
  const open = async () => {
    setState("busy");
    try {
      const t = (await writeToken(app)) || tabToken();
      if (!t) throw new Error("connect GitHub first");
      const got = await filePr(makeApi(t), { repo: app.repo, base, branch: f.branch, file: f.file, content: f.content, message: f.message, title: f.title, body: f.body });
      setPr(got); setState("done"); toast(`Pull request #${got.number} opened`);
    } catch (e) { setErr(e instanceof Error ? e.message : "GitHub refused it"); setState("error"); }
  };
  return <>
    <CodeBlock title={f.file} code={f.content} />
    <div class="blk-bar blk-bar-flat" role="group" aria-label="Add the file">
      <Button variant="filled" href={link.url} external icon="external" onClick={onPrefill(link, "Opened on GitHub: press Commit changes there")}>Open on GitHub as a new file</Button>
      {has ? <Button variant="tinted" icon="bolt" loading={state === "busy"} onClick={open}>Open a pull request</Button>
        : <Button variant="plain" href="#/settings?module=account" iconEnd="right">Connect GitHub to open a pull request</Button>}
      <CopyButton text={f.content} label="Copy the file" />
    </div>
    <PasteNote link={link} />
    <p class="blk-how">GitHub's editor opens {link.paste ? "on the new file" : "with the file filled in"} on {base}; nothing is saved until you press Commit changes there.
      {has ? ` Open a pull request puts it on a ${f.branch} branch with your GitHub sign-in or token, which needs ${needs}.` : ` With GitHub connected, one click opens it as a pull request instead (the token needs ${needs}).`}</p>
    <div role="status">{state === "done" && pr ? <p class="note note-good"><Icon name="check" /><span>Pull request <a href={pr.url} target="_blank" rel="noopener noreferrer">#{pr.number}</a> is open: merge it to turn this on.</span></p> : null}</div>
    <div role="alert">{state === "error" ? <p class="note note-bad"><Icon name="warn" /><span>Not opened: {err}. The GitHub editor link works without a token.</span></p> : null}</div>
  </>;
}
