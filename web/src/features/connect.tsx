// Connecting GitHub: Sign in (when a relay is set up) or a fine-grained token made on GitHub's prefilled page and pasted here.
import { useEffect, useState } from "preact/hooks";
import type { AppJson } from "../data/types";
import { store, useStore } from "../data/store";
import { authConfig } from "../github/config";
import { TOKEN_RE, inspect, kindOf, tokenPageUrl, type Inspection } from "../github/caps";
import { makeApi } from "../github/client";
import { authorizeUrl } from "../github/oauth";
import { account, canRemember, saveAccount, signOut } from "../github/token";
// Loaded for its sign-out hook: every repo entry drops its token too.
import "../github/session";
import { Button } from "../ui/Button";
import { Field, Toggle } from "../ui/controls";
import { Icon } from "../ui/icons";
import { Card } from "../ui/Page";
import { Pill, toast } from "../ui/bits";
import css from "./connect.css" with { type: "text" };

// These styles travel with this lazy code, so they never weigh on the first screen's stylesheet.
if (!document.getElementById("sv-connect-css")) document.head.appendChild(Object.assign(document.createElement("style"), { id: "sv-connect-css", textContent: css }));

export function Avatar({ src, size = 36 }: { src?: string; size?: number }) {
  return src ? <img class="gh-avatar" src={src.includes("?") ? src : `${src}?s=${size * 2}`} alt="" width={size} height={size} /> : <span class="gh-avatar" style={{ width: `${size}px`, height: `${size}px` }}><Icon name="lock" /></span>;
}

// What the token can do, each permission named in plain words; missing ones come with a button that makes a new token.
export function Abilities({ info }: { info: Inspection }) {
  return <div class="abilities">
    {info.repos === 0 ? <div class="note note-bad" role="alert"><Icon name="warn" /><span>This token reaches no repos. On GitHub's page, under
      <b> Repository access</b>, choose <b>Only select repositories</b> and pick yours.</span></div> : null}
    <ul class="ability-list" aria-label="What the token can do">
      {info.checks.map((c) => <li class={c.ok === false ? "is-missing" : ""}>
        <Icon name={c.ok === false ? "warn" : c.ok ? "check" : "dot"} /><span>{c.says}</span>
        {c.ok === false ? <Pill tone="bad" icon={null}>missing</Pill> : c.ok === null ? <Pill tone="neutral" icon={null}>checked at setup</Pill> : null}
      </li>)}
    </ul>
    {info.missing.length ? <div class="note note-watch"><Icon name="warn" />
      <span>Missing: {info.missing.map((m) => m.says.toLowerCase()).join("; ")}. Make a new token with everything ticked and paste it here.
        <span class="note-act"><Button size="sm" variant="tinted" href={tokenPageUrl()} external iconEnd="external">Make a new token</Button></span></span></div> : null}
  </div>;
}

// The last token check, so a page that swaps the form for the repo list can still say what's missing.
export const lastCheck = store<Inspection | null>(null);

// Checks a pasted token with api.github.com, then saves the account; both designs' Connect forms use it.
export function useTokenCheck(remember: boolean, onConnected?: () => void) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<Inspection | null>(null);
  const check = async (raw: string) => {
    const tok = raw.match(TOKEN_RE)?.[1];
    if (!tok) { setErr("That doesn't look like a GitHub token. It starts with github_pat_ (or ghp_ for a classic one)."); return; }
    setBusy(true); setErr(null); setInfo(null);
    try {
      const got = await inspect(makeApi(tok), tok);
      setInfo(got);
      lastCheck.set(got);
      saveAccount({ token: tok, kind: kindOf(tok), login: got.login, avatar: got.avatar, ...(got.name ? { name: got.name } : {}), remember });
      setText("");
      toast(`Connected as ${got.login}`);
      if (!got.missing.length && got.repos !== 0) onConnected?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The check failed.");
    }
    setBusy(false);
  };
  // A pasted token is checked at once.
  const onInput = (v: string) => { setText(v); setErr(null); const t = v.trim(); if (t && t.match(TOKEN_RE)?.[1] === t) void check(t); };
  return { text, busy, err, setErr, info, setInfo, check, onInput };
}
export function TokenWarnings() {
  const info = useStore(lastCheck), a = useStore(account);
  return info && a && a.login === info.login && (info.missing.length || info.repos === 0) ? <Abilities info={info} /> : null;
}

export function AccountBar({ compact }: { compact?: boolean }) {
  const a = useStore(account);
  if (!a) return null;
  return <div class={"account-bar" + (compact ? " is-compact" : "")}>
    <Avatar src={a.avatar} size={compact ? 28 : 36} />
    <span class="account-text"><b>{a.login || "Connected"}</b><small>{a.kind === "app" ? "Signed in with GitHub" : a.kind === "fine" ? "Fine-grained token" : "Classic token"}
      {a.remember ? ", remembered on this device" : ", this tab only"}</small></span>
    <Button size="sm" variant="plain" onClick={() => { signOut(); toast("Signed out of GitHub", "neutral"); location.reload(); }}>Sign out</Button>
  </div>;
}

export function ConnectPanel({ app, onConnected }: { app?: AppJson | null; onConnected?: () => void }) {
  const cfg = authConfig(app);
  const [remember, setRemember] = useState(false);
  const { text, busy, err, info, setInfo, check, onInput } = useTokenCheck(remember, onConnected);

  const signIn = async () => { if (cfg) location.assign(await authorizeUrl(cfg, remember && canRemember(), location.hash || "#/")); };
  const a = useStore(account);
  useEffect(() => { if (!a) setInfo(null); }, [a]);

  return <div class="connect">
    {cfg ? <><Button variant="filled" size="lg" wide icon="link" onClick={signIn}>Sign in with GitHub</Button>
      <p class="connect-or"><span>or use a token</span></p></> : null}
    <ol class="connect-steps">
      <li><span class="step-n" aria-hidden="true">1</span><div>
        <b>Make a token on GitHub</b>
        <p>The page opens with the name, a 90-day expiry and the permissions filled in.</p>
        <Button variant={cfg ? "tinted" : "filled"} href={tokenPageUrl()} external iconEnd="external">Open GitHub's token page</Button>
        <figure class="pick-hint" aria-label="On GitHub's page: Repository access, Only select repositories, then pick yours">
          <span class="pick-hint-tag" aria-hidden="true">What GitHub's page looks like</span>
          <div class="pick-hint-row"><span class="radio" /><span>All repositories</span></div>
          <div class="pick-hint-row is-on"><span class="radio is-on" /><span>Only select repositories</span><span class="pick-hint-chip" aria-hidden="true"><Icon name="check" />owner/repo</span></div>
          <figcaption>On GitHub's page, under <b>Repository access</b>, pick the repos; GitHub can't fill that in. Then <b>Generate token</b> and copy it.</figcaption>
        </figure>
      </div></li>
      <li><span class="step-n" aria-hidden="true">2</span><div>
        <Field label="Paste it here" error={err} hint="Checked as soon as you paste. It goes only to api.github.com and stays in this browser.">
          {(id) => <input id={id} class="input mono" type="password" autoComplete="off" spellcheck={false} placeholder="github_pat_…" value={text}
            onInput={(e) => onInput(e.currentTarget.value)} onKeyDown={(e) => { if (e.key === "Enter") void check(text); }} />}
        </Field>
        <div class="connect-row">
          {canRemember() ? <label class="remember"><Toggle checked={remember} onChange={setRemember} labelledBy="remember-l" /><span id="remember-l">Remember on this device</span></label>
            : <small class="remember">Kept for this tab only: other sites under {location.hostname} could read a remembered token. Use a custom domain or <code>stackvitals ui</code> to remember it.</small>}
          <Button variant="tinted" loading={busy} disabled={!text.trim()} onClick={() => check(text)}>Check token</Button>
        </div>
      </div></li>
    </ol>
    {info && a ? <Card class="connect-result">
      <div class="account-bar"><Avatar src={info.avatar} /><span class="account-text"><b>{info.login}</b>
        <small>{info.repos === null ? "Classic token: every repo you can reach" : `${info.repos}${info.repos === 100 ? "+" : ""} repo${info.repos === 1 ? "" : "s"} picked`}</small></span>
        {info.missing.length ? <Pill tone="watch">Needs more</Pill> : <Pill tone="good">Ready</Pill>}</div>
      <Abilities info={info} />
      {onConnected ? <Button variant="filled" wide onClick={onConnected}>Continue</Button> : null}
    </Card> : null}
  </div>;
}
