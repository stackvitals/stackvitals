// Welcome: shown where no repo's data sits beside the page. Connect GitHub, try the demo, or open a public repo by name.
import { useEffect, useState } from "preact/hooks";
import { entryFor, repos, type RepoEntry } from "../data/repos";
import { prefs, useStore } from "../data/store";
import { authConfig } from "../github/config";
import { finishSignIn } from "../github/oauth";
import { lookup, openByName, openEntry, openSetup, parseRepo, type Lookup } from "../github/open";
import { account, saveAccount, type Account } from "../github/token";
import { makeApi } from "../github/client";
import { toast } from "../ui/bits";
import WelcomeSheet from "./welcome-sheet";

// Opening a public repo by name; welcome-sheet.tsx draws the form around it.
export function useByName() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [found, setFound] = useState<{ repo: string; res: Lookup } | null>(null);
  const go = async (e?: Event) => {
    e?.preventDefault();
    const repo = parseRepo(text);
    if (!repo) { setErr("Type it as owner/repo, for example vitejs/vite."); return; }
    setBusy(true); setErr(null); setFound(null);
    const res = await lookup(repo);
    setBusy(false);
    if (res.kind === "data") { openEntry(entryFor(res.source, res.app.repo)); toast(`Opened ${res.app.repo}`); return; }
    setFound({ repo, res });
  };
  const edit = (v: string) => { setText(v); setErr(null); setFound(null); };
  return { text, edit, busy, err, found, go };
}

// What the Welcome screen shows: the GitHub account, a sign-in in progress, and repos opened before.
export interface WelcomeState { a: Account | null; signing: string | null; known: RepoEntry[] }
export const pickRepo = (r: { full_name: string; private: boolean }, s: string) => (s === "data" ? openByName(r.full_name, r.private) : openSetup(r.full_name, r.private));

export default function Welcome() {
  const a = useStore(account);
  const [signing, setSigning] = useState<string | null>(null);
  const known = useStore(repos).filter((e) => e.id !== "here" && !e.demo);
  const forced = new URLSearchParams(location.search).has("welcome");

  useEffect(() => {
    // Back from GitHub's sign-in page: finish through the relay, then fetch who signed in.
    const cfg = authConfig();
    if (!cfg || !new URLSearchParams(location.search).has("code")) {
      // A returning visitor with a saved token goes straight to the last repo.
      const last = known.find((e) => e.id === prefs.get<string>("last", "")) || known[known.length - 1];
      if (a && last && !forced) openEntry(last);
      return;
    }
    setSigning("Finishing sign-in…");
    finishSignIn(cfg).then(async (done) => {
      if (!done) { setSigning(null); return; }
      const me = await makeApi(done.account.token).get<any>("/user");
      saveAccount({ ...done.account, login: me?.login, avatar: me?.avatar_url });
      toast(`Signed in as ${me?.login || "you"}`);
      setSigning(null);
    }, (e) => { setSigning(e instanceof Error ? e.message : "Sign-in failed."); });
  }, []);

  return <WelcomeSheet a={a} signing={signing} known={known} />;
}
