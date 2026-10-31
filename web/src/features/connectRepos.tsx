// The connected account's repos, grouped by owner and searchable, each marked set up or not (checked only when it scrolls into view).
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { RepoAvatar } from "../app/Profile";
import { useStore } from "../data/store";
import { makeApi } from "../github/client";
import { groupRepos, limiter, myRepos, setupState, type GhRepo, type SetupState } from "../github/mine";
import { account } from "../github/token";
import { Icon } from "../ui/icons";
import { EmptyState, Pill, Skeleton } from "../ui/bits";
import { Button } from "../ui/Button";

const lists = new Map<string, Promise<GhRepo[]>>();
const queue = limiter(4);

function StatusPill({ s }: { s: SetupState | undefined | "error" }) {
  if (s === undefined) return <span class="checking" aria-label="Checking"><span class="spin" aria-hidden="true" /></span>;
  if (s === "data") return <Pill tone="good">Set up</Pill>;
  if (s === "workflow") return <Pill tone="watch">Set up, first run pending</Pill>;
  if (s === "error") return <Pill tone="neutral" icon={null}>Couldn't check</Pill>;
  return <Pill tone="neutral" icon={null}>Not set up</Pill>;
}

function Row({ r, token, onPick }: { r: GhRepo; token: string; onPick: (r: GhRepo, s: SetupState) => void }) {
  const el = useRef<HTMLLIElement>(null);
  const [s, setS] = useState<SetupState | undefined | "error">(undefined);
  useEffect(() => {
    const node = el.current;
    if (!node) return;
    let live = true;
    const go = () => queue(() => setupState(makeApi(token), r.full_name)).then((x) => live && setS(x), () => live && setS("error"));
    if (typeof IntersectionObserver !== "function") { go(); return () => { live = false; }; }
    const io = new IntersectionObserver(([e]) => { if (e?.isIntersecting) { io.disconnect(); go(); } }, { rootMargin: "120px" });
    io.observe(node);
    return () => { live = false; io.disconnect(); };
  }, [r.full_name, token]);
  return <li class="glist-item" ref={el}>
    <button type="button" class="row row-action press" onClick={() => onPick(r, s === "data" || s === "workflow" ? s : "none")}>
      <span class="row-lead"><RepoAvatar label={r.full_name} size={32} /></span>
      <span class="row-text"><span class="row-title">{r.name}{r.private ? <Icon name="lock" class="repo-lock" /> : null}</span>
        {r.description ? <span class="row-sub">{r.description}</span> : null}</span>
      <span class="row-trail"><StatusPill s={s} /></span>
      <Icon name="right" class="row-chev" />
    </button>
  </li>;
}

export function RepoPicker({ onPick }: { onPick: (r: GhRepo, s: SetupState) => void }) {
  const a = useStore(account);
  const [list, setList] = useState<GhRepo[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!a) return;
    let live = true;
    if (!lists.has(a.token)) lists.set(a.token, myRepos(makeApi(a.token)));
    lists.get(a.token)!.then((l) => live && setList(l), (e) => { lists.delete(a.token); if (live) setErr(e instanceof Error ? e.message : "Couldn't list your repos."); });
    return () => { live = false; };
  }, [a?.token, tick]);
  const groups = useMemo(() => groupRepos((list || []).filter((r) => !r.archived), q, a?.login), [list, q, a?.login]);
  if (!a) return null;
  if (err) return <EmptyState icon="warn" title="Couldn't list your repos." action={<Button onClick={() => { setErr(null); setTick((n) => n + 1); }}>Try again</Button>}>{err}</EmptyState>;
  if (!list) return <Skeleton lines={5} />;
  if (!list.length) return <EmptyState icon="search" title="This token reaches no repos.">On GitHub's token page, under Repository access, pick the repos, then paste the new token.</EmptyState>;
  return <div class="picker">
    <div class="search-field"><Icon name="search" /><input class="input" type="search" placeholder={`Search ${list.length} repos`} aria-label="Search your repos"
      value={q} onInput={(e) => setQ(e.currentTarget.value)} /></div>
    {groups.length ? groups.map(([owner, items]) => <div class="picker-group">
      <h3 class="picker-owner">{owner}<span class="num">{items.length}</span></h3>
      <ul class="glist card" aria-label={`${owner}'s repos`}>{items.map((r) => <Row key={r.full_name} r={r} token={a.token} onPick={onPick} />)}</ul>
    </div>) : <p class="picker-none">No repo matches “{q}”.</p>}
  </div>;
}
