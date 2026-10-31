// Overview's structured parts: the decision queue as a table, fix-first cards, decision tables and the decision builder.
import { useState } from "preact/hooks";
import { href } from "../../app/router";
import { ago, count, day, hours, parseStamp } from "../../data/format";
import type { AppJson, Decision, Finding } from "../../data/types";
import { DECIDE_SEND, Decide, LASTS, Send, WORDS, decision, later } from "../../features/Decide";
import { FINDING_AREA, jobId, type QueueItem, type VitalFiles } from "../../features/vitals";
import { Button } from "../../ui/Button";
import { CodeBlock, EmptyState, Pill } from "../../ui/bits";
import { DateInput, Field, SegmentedControl, Select, TextInput } from "../../ui/controls";
import { Card } from "../../ui/Page";
import { Table, type Column } from "../../ui/Table";

const sinceDays = (s: string | null | undefined): number | null => {
  const t = parseStamp(s);
  return Number.isNaN(t) ? null : Math.max(0, (Date.now() - t) / 864e5);
};
const KIND_WORD: Record<string, string> = { test: "Test", job: "Job", package: "Package", finding: "Finding", pr: "Pull request", issue: "Issue" };
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const verbWord = (v: string) => (WORDS[v] || cap(v)).split(":")[0]!;
const kindWord = (k: string) => KIND_WORD[k] || k.charAt(0).toUpperCase() + k.slice(1);

// One waiting item, split into the columns the table shows.
export interface Need { id: string; item: QueueItem; where: string; whereHref: string; external?: boolean; mono?: boolean; detail: string; wait: number | null }

export function needs(todo: QueueItem[], f: VitalFiles): Need[] {
  const at: Record<string, number> = {};
  const nth = (k: string) => (at[k] = (at[k] ?? -1) + 1);
  return todo.map((t, i) => {
    const base = { id: `${t.kind}-${i}`, item: t, whereHref: t.href, external: t.external };
    if (t.decide?.kind === "test") {
      const x = (f.ci?.tests || []).find((r) => r.id === t.decide!.id);
      return { ...base, where: t.decide.id, mono: true, wait: sinceDays(x?.since),
        detail: x ? `${x.state === "flaky" ? x.flake_events : x.failures} of ${x.runs} runs ${x.state === "flaky" ? "flaked" : "failed"}` : t.meta || "" };
    }
    if (t.decide?.kind === "job") {
      const x = (f.ci?.jobs || []).find((r) => jobId(r) === t.decide!.id);
      return { ...base, where: t.decide.id, mono: true, wait: sinceDays(x?.since), detail: t.meta || "" };
    }
    if (t.kind === "prs") {
      const x = f.delivery?.stuck?.hanging_review?.[nth("prs")];
      return { ...base, where: `PR #${x?.pr ?? "?"}`, wait: sinceDays(x?.since), detail: `Review asked ${ago(x?.since)}, nobody has started` };
    }
    if (t.kind === "deps") {
      const x = f.deps?.security_overdue?.[nth("deps")];
      return { ...base, where: x?.package || t.title, mono: true, wait: x ? x.age_hours / 24 : null,
        detail: x ? `${x.from || "?"} to ${x.to || "?"} in PR #${x.pr}, open ${hours(x.age_hours)}` : t.meta || "" };
    }
    const x = f.community?.waiting?.[nth("community")];
    return { ...base, where: `${x?.kind === "issue" ? "Issue" : "PR"} #${x?.n ?? "?"}`, wait: x ? x.days : null,
      detail: x ? `Opened by a newcomer, no answer for ${count(x.days, "day")}` : t.meta || "" };
  });
}

const waitText = (d: number | null) => (d === null ? "–" : hours(d * 24));

export function NeedsTable({ app, rows }: { app: AppJson; rows: Need[] }) {
  const columns: Column<Need>[] = [
    { key: "kind", label: "Kind", filter: true, raw: (r) => r.item.what, render: (r) => <Pill tone={r.item.tone}>{r.item.what}</Pill> },
    { key: "where", label: "Where", primary: true, raw: (r) => r.where,
      render: (r) => <a class={"ov-where" + (r.mono ? " is-id" : "")} href={r.whereHref} {...(r.external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{r.where}</a> },
    { key: "detail", label: "Detail", raw: (r) => r.detail },
    { key: "wait", label: "Waiting", num: true, raw: (r) => r.wait, render: (r) => waitText(r.wait) },
    { key: "act", label: "Action", nowrap: true, raw: () => "", render: (r) => r.item.decide
      ? <Decide app={app} kind={r.item.decide.kind} id={r.item.decide.id} verbs={r.item.decide.verbs} label="Decide" />
      : <Button size="sm" variant="tinted" href={r.item.href} external={r.item.external} iconEnd={r.item.external ? "external" : undefined}>Open</Button> },
  ];
  return <div class="ov-needs"><Table rows={rows} columns={columns} name="needs-a-decision" caption="Waiting for a decision" limit={8} /></div>;
}

export function FixFirst({ fixes }: { fixes: Finding[] }) {
  if (!fixes.length) return <Card><EmptyState icon="insights" title="Nothing stands out.">Findings appear once there is enough history to rank them.</EmptyState></Card>;
  return <ol class="ov-fixes">{fixes.map((x, i) => <li class={"ov-fix" + (x.structural ? " is-structural" : "")}>
    <div class="ov-fix-head">
      <span class="ov-fix-rank num" aria-hidden="true">{i + 1}</span>
      <span class="ov-fix-kicker">Rank {i + 1}</span>
      {x.structural ? <Pill tone="watch" icon="clock">Structural</Pill> : null}
    </div>
    <div class="ov-fix-body">
      <h3 class="ov-fix-title">{x.title}</h3>
      {x.action ? <p class="ov-fix-action">{x.action}</p> : null}
      <dl class="ov-facts">
        <div><dt>Hours at stake</dt><dd class="num">{x.hours}</dd></div>
        <div><dt>Sample</dt><dd class="num">n = {x.n}</dd></div>
        <div><dt>Open since</dt><dd class="num ov-date">{x.open_since || "–"}</dd></div>
      </dl>
    </div>
    {FINDING_AREA[x.kind] ? <div class="ov-fix-foot"><Button size="sm" variant="tinted" href={href(FINDING_AREA[x.kind]!)} iconEnd="right">Open the area</Button></div> : null}
  </li>)}</ol>;
}

interface DRow { id: string; d: Decision }
const what = (r: DRow) => <span class="ov-what"><span class="ov-what-kind">{kindWord(r.d.kind)}</span><span class="ov-what-id">{r.d.id}</span></span>;
const untilText = (u?: string | null) => {
  const left = Math.ceil((parseStamp(u) - Date.now()) / 864e5);
  return !u ? "–" : Number.isNaN(left) ? String(u) : `${day(u)}${left >= 0 ? `, in ${count(left, "day")}` : ""}`;
};

export function DecisionTables({ soon, log }: { soon: Decision[]; log: Decision[] }) {
  const soonCols: Column<DRow>[] = [
    { key: "what", label: "What", primary: true, raw: (r) => `${r.d.kind}:${r.d.id}`, render: what },
    { key: "verb", label: "Decision", raw: (r) => r.d.verb, render: (r) => <Pill tone="accent" icon={null}>{cap(r.d.verb)}</Pill> },
    { key: "until", label: "Until", raw: (r) => r.d.until, render: (r) => untilText(r.d.until) },
    { key: "by", label: "By", raw: (r) => r.d.by || "" },
    { key: "reason", label: "Reason", raw: (r) => r.d.reason || "", render: (r) => r.d.reason || <span class="muted">No reason given</span> },
  ];
  const logCols: Column<DRow>[] = [
    { key: "what", label: "What", primary: true, raw: (r) => `${r.d.kind}:${r.d.id}`, render: what },
    { key: "verb", label: "Decision", raw: (r) => r.d.verb, render: (r) => <Pill tone="neutral" icon={null}>{cap(r.d.verb)}</Pill> },
    { key: "by", label: "By", raw: (r) => r.d.by || "" },
    { key: "at", label: "When", raw: (r) => r.d.at, render: (r) => ago(r.d.at) },
    { key: "source", label: "Source", raw: (r) => r.d.source || "", render: (r) => SOURCE[r.d.source || ""] || r.d.source || "–" },
  ];
  const wrap = (xs: Decision[]) => xs.map((d, i) => ({ id: String(i), d }));
  return <div class="ov-decisions">
    <h3 class="ov-sub">Ending soon</h3>
    <Table rows={wrap(soon)} columns={soonCols} name="decisions-ending-soon" caption="Decisions ending soon" search={false}
      empty={<Card><EmptyState icon="clock" title="No decision has an end date coming up.">Quarantines, mutes and snoozes show here a week before they end.</EmptyState></Card>} />
    <h3 class="ov-sub">Latest decisions</h3>
    <Table rows={wrap(log)} columns={logCols} name="latest-decisions" caption="Latest decisions" search={false}
      empty={<Card><EmptyState icon="check" title="No decisions made yet.">Each decision made here, in a comment or in the app, lands in this log.</EmptyState></Card>} />
  </div>;
}
const SOURCE: Record<string, string> = { app: "The app", comment: "A comment", issue: "An issue", dispatch: "Workflow run" };

// What the builder can decide on: items this page already knows, each with only the verbs valid for its kind.
export interface Pickable { key: string; kind: string; id: string; label: string; verbs: string[] }

export function pickables(todo: QueueItem[], f: VitalFiles, findings: Finding[]): Pickable[] {
  const out: Pickable[] = [];
  for (const t of todo) {
    if (t.decide) out.push({ key: `${t.decide.kind}:${t.decide.id}`, kind: t.decide.kind, id: t.decide.id, label: `${t.what}: ${t.decide.id}`, verbs: t.decide.verbs });
  }
  for (const x of findings) {
    const id = x.key || x.kind;
    out.push({ key: `finding:${id}`, kind: "finding", id, label: `Finding: ${x.title}`, verbs: ["snooze", "acknowledge"] });
  }
  for (const s of f.delivery?.stuck?.hanging_review || []) {
    out.push({ key: `pr:${s.pr}`, kind: "pr", id: String(s.pr), label: `Pull request #${s.pr} (review not started)`, verbs: ["exclude"] });
  }
  return out;
}

export function DecisionBuilder({ app, items, newcomers }: { app: AppJson; items: Pickable[]; newcomers: number }) {
  const [key, setKey] = useState(items[0]?.key || "");
  const item = items.find((x) => x.key === key) || items[0];
  const [verb, setVerb] = useState(item?.verbs[0] || "");
  const [days, setDays] = useState(String(LASTS[item?.verbs[0] || ""] || 0));
  const [until, setUntil] = useState("");
  const [reason, setReason] = useState("");
  if (!item) return <Card><EmptyState icon="check" title="Nothing to decide on right now.">Flaky tests and jobs, findings, security updates and stuck reviews show up here when they need a decision.</EmptyState></Card>;
  const v = item.verbs.includes(verb) ? verb : item.verbs[0]!;
  const pickVerb = (x: string) => { setVerb(x); setDays(String(LASTS[x] || 0)); };
  const d = decision(item.kind, item.id, v, days, until, reason);
  const ready = !(d.lasts && days === "date" && !until);
  return <div class="ov-builder">
    <div class="ov-build-strip"><span>Decision builder</span><span>{count(items.length, "item")} to choose from</span></div>
    <div class="ov-build-form form">
      <Field label="1. What to decide on" hint="Flaky tests and jobs, security updates, findings and stuck reviews from this page.">{(fid) =>
        <Select id={fid} value={item.key} onChange={(k) => { const n = items.find((x) => x.key === k)!; setKey(k); pickVerb(n.verbs[0]!); }}
          options={items.map((x) => ({ value: x.key, label: x.label }))} />}</Field>
      <Field label="2. The decision" hint={item.verbs.length > 1 ? "Only the decisions that apply to this kind of item." : "The one decision that applies to this kind of item."}>{(fid) =>
        <Select id={fid} value={v} onChange={pickVerb} options={item.verbs.map((x) => ({ value: x, label: WORDS[x] || x }))} />}</Field>
      {d.lasts ? <div class="field"><span class="field-label">3. For how long</span>
        <SegmentedControl label="For how long" value={days} onChange={setDays} scroll
          options={[...["7", "14", "30", "90"].map((n) => ({ value: n, label: `${n} days` })), { value: "date", label: "Until a date" }]} /></div> : null}
      {d.lasts && days === "date" ? <Field label="Until">{(fid) => <DateInput id={fid} value={until} min={later(1)} onInput={setUntil} />}</Field> : null}
      <Field label={`${d.lasts ? 4 : 3}. Why`} hint="Kept in the decisions log.">{(fid) => <TextInput id={fid} value={reason} onInput={setReason} maxLength={200} placeholder="A short reason" />}</Field>
    </div>
    <div class="ov-build-send">
      <p class="ov-build-h">What gets sent</p>
      <dl class="ov-build-sum">
        <div><dt>Item</dt><dd><span class="ov-what"><span class="ov-what-kind">{kindWord(item.kind)}</span><span class="ov-what-id">{item.id}</span></span></dd></div>
        <div><dt>Decision</dt><dd>{verbWord(v)}{d.end ? `, until ${d.end}` : ""}</dd></div>
      </dl>
      <CodeBlock inline code={d.snippet} note="The same decision as a comment: paste it on any issue or pull request in this repo." />
      {ready ? <Send app={app} title={d.title} req={d.req} {...DECIDE_SEND} /> : <p class="field-hint">Pick the date it ends, then send it.</p>}
      <p class="ov-build-note">Nothing is posted from this page. The GitHub button opens a prefilled issue that you submit there; the token path starts the workflow, which checks your access first.
        {newcomers ? ` Newcomers waiting for a first answer (${newcomers}) have no decision to record: answer them on GitHub.` : ""}</p>
    </div>
  </div>;
}
