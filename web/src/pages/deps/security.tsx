// What the security checks read (security.json facts): branch protection tiers, committed binaries, SBOMs, fuzzing,
// the security policy, release signing, code scanning and publishing workflows, plus the weekly score.
import { Sparkline } from "../../charts/Sparkline";
import { day, short } from "../../data/format";
import { Pill, type PillTone } from "../../ui/bits";
import { Table } from "../../ui/Table";
import { Facts, Framed } from "./blocks";

type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const TIER: Record<string, [PillTone, string]> = { met: ["good", "met"], missing: ["bad", "missing"], unknown: ["neutral", "can't read"] };
const EFFORT: Record<string, string> = { S: "small", M: "medium", L: "large" };
export const effortWord = (e?: string) => (e ? EFFORT[e] || e : "–");
const yes = (v: unknown, on = "yes", off = "no") => (v ? <Pill tone="good">{on}</Pill> : v === false ? <Pill tone="watch">{off}</Pill> : <Pill tone="neutral">can't read</Pill>);
const list = (xs?: string[]) => (xs && xs.length ? short(xs.join(", "), 80) : <span class="muted">none</span>);

// The score's headline cells: now, the weekly line, and how the checks came out.
export function ScoreFacts({ sec }: { sec: R }) {
  const pts = ((sec.history || []) as [string, number | null][]).filter(([, s]) => s != null) as [string, number][];
  const first = pts[0], last = pts[pts.length - 1];
  const probes: R[] = sec.probes || [];
  const n = (r: string) => probes.filter((p) => p.result === r).length;
  return <Facts class="is-figures" rows={[
    ["Score", <>{sec.score == null ? "–" : sec.score}<small>{sec.score == null ? "not scored yet" : "of 10, weighed by risk"}</small></>],
    pts.length > 1 && first && last ? ["Weekly score", <span class="sec-trend"><Sparkline values={pts.map(([, s]) => s)} tone={last[1] >= first[1] ? "good" : "bad"} label={`Weekly score from ${first[1]} to ${last[1]}`} />
      <small>{first[1]} on {day(first[0])} to {last[1]} now, {pts.length} weeks kept</small></span>] : null,
    ["Failing", <>{n("fail")}<small>checks to fix</small></>],
    ["Passing", <>{n("pass")}<small>checks</small></>],
    ["Can't read", <>{n("unknown")}<small>need more access</small></>],
  ]} />;
}

export function SecurityFacts({ f, repo }: { f: R; repo: string }) {
  const b = f.branch || {}, t = f.tree || {}, w = f.workflows || {}, p = f.policy || {}, rel = f.releases || {};
  return <>
    <Framed title="Branch protection on the default branch" note={`Level ${b.level ?? "–"} of 5, counted up to the first tier not met`}>
      <Table name="branch-tiers" caption="Branch protection tiers" search={false} rows={b.tiers || []} columns={[
        { key: "tier", label: "Tier", num: true },
        { key: "rule", label: "Rule", primary: true },
        { key: "state", label: "State", filter: true, render: (x: R) => { const [tone, word] = TIER[x.state] || ["neutral", x.state]; return <Pill tone={tone}>{word}</Pill>; } }]} />
      <p class="blk-note">{b.readable ? "Read from rulesets and the branch's public summary; a tier that needs an admin token to read says can't read, never met."
        : "Nothing about protection was readable with this token. Rulesets are readable by anyone with read access; classic protection needs an admin token."}</p>
    </Framed>

    <Framed title="What the repo holds" note={`${w.files ?? 0} workflow files read`}>
      <Table name="security-facts" caption="Security facts" search={false} rows={[
        { what: "Committed binaries", has: (t.binaries || []).length ? <Pill tone="bad">{(t.binaries || []).length} found</Pill> : <Pill tone="good">none</Pill>, detail: list(t.binaries),
          note: "By file name (Scorecard's list) and, for executable files with no extension, by reading their first bytes." },
        { what: "SBOM files", has: yes((t.sbom_files || []).length || (rel.sbom || []).length ? true : false), detail: <>{list(t.sbom_files)}{(rel.sbom || []).length ? `; attached to ${rel.sbom.join(", ")}` : ""}</> },
        { what: "Fuzzing", has: yes(Boolean((t.fuzzing || []).length || f.oss_fuzz)), detail: <>{list(t.fuzzing)}{f.oss_fuzz ? "; listed in OSS-Fuzz" : ""}</> },
        { what: "Security policy", has: yes(Boolean(p.file)), detail: p.file ? <span class="mono-soft">{p.file.replace(`${repo}:`, "")}</span> : <span class="muted">no SECURITY.md here or in the owner's .github repo</span> },
        { what: "Policy names a contact", has: p.file ? yes(p.contact) : <span class="muted">–</span>, detail: "An email address, a link or GitHub's security advisories" },
        { what: "Policy says how disclosure works", has: p.file ? yes(p.disclosure) : <span class="muted">–</span>, detail: "Words about reporting, vulnerabilities or a timeline" },
        { what: "Private vulnerability reporting", has: yes(p.private_reporting, "on", "off"), detail: "GitHub's Report a vulnerability button" },
        { what: "Signed releases", has: rel.releases ? yes((rel.signed || []).length > 0) : <span class="muted">no releases</span>,
          detail: rel.releases ? `${(rel.signed || []).length} of the last ${rel.releases} carry a signature or provenance file${(rel.signed || []).length ? ` (${rel.signed.join(", ")})` : ""}` : "–" },
        { what: "Code scanning on pull requests", has: yes((w.sast || []).length > 0), detail: list(w.sast) },
        { what: "Published by a workflow", has: yes((w.publish || []).length > 0), detail: list(w.publish) },
        { what: "OpenSSF Best Practices badge", has: f.badge ? <Pill tone="good">{f.badge}</Pill> : <Pill tone="neutral">none</Pill>, detail: "From bestpractices.dev" },
      ]} columns={[
        { key: "what", label: "Check", primary: true, render: (x: R) => <>{x.what}{x.note ? <div class="muted small">{x.note}</div> : null}</> },
        { key: "has", label: "Found", raw: () => "", render: (x: R) => x.has },
        { key: "detail", label: "Where", raw: () => "", render: (x: R) => x.detail }]} />
    </Framed>
  </>;
}
