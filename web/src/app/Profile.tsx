// The repo switcher in the top bar: the repos you follow, adding one, the demo, and appearance.
import { useEffect, useRef, useState } from "preact/hooks";
import { refresh } from "../data/files";
import { current, demoMode, forgetRepo, openRepo, repos, type RepoEntry } from "../data/repos";
import { describe } from "../data/source";
import { useStore } from "../data/store";
import { calm, setCalm, setTheme, theme, type Theme } from "../data/theme";
import { toast } from "../ui/bits";
import { SegmentedControl, Toggle } from "../ui/controls";
import { Icon } from "../ui/icons";
import { Menu, MenuItem, MenuLabel, MenuSep, Popover } from "../ui/Popover";
import { account, signOut } from "../github/token";

const HUES = [212, 152, 32, 280, 350, 190, 100, 0];
export function RepoAvatar({ label, size = 28 }: { label: string; size?: number }) {
  const name = label.split("/").pop() || label;
  let h = 0;
  for (const c of label) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return <span class="repo-av" aria-hidden="true" style={{ width: `${size}px`, height: `${size}px`, fontSize: `${Math.round(size * 0.46)}px`, ["--hue" as string]: String(HUES[h % HUES.length]) }}>
    {name.replace(/[^A-Za-z0-9]/g, "")[0]?.toUpperCase() || "?"}</span>;
}

// Theme and reduce motion, in the repo menu, Settings and the Welcome screen.
export function Appearance() {
  const t = useStore(theme), still = useStore(calm);
  return <div class="appearance">
    <div class="pref-row"><span id="pref-theme">Theme</span>
      <SegmentedControl<Theme> size="sm" label="Theme" value={t} onChange={setTheme}
        options={[{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} /></div>
    <div class="pref-row"><span id="pref-calm">Reduce motion</span><Toggle checked={still} onChange={setCalm} labelledBy="pref-calm" /></div>
  </div>;
}

// The add-a-repo sheet loads the first time it opens.
let addMod: Promise<typeof import("./AddRepo")> | null = null;
function LazyAddRepo({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [M, setM] = useState<typeof import("./AddRepo") | null>(null);
  useEffect(() => { if (open && !M) (addMod ||= import("./AddRepo")).then(setM); }, [open]);
  return M ? <M.AddRepoSheet open={open} onClose={onClose} /> : null;
}

export function Profile() {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const list = useStore(repos), cur = useStore(current), gh = useStore(account);
  const pick = (e: RepoEntry) => { setOpen(false); if (e.id !== cur.id) { openRepo(e); toast(`Showing ${e.label}`, "neutral"); } };
  return <>
    <button ref={btn} type="button" class="profile press" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}
      aria-label={`Repository ${cur.label}. Switch repository or change appearance`}>
      <RepoAvatar label={cur.label} /><span class="profile-name">{cur.label}</span><Icon name="chev" class="profile-chev" />
    </button>
    <Popover open={open} onClose={() => setOpen(false)} anchor={btn} label="Repositories and appearance" width={360} sheetOnPhone>
      <Menu label="Repositories">
        <MenuLabel>{demoMode ? "Demo repositories" : "Your repositories"}</MenuLabel>
        {list.map((e) => <MenuItem leading={<RepoAvatar label={e.label} size={34} />} title={e.label} subtitle={e.demo ? "Example repo with demo data" : describe(e.source)}
          checked={e.id === cur.id} onSelect={() => pick(e)} />)}
        <MenuSep />
        {!demoMode ? <MenuItem icon="plus" title="Add a repository" subtitle="By name or Pages address" onSelect={() => { setOpen(false); setAdding(true); }} /> : null}
        {!demoMode ? <MenuItem icon="link" title={gh ? "Your GitHub repos" : "Connect GitHub"} subtitle={gh ? `Signed in as ${gh.login || "you"}; set up in a few clicks` : "Open private repos and set up in a few clicks once GitHub is connected"}
          onSelect={() => { setOpen(false); location.hash = "#/setup?pick=1"; }} /> : null}
        {gh ? <MenuItem icon="left" title="Sign out of GitHub" subtitle="Forgets the token in this browser" onSelect={() => { setOpen(false); signOut(); location.reload(); }} /> : null}
        <MenuItem icon="refresh" title="Reload the data" subtitle="Fetch every file again" onSelect={() => { refresh(); setOpen(false); toast("Data reloaded"); }} />
        {demoMode ? <MenuItem icon="left" title="Leave the demo" onSelect={() => { location.href = location.pathname; }} />
          : <MenuItem icon="play" title="Try the demo" subtitle="Three example repos with full data" onSelect={() => { location.href = location.pathname + "?demo=1"; }} />}
        {!demoMode && cur.id !== "here" ? <MenuItem icon="trash" title={`Forget ${cur.label}`} danger onSelect={() => { setOpen(false); forgetRepo(cur.id); toast("Removed from your list", "neutral"); }} /> : null}
      </Menu>
      <MenuSep />
      <Appearance />
    </Popover>
    <LazyAddRepo open={adding} onClose={() => setAdding(false)} />
  </>;
}
