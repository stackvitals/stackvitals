// Pull Requests' automation: check a planned pull request in the browser (flow/preflight.py's rule on the habits
// flow.json publishes), turn the same check on as a note on new outside PRs, and outside-PR triage from your machine.
import { useState } from "preact/hooks";
import { pct } from "../../data/format";
import type { AppJson } from "../../data/types";
import { request } from "../../data/write";
import { Send } from "../../features/Decide";
import { valueAt } from "../../features/settingsModel";
import { CodeBlock, CopyButton } from "../../ui/bits";
import { Field, TextInput } from "../../ui/controls";
import { Table } from "../../ui/Table";
import { Facts, Framed, Machine, Mark, Panel } from "../delivery/blocks";
import { areas, basis, check, HABIT, MIN_SCOPE_PRS, parsePaths, type Kind, type Published } from "./preflight";

type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const NAME: Record<Kind, string> = { tests: "Tests", changelog: "A changelog entry", docs: "Docs" };
const VERDICT = { missing: ["watch", "Missing"], included: ["good", "Included"], optional: ["neutral", "Optional here"], expected: ["accent", "Usually included"] } as const;
const SIZE = { unusual: ["bad", "Unusually big"], big: ["watch", "Bigger than most"], usual: ["good", "Usual size"] } as const;

// The in-app pre-flight: files and size in, what similar merged PRs include and whether it is unusually big out.
export function Preflight({ repo, h: all, known }: { repo: string; h: Published; known: R[] }) {
  const [text, setText] = useState("");
  const [linesText, setLines] = useState("");
  const paths = parsePaths(text);
  const lines = /^\d+$/.test(linesText.trim()) ? Number(linesText.trim()) : null;
  // Narrowed to the folders it touches when flow.json publishes them, as the CLI narrows it.
  const b = basis(paths, all, known.filter((a) => (a.prs || 0) > 0).map((a) => String(a.area)));
  const h = b.h;
  const res = check(paths, lines, h);
  const folders = areas(paths);
  // The knowledge map's folders can be deeper or shallower than a PR's areas: match either way.
  const mapped = (f: string) => known.filter((a) => a.area === f || String(a.area).startsWith(f + "/") || f.startsWith(a.area + "/"));
  const prsIn = (f: string) => { const m = mapped(f); return m.length ? Math.max(...m.map((a) => a.prs || 0)) : null; };
  const cmd = `stackvitals flow preflight ${repo}${paths.length ? ` --paths ${paths.map((p) => (/[\s"'$]/.test(p) ? JSON.stringify(p) : p)).join(" ")}` : " --paths src/app.ts"} --lines ${lines ?? 180}`;
  const list = res.rows.filter((r) => r.verdict === "missing").map((r) => `- [ ] ${NAME[r.what]} (${pct(r.share)} of merged PRs here include them)`);
  if (res.size === "unusual") list.push(`- [ ] Split it: ${lines} lines, while 90% of merged PRs here have at most ${h.size?.p90_lines}`);
  const checklist = list.length ? `Before opening this pull request:\n${list.join("\n")}` : "This pull request matches what merged pull requests here usually include.";
  const sz = res.size ? SIZE[res.size] : null;
  return <Panel title="Check a planned pull request" class="pr-pre"
    state={res.gaps.length ? <Mark tone="watch">{res.gaps.length} to look at</Mark> : paths.length || lines != null ? <Mark tone="good">Nothing stands out</Mark> : <Mark tone="neutral">Fill in the files and size</Mark>}
    bar={<><CopyButton text={checklist} label="Copy as a checklist" small /><span class="blk-note">Runs in this page from the published history; nothing is sent anywhere.</span></>}>
    <div class="blk-form">
      <Field label="Files it changes" hint="One per line, or separated by commas. Only the names are read.">{(id) =>
        <textarea id={id} class="input" value={text} placeholder={`${known[0]?.area || "src"}/handler.ts\n${known[0]?.area || "src"}/handler.test.ts`} spellcheck={false}
          onInput={(e) => setText(e.currentTarget.value)} />}</Field>
      <Field label="Lines added plus removed" hint="What git diff --shortstat says, added and removed together.">{(id) =>
        <TextInput id={id} value={linesText} onInput={(v) => setLines(v.replace(/[^\d]/g, ""))} placeholder="180" maxLength={7} />}</Field>
    </div>
    <Facts rows={[
      ["Compared with", compared(b.kind, h.merged_prs ?? 0, b.used)],
      b.kind === "folders" && b.used.length > 1 ? ["How", "Combined from each folder's published figures, so a pull request in two of them counts twice; the command below pools them exactly."] : null,
      b.left.length ? ["Left out", `${b.left.map(dir).join(", ")}: under ${MIN_SCOPE_PRS} merged pull requests there (or not among the busiest folders published), so its numbers aren't published${b.kind === "repo" ? "; the whole repo is used instead, as the command does for thin folders" : ""}.`] : null,
      b.kind === "repo" && folders.length && !b.left.length ? ["Note", `None of its folders has ${MIN_SCOPE_PRS} or more merged pull requests, so the whole repo is used, as the command does.`] : null,
      folders.length ? ["Its folders", folders.map((a) => `${a} (${prsIn(a) != null ? `${prsIn(a)} merged PRs` : "no merged history yet"})`).join(", ")] : null,
    ]} />
    <Framed title="What merged pull requests here include" note={`a habit is something ${pct(HABIT)} or more of them do`}>
      <Table name="preflight" search={false} rows={res.rows.map((r) => ({ ...r, id: r.what }))} columns={[
        { key: "what", label: "Item", primary: true, raw: (r) => NAME[r.what] },
        { key: "share", label: "Merged PRs with it", num: true, render: (r) => pct(r.share) },
        { key: "have", label: "Yours", raw: (r) => (paths.length ? (r.have ? "Yes" : "No") : "–") },
        { key: "verdict", label: "Reading", raw: (r) => VERDICT[r.verdict][1], render: (r) => <Mark tone={VERDICT[r.verdict][0]}>{VERDICT[r.verdict][1]}</Mark> }]} />
    </Framed>
    <Framed title="Size" note="lines added plus removed, against merged pull requests here">
      <Table name="preflight-size" search={false} rows={[{ id: "size" }]} columns={[
        { key: "yours", label: "Yours", num: true, raw: () => (lines == null ? "–" : String(lines)) },
        { key: "p50", label: "Median", num: true, raw: () => h.size?.median_lines ?? "–" },
        { key: "p75", label: "3 in 4 within", num: true, raw: () => h.size?.p75_lines ?? "–" },
        { key: "p90", label: "9 in 10 within", num: true, raw: () => h.size?.p90_lines ?? "–" },
        { key: "reading", label: "Reading", raw: () => (sz ? sz[1] : "Enter the size"), render: () => (sz ? <Mark tone={sz[0]}>{sz[1]}</Mark> : <span class="muted">Enter the size</span>) }]} />
    </Framed>
    {b.asks.length ? <Facts rows={[[b.kind === "repo" ? "Reviewers here often ask for" : "Reviewers in these folders often ask for", b.asks.slice(0, 3).map((a) => `${a.ask} (${pct(a.share)} of reviewed PRs)`).join(", ")]]} /> : null}
    <div class="pr-pre-cli">
      <p class="blk-note">The same check from your machine, pooling every merged pull request in exactly these folders (it reads per-pull-request history, which isn't published with this page).</p>
      <CodeBlock inline code={cmd} />
    </div>
  </Panel>;
}

const dir = (a: string) => (a === "(root)" ? "top-level files" : `${a}/`);

function compared(kind: "folder" | "folders" | "repo", n: number, used: string[]): string {
  if (kind === "repo") return `${n} merged pull requests by people across the whole repo, last 12 months`;
  return `${kind === "folders" ? "about " : ""}${n} merged pull requests by people in ${used.map(dir).join(", ")}, last 12 months`;
}

// The same check posted by the workflow on new outside PRs: the existing automation.preflight_comments switch.
export function AutoNote({ app, values }: { app: AppJson; values: unknown }) {
  const set = valueAt(values, "automation.preflight_comments");
  const on = set === true;
  return <Panel title="Post this check on new outside pull requests" class="pr-auto"
    state={on ? <Mark tone="good">On</Mark> : <Mark tone="neutral">{set === false ? "Off" : "Off (the default)"}</Mark>}>
    <Facts rows={[
      ["What it does", "One short note on each new pull request from an outside contributor that misses what merged pull requests here usually include, or is unusually big. Nothing is posted when it matches; drafts and the team's own PRs are skipped."],
      ["When it posts", "On the Team Flow run after the pull request opens (every 3 hours); one note per pull request, never edited again."],
      ["Setting", <code>automation.preflight_comments</code>],
      set == null ? ["Note", "Not set in .github/stackvitals.toml, so the workflow's preflight-comments input decides (false unless you changed it)."] : null,
    ]} />
    <Send app={app} title={`StackVitals: turn ${on ? "off" : "on"} the pre-flight note`} req={request([], { "automation.preflight_comments": !on })}
      who="anyone with write access to this repo" lands=".github/stackvitals.toml on the default branch (a pull request when it is protected)"
      when={`from the next run; the button ${on ? "turns it off" : "turns it on"}`} />
  </Panel>;
}

// Triage stays on the maintainer's machine: private by design (never stored, posted or published).
export function Triage({ repo }: { repo: string }) {
  return <Machine title="Outside pull requests most likely to merge"
    does="Each open outside pull request's chance of merging within 30 days and why, with the model's Brier score on past pull requests against always guessing the usual rate."
    why="It is private by design: the scores are worked out on demand for maintainers and never stored, posted or put on a page, so the published data the app reads doesn't carry them."
    needs={<>Python with <code>pip install stackvitals</code> and your own GitHub token (<code>GITHUB_TOKEN</code>, or <code>gh auth login</code>) that can read {repo}.</>}>
    <CodeBlock inline code={`stackvitals flow triage ${repo}`} note="Every open outside pull request, likeliest first." />
    <CodeBlock inline code={`stackvitals flow triage ${repo} --pr 123`} note="Only one pull request: put its number in place of 123." />
  </Machine>;
}
