// Activity: every decision and settings change, who made it, why, until when and where, newest first; what is in force
// with an undo in one click. The data branch's git history keeps the same record.
import "./activity.css";
import type { PageProps } from "../app/routes";
import { inForce, useFiles } from "../data/files";
import { ago, count } from "../data/format";
import type { Decision, DecisionsJson } from "../data/types";
import { fmt, type SettingsFile } from "../features/settingsModel";
import { Decide } from "../features/Decide";
import { Button } from "../ui/Button";
import { CodeBlock, EmptyState, InfoButton, PageSkeleton, Pill } from "../ui/bits";
import { Card, GroupedList, ListRow, Page, Section, Stat, Stats } from "../ui/Page";
import { Table } from "../ui/Table";

const UNDO: Record<string, string> = { quarantine: "unquarantine", mute: "unmute", acknowledge: "reopen", snooze: "reopen", exclude: "include", accept: "reopen" };
const CALM = ["unmute", "unquarantine", "reopen", "include"];
const said = (d: Decision) => (d.verb === "set" ? "changed" : d.verb);
// "null to true" or "14.0 to 20" from a settings change, worded as the Settings page words values ("Off to On", "14 h to 20 h").
function worded(d: Decision, defs: SettingsFile["settings"]): string | null | undefined {
  const m = d.kind === "setting" && d.reason?.match(/^(.*) to (.*)$/);
  const def = m ? (defs || []).find((x) => x.key === d.id) : null;
  if (!m || !def) return d.reason;
  const val = (t: string) => { let v: unknown; try { v = JSON.parse(t); } catch { v = t; } return fmt(v ?? def.default, def.kind, def.unit); };
  return `${val(m[1]!)} to ${val(m[2]!)}`;
}
const tone = (d: Decision) => (CALM.includes(d.verb) ? "good" : d.kind === "setting" ? "neutral" : "accent");

export default function Activity({ app }: PageProps) {
  const f = useFiles<{ d: DecisionsJson; s: SettingsFile }>({ d: "decisions.json", s: "settings.json" });
  if (!f.ready) return <PageSkeleton />;
  const state = f.d?.state || {}, defs = f.s?.settings;
  // A log line missing its reason or end date takes them from the same decision in force.
  const log = (f.d?.log || []).map((d) => { const s = state[`${d.kind}:${d.id}`];
    const same = s && s.verb === d.verb && (!d.at || !s.at || s.at === d.at);
    const out = { ...d, until: d.until ?? (same ? s.until : null), reason: d.reason ?? (same ? s.reason : null) };
    return { ...out, reason: worded(out, defs) }; });
  const active = Object.values(state).filter(inForce)
    .sort((a, b) => (a.until ? 0 : 1) - (b.until ? 0 : 1) || String(a.until || "").localeCompare(String(b.until || "")));
  const n = (verbs: string[]) => active.filter((d) => verbs.includes(d.verb)).length;
  return <Page title="Activity" subtitle="Decisions and settings changes made on GitHub or from this app, newest first.">
    <Section title="At a glance" description="What still changes something today."
      info={<InfoButton info={{ title: "Decisions", doc: "app.md#making-a-decision", body: <>A decision is in force until it ends or someone undoes it.
        Unmutes, reopens and confirmations only undo or rate one, so they are not counted. Git history of the data branch keeps the same record.</> }} />}>
      <Stats>
        <Stat label="Decisions in force" value={active.length} />
        <Stat label="Quarantined" value={n(["quarantine"])} />
        <Stat label="Muted or acknowledged" value={n(["mute", "acknowledge"])} />
        <Stat label="Excluded pull requests" value={n(["exclude"])} />
        <Stat label="Settings changes" value={log.filter((d) => d.kind === "setting").length} note="in the log" />
      </Stats>
    </Section>

    <Section title="In force" description="Ending soon first. Undo one in a click; the workflow applies it and logs who and why."
      action={<Pill tone={active.length ? "accent" : "good"}>{active.length ? count(active.length, "decision") : "None"}</Pill>}>
      {active.length && app ? <GroupedList label="Decisions in force">{active.map((d) => <ListRow mono title={`${d.kind}:${d.id}`}
        leading={<Pill tone="accent" icon="clock">{d.verb}</Pill>}
        subtitle={`${d.until ? `until ${d.until}` : "no end date"}, by ${d.by}${d.reason ? `: ${d.reason}` : ""}`}
        trailing={UNDO[d.verb] && d.kind !== "rerun" ? <Decide app={app} kind={d.kind} id={d.id} verbs={[UNDO[d.verb]!]} label="Undo" /> : null} />)}</GroupedList>
        : <Card><EmptyState icon="check" title="Nothing is in force.">Quarantines, mutes, snoozes and accepted risks show here with their end date.</EmptyState></Card>}
    </Section>

    {log.length ? <Section title="Timeline" description={`The newest ${Math.min(log.length, 12)}.`}>
      <Card pad={false}><ol class="timeline">{log.slice(0, 12).map((d) => <li class={`tl tl-${tone(d)}`}>
        <span class="tl-dot" aria-hidden="true" />
        <div class="tl-body">
          <p class="tl-line"><b>{d.by}</b> {said(d)} <span class="mono-soft">{d.kind}:{d.id}</span>{d.until ? ` until ${d.until}` : ""}</p>
          <p class="tl-meta"><span title={d.at || ""}>{ago(d.at)}</span> · {d.reason || "no reason given"} · from {d.source}</p>
        </div>
      </li>)}</ol></Card>
    </Section> : null}

    <Section title="Log" description="Every decision. Filter by what was done, on what kind of item, or by who.">
      <Table name="activity" caption="Decisions log" rows={log} columns={[
        { key: "at", label: "When", raw: (d) => d.at || "", render: (d) => <span title={d.at || ""}>{ago(d.at)}</span> },
        { key: "verb", label: "Did", filter: true, render: (d) => <Pill tone={tone(d)} icon={null}>{d.verb}</Pill> },
        { key: "kind", label: "On", primary: true, filter: true, render: (d) => <span class="mono-soft">{d.kind}:{d.id}</span> },
        { key: "by", label: "Who", filter: true },
        { key: "until", label: "Until", render: (d) => d.until || "–" },
        { key: "reason", label: "Why", render: (d) => <span class="muted">{d.reason || "–"}</span> },
        { key: "source", label: "Where" }]}
        empty={<Card><EmptyState icon="activity" title="No decisions yet." action={<Button variant="tinted" href="#/ci">Open CI Health</Button>}>
          Type a command in a comment, or use the Decide buttons in this app; every decision lands here.</EmptyState>
          <CodeBlock inline code="/stackvitals mute test:<id> for 7d because <reason>" /></Card>} />
    </Section>
  </Page>;
}
