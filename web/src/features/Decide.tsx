// Deciding on an item (quarantine, mute, acknowledge, snooze...) in a sheet, sent through one of three paths:
// a prefilled GitHub issue (one click, no token), the workflow started with your own token, or a comment command.
import { useState } from "preact/hooks";
import type { AppJson } from "../data/types";
import { issueUrl } from "../data/requestIssue";
import { dispatch, request, runStatus, setToken, target, token, tokenLink, type Req, type Run } from "../data/write";
import { Button } from "../ui/Button";
import { CodeBlock, CopyButton, toast } from "../ui/bits";
import { PasteNote, onPrefill } from "../ui/prefill";
import { DateInput, Field, SegmentedControl, Select, TextInput } from "../ui/controls";
import { Icon } from "../ui/icons";
import { Sheet } from "../ui/Sheet";

export const WORDS: Record<string, string> = {
  quarantine: "Quarantine: your test command passes while only it fails", unquarantine: "Keep out of quarantine (it blocks)",
  mute: "Mute: measured, but no alert or new issue", unmute: "Unmute", acknowledge: "Acknowledge: the team lives with it",
  snooze: "Snooze: off the list for a while", reopen: "Reopen", exclude: "Leave out of the numbers", include: "Count it again",
  accept: "Accept the risk until a date", confirm: "StackVitals got this right", dispute: "StackVitals got this wrong (say why)",
};
export const LASTS: Record<string, number> = { quarantine: 30, mute: 30, snooze: 14, accept: 30 };
export const later = (days: number) => new Date(Date.now() + days * 864e5).toISOString().slice(0, 10);

// One decision as a request, a comment command and an issue title; shared by the Decide sheet and the Overview builder.
export function decision(kind: string, id: string, verb: string, days: string, until: string, reason: string) {
  const lasts = LASTS[verb] !== undefined;
  const end = !lasts ? null : days === "date" ? until || null : later(Number(days));
  const req = request([{ verb, kind, id, until: end, reason }]);
  const snippet = `/stackvitals ${verb} ${target(kind, id)}${end ? ` until ${end}` : ""}${reason ? ` because ${reason}` : ""}`;
  return { lasts, end, req, snippet, title: `StackVitals: ${verb} ${kind} ${id}`.slice(0, 120) };
}
export const DECIDE_SEND = { who: "anyone with triage or write access to this repo", lands: "the decisions log in the stackvitals-data branch, shown on every page",
  when: "as soon as the workflow has run (a minute or two)" };

export function Send({ app, title, req, snippet, who, lands, when }: { app: AppJson; title: string; req: Req; snippet?: string; who?: string; lands?: string; when?: string }) {
  const [step, setStep] = useState<"choose" | "token" | "sending" | "sent" | "error">("choose");
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const url = issueUrl(app, title, req);
  const apply = async () => {
    if (!token()) { setStep("token"); return; }
    setStep("sending");
    try {
      let r = await dispatch(app, req);
      setRun(r); setStep("sent");
      toast("The StackVitals workflow started");
      for (let i = 0; r && i < 60 && r.status !== "completed"; i++) {
        await new Promise((ok) => setTimeout(ok, 5000));
        r = await runStatus(app, r.id);
        setRun(r);
      }
    } catch (e) {
      setError((e as Error).message); setStep("error");
    }
  };
  return <div class="send">
    <dl class="kv">
      {who ? <><dt>Who can</dt><dd>{who}</dd></> : null}
      {lands ? <><dt>Where it lands</dt><dd>{lands}</dd></> : null}
      {when ? <><dt>When</dt><dd>{when}</dd></> : null}
    </dl>
    <div class="send-actions">
      {url ? <Button variant="filled" href={url.url} external icon="external" onClick={onPrefill(url, "Opened on GitHub: press Submit there")}>Open the request on GitHub</Button> : null}
      <Button variant="tinted" icon="bolt" loading={step === "sending"} onClick={apply}>Apply now with my token</Button>
      {snippet ? <CopyButton text={snippet} label="Copy as a comment" /> : null}
    </div>
    <PasteNote link={url} />
    {step === "token" ? <div class="card card-pad token-box">
      <p>Paste a fine-grained token for <b>{app.repo}</b> with <b>Actions: read and write</b> only. <a href={tokenLink(app)} target="_blank" rel="noopener noreferrer">Create one</a> (30 days).
        It stays in this tab and goes only to api.github.com.</p>
      <div class="inline-form">
        <TextInput type="password" mono value={draft} onInput={(v) => setDraft(v.trim())} placeholder="github_pat_…" label="Fine-grained GitHub token" />
        <Button variant="filled" disabled={!draft} onClick={() => { setToken(draft, true); setDraft(""); apply(); }}>Use it and apply</Button>
      </div>
    </div> : null}
    <div role="status">{step === "sent" ? <p class="note note-good"><Icon name="check" /><span>{run
      ? <>Run <a href={run.html_url} target="_blank" rel="noopener noreferrer">#{run.run_number}</a>: {run.status === "completed" ? `finished (${run.conclusion}). Reload to see the change.` : `${run.status}…`}</>
      : "The workflow started; it shows in the Actions tab in a moment."}</span></p> : null}</div>
    <div role="alert">{step === "error" ? <p class="note note-bad"><Icon name="warn" /><span>Not sent: {error}. The GitHub issue works without a token.</span></p> : null}</div>
  </div>;
}

export function Decide({ app, kind, id, verbs, label = "Decide", size = "sm" }: { app: AppJson; kind: string; id: string; verbs: string[]; label?: string; size?: "sm" | "md" }) {
  const [open, setOpen] = useState(false);
  const [verb, setVerb] = useState(verbs[0]!);
  const [days, setDays] = useState<string>(String(LASTS[verbs[0]!] || 0));
  const [until, setUntil] = useState("");
  const [reason, setReason] = useState("");
  const { lasts, req, snippet, title } = decision(kind, id, verb, days, until, reason);
  return <>
    <Button size={size} variant="tinted" onClick={() => setOpen(true)} haspopup="dialog">{label}</Button>
    <Sheet open={open} onClose={() => setOpen(false)} title={label} description={<span class="mono-soft">{kind}: {id}</span>} size="md">
      <div class="form">
        <Field label="What to do">{(fid) => <Select id={fid} value={verb} onChange={(v) => { setVerb(v); setDays(String(LASTS[v] || 0)); }}
          options={verbs.map((v) => ({ value: v, label: WORDS[v] || v }))} />}</Field>
        {lasts ? <div class="field"><span class="field-label" id="dec-len">For how long</span>
          <SegmentedControl label="For how long" value={days} onChange={setDays} scroll
            options={[...["7", "14", "30", "90"].map((d) => ({ value: d, label: `${d} days` })), { value: "date", label: "Until a date" }]} /></div> : null}
        {lasts && days === "date" ? <Field label="Until">{(fid) => <DateInput id={fid} value={until} min={later(1)} onInput={setUntil} />}</Field> : null}
        <Field label="Why" hint="Kept in the decisions log.">{(fid) => <TextInput id={fid} value={reason} onInput={setReason} maxLength={200} placeholder="A short reason" />}</Field>
      </div>
      {lasts && days === "date" && !until ? <p class="field-hint">Pick the date it ends, then send it.</p>
        : <Send app={app} title={title} req={req} snippet={snippet} {...DECIDE_SEND} />}
    </Sheet>
  </>;
}

export function Commands({ list }: { list: { text: string; note: string }[] }) {
  return <div class="commands">{list.map((c) => <CodeBlock inline code={c.text} note={c.note} />)}</div>;
}
