// "What's behind this number": the pull requests, deployments and incidents a DORA measure was computed from, each linked.
import { useState } from "preact/hooks";
import { count, day, hours } from "../data/format";
import { Button } from "../ui/Button";
import { GroupedList, ListRow } from "../ui/Page";
import { Sheet } from "../ui/Sheet";

type Row = (string | number | null)[];
export interface DoraEvidence {
  deployments?: Row[]; lead_time?: Row[]; lead_time_total?: number; failed?: Row[]; recovery?: Row[];
  not_first_try?: (string | number[] | null)[][]; not_first_try_total?: number; phase?: Row[];
}
export type EvidenceKind = "deployments" | "lead_time" | "failed" | "recovery" | "not_first_try" | "phase";

const TITLES: Record<EvidenceKind, string> = {
  deployments: "Deployments counted", lead_time: "Pull requests behind the lead time",
  failed: "Deployments that failed", recovery: "Recoveries counted", not_first_try: "Pushes not green on the first try", phase: "Pull requests in this phase",
};
const WHY: Record<EvidenceKind, string> = {
  deployments: "Every deployment in the window, oldest first. Deployment frequency counts the days these landed on.",
  lead_time: "Each deployed pull request with its time from first commit to deployment, longest first. The lead time is their median.",
  failed: "Each deployment tied to an incident after it (a revert, a hotfix or an incident issue). The fail rate is these over all deployments.",
  recovery: "Each failed deployment and how long until its incident was resolved. Recovery is their median.",
  not_first_try: "Each push whose checks failed or needed a re-run, newest first, with the runs that did. The first-try share is the other pushes over all of them.",
  phase: "Each merged pull request's hours in this phase, longest first (up to 200). The P50 and P75 are read from these.",
};

// Reverts and hotfixes are pull requests, incident issues are issues; pager incidents have no GitHub link.
const incidentHref = (repo: string, source: unknown, n: unknown) =>
  !n ? undefined : source === "issue" ? `https://github.com/${repo}/issues/${n}` : source === "revert" || source === "hotfix" ? `https://github.com/${repo}/pull/${n}` : undefined;
const commitHref = (repo: string, sha: unknown) => (sha ? `https://github.com/${repo}/commit/${sha}` : undefined);
const mins = (m: unknown) => (typeof m === "number" ? hours(m / 60) : "–");

export function EvidenceLink({ kind, ev, repo }: { kind: EvidenceKind; ev?: DoraEvidence; repo?: string | null }) {
  const [open, setOpen] = useState(false);
  const rows = (ev?.[kind] || []) as Row[];
  if (!rows.length || !repo) return null;
  const total = kind === "lead_time" ? ev?.lead_time_total ?? rows.length : kind === "not_first_try" ? ev?.not_first_try_total ?? rows.length : rows.length;
  return <>
    <Button size="sm" variant="plain" onClick={() => setOpen(true)}>Show the {count(total, kind === "lead_time" ? "pull request" : kind === "recovery" ? "recovery" : kind === "not_first_try" ? "push" : kind === "phase" ? "pull request" : "deployment")}</Button>
    <Sheet open={open} onClose={() => setOpen(false)} title={TITLES[kind]} description={WHY[kind]}>
      {total > rows.length ? <p class="mute small">Showing the first {rows.length} of {total}.</p> : null}
      <GroupedList label={TITLES[kind]}>
        {rows.map((r) => kind === "deployments" ? <ListRow title={day(String(r[1]))} subtitle={`Commit ${r[0]}`} href={commitHref(repo, r[0])} external />
          : kind === "not_first_try" ? <ListRow title={`Commit ${r[0]}`} subtitle={`${r[1] || "?"}: ${count((r[2] as unknown as number[]).length, "run")} failed or re-run`} href={(r[2] as unknown as number[]).length ? `https://github.com/${repo}/actions/runs/${(r[2] as unknown as number[])[0]}` : commitHref(repo, r[0])} external />
          : kind === "phase" ? <ListRow title={`#${r[0]}`} trailing={mins(Number(r[1]) * 60)} href={`https://github.com/${repo}/pull/${r[0]}`} external />
          : kind === "lead_time" ? <ListRow title={`#${r[0]}`} subtitle={`Shipped in ${r[1]}`} trailing={mins(r[2])} href={`https://github.com/${repo}/pull/${r[0]}`} external />
          : kind === "failed" ? <ListRow title={`Deployment ${r[0]}`} subtitle={`${r[1]}${r[2] ? ` #${r[2]}` : ""}`} href={incidentHref(repo, r[1], r[2]) || commitHref(repo, r[0])} external />
          : <ListRow title={`Deployment ${r[0]}`} subtitle={`${r[1]}${r[2] ? ` #${r[2]}` : ""}`} trailing={mins(r[3])} href={incidentHref(repo, r[1], r[2]) || commitHref(repo, r[0])} external />)}
      </GroupedList>
    </Sheet>
  </>;
}
