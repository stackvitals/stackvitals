// Insights building blocks: label/value facts, a ranked finding card and a flaky-test chain panel.
import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { href } from "../../app/router";
import { count, day, hours, pct } from "../../data/format";
import type { AppJson, Decision, Finding } from "../../data/types";
import { target } from "../../data/write";
import { Commands, Decide } from "../../features/Decide";
import { FINDING_AREA } from "../../features/vitals";
import { Button } from "../../ui/Button";
import { Pill } from "../../ui/bits";
import { Icon } from "../../ui/icons";

export interface Chain {
  test: string; hours: number; prs: number; pr_list?: number[]; state?: string | null; flake_events?: number | null; runs?: number | null;
  owners?: string[]; owners_from?: string | null; decision?: Decision | null;
}

export const AREA_NAME: Record<string, string> = { ci: "CI Health", prs: "Pull Requests", community: "Community", deps: "Dependencies", delivery: "Delivery" };
const VERB: Record<string, string> = { snooze: "Snoozed", acknowledge: "Acknowledged", quarantine: "Quarantined", reopen: "Reopened", mute: "Muted" };
const verbWord = (v: string) => VERB[v] || v.charAt(0).toUpperCase() + v.slice(1);

export type Fact = [string, ComponentChildren];
export function Facts({ rows, class: cls }: { rows: (Fact | null | false | undefined)[]; class?: string }) {
  return <dl class={"ins-facts" + (cls ? " " + cls : "")}>{rows.filter((r): r is Fact => !!r).map(([k, v]) =>
    <div class="ins-fact"><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}

export const findingId = (rank: number) => `ins-f-${rank}`;
export function goTo(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  el.focus({ preventScroll: true });
}

const links = (list: number[], repo: string) => list.map((n, i) => <>{i ? ", " : ""}<a href={`https://github.com/${repo}/pull/${n}`} target="_blank" rel="noopener noreferrer">#{n}</a></>);

export function FindingRow({ app, f, rank }: { app: AppJson; f: Finding; rank: number | null }) {
  const [more, setMore] = useState(false);
  const key = f.key || f.kind;
  const area = FINDING_AREA[f.kind];
  const ev = (f.evidence || []).slice(0, 8);
  const d = f.decision;
  return <li class={"ins-f" + (d ? " is-aside" : "")} id={rank ? findingId(rank) : undefined} tabIndex={rank ? -1 : undefined}>
    <div class="ins-f-head">
      <span class="ins-rank num" aria-label={rank === null ? "Decided" : `Rank ${rank}`}>{rank ?? <Icon name="check" />}</span>
      <div class="ins-f-titles">
        <h3 class="ins-f-title">{f.title}</h3>
        {f.structural ? <span class="ins-f-kind"><Pill tone="watch" icon="clock">Structural</Pill><span class="ins-f-kind-note">keeps coming back, not a one-off</span></span> : null}
      </div>
      <div class="ins-f-hours"><span class="ins-f-num num">{f.hours}</span><span class="ins-f-unit">hours at stake</span></div>
    </div>
    {f.action ? <div class="ins-f-action"><span class="ins-k">Action</span><p>{f.action}</p></div> : null}
    <Facts rows={[
      ["Hours at stake", <span class="num">{hours(f.hours)}{f.part_of === "red_ci" ? <span class="ins-dim"> (inside the red-check hours below)</span> : null}</span>],
      ["How sure", "Estimated"],
      ["Sample", <span class="num">n = {f.n}</span>],
      ["Open since", <span class="num">{day(f.open_since)}</span>],
      f.active_share_90d !== undefined && ["Active", <span class="num">{pct(f.active_share_90d)} of the last 90 days</span>],
      ["Area", area ? <a href={href(area)}>{AREA_NAME[area] || area}</a> : "–"],
      ev.length > 0 && ["Evidence", ev.map((e, i) => <>{i ? ", " : ""}<a href={e.url} target="_blank" rel="noopener noreferrer">{e.label}</a></>)],
    ]} />
    {d ? <div class="ins-dec">
      <p class="ins-dec-h"><Pill tone="accent" icon="check">{verbWord(d.verb)}</Pill></p>
      <Facts class="ins-facts-dec" rows={[["Who", d.by || "–"], ["Until", <span class="num">{d.until ? day(d.until) : "Reopened by hand"}</span>],
        ["Why", d.reason || "No reason given"], !!d.at && ["Decided on", <span class="num">{day(d.at)}</span>]]} />
    </div> : null}
    <div class="ins-bar" role="group" aria-label="Actions">
      <Decide app={app} kind="finding" id={key} verbs={d ? ["reopen", "snooze", "acknowledge"] : ["snooze", "acknowledge"]} />
      {area ? <Button size="sm" variant="plain" href={href(area)} iconEnd="right">Open {AREA_NAME[area] || "the area"}</Button> : null}
      <Button size="sm" variant="plain" expanded={more} onClick={() => setMore(!more)} iconEnd={more ? "up" : "down"}>As a comment</Button>
    </div>
    {more ? <div class="ins-cmds"><Commands list={[
      { text: `/stackvitals snooze ${target("finding", key)} for 14d because `, note: "Off the list for two weeks, then back if it still holds." },
      { text: `/stackvitals acknowledge ${target("finding", key)} because `, note: "The team accepts it; it stays off the list until reopened." }]} /></div> : null}
  </li>;
}

// A flaky test followed end to end: the merged PRs it held red, its verdict, its owners and the decision on it.
export function ChainRow({ app, c }: { app: AppJson; c: Chain }) {
  const prs = c.pr_list || [];
  const sql = `select * from tests where test_id = '${c.test.replace(/'/g, "''")}'`;
  const d = c.decision;
  const flaky = c.state === "flaky";
  return <li class="ins-chain card">
    <div class="ins-chain-head">
      <h3 class="ins-chain-test">{c.test}</h3>
      {d ? <Pill tone="accent" icon="check">{verbWord(d.verb)}</Pill> : <Pill tone="watch" icon="clock">No decision yet</Pill>}
    </div>
    <ol class="ins-steps">
      <li><span class="ins-step-k"><Icon name="ci" />{flaky ? "Flaky" : "Re-run passed"}</span>
        <div class="ins-step-v">{flaky ? <>Failed, then passed on the same code <b class="num">{c.flake_events}</b> times in <b class="num">{c.runs}</b> runs</>
          : <>Failed, then passed on a re-run (CI Health calls it {c.state || "not tracked"})</>}</div></li>
      <li><span class="ins-step-k"><Icon name="prs" />Held PRs red</span>
        <div class="ins-step-v"><b class="num">{hours(c.hours)}</b> across {count(c.prs, "merged PR")}, until a re-run passed
          {prs.length ? <div class="ins-step-sub">Pull requests: {links(prs, app.repo)}</div> : null}</div></li>
      <li><span class="ins-step-k"><Icon name="community" />Owner</span>
        <div class="ins-step-v">{c.owners?.length ? <>{c.owners.map((o, i) => <>{i ? ", " : ""}<code class="code-inline">{o}</code></>)}
          <div class="ins-step-sub">From {c.owners_from || "CODEOWNERS"}</div></> : "Nobody: CODEOWNERS names no one for its file"}</div></li>
      <li><span class="ins-step-k"><Icon name={d ? "check" : "clock"} />Decision</span>
        <div class="ins-step-v">{d ? <Facts class="ins-facts-dec" rows={[["What", verbWord(d.verb)], ["Who", d.by || "–"], ["When", <span class="num">{day(d.at)}</span>],
          ["Until", <span class="num">{d.until ? day(d.until) : "Reopened by hand"}</span>], ["Why", d.reason || "No reason given"]]} /> : "None yet: quarantine it or acknowledge it"}</div></li>
    </ol>
    <div class="ins-bar" role="group" aria-label={`Actions for ${c.test}`}>
      {d ? null : <Decide app={app} kind="test" id={c.test} verbs={["quarantine", "acknowledge"]} />}
      <Button size="sm" variant="plain" href={`#/ci/test/${encodeURIComponent(c.test)}`} iconEnd="right">Its CI page</Button>
      {/* Only where the SQL explorer is published beside the app; otherwise the Explore page. */}
      {app.pages?.includes("explore.html") ? <Button size="sm" variant="plain" href={`explore.html#sql=${encodeURIComponent(sql)}`} iconEnd="external">Query it in Explore</Button>
        : <Button size="sm" variant="plain" href="#/explore" iconEnd="right">Explore</Button>}
    </div>
  </li>;
}
