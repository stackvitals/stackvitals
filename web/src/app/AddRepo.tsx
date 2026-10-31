// Adding a repo by name or Pages address, with an optional token for a private one.
import { useState } from "preact/hooks";
import { json } from "../data/files";
import { entryFor, openRepo } from "../data/repos";
import { parseSource } from "../data/source";
import type { AppJson } from "../data/types";
import { toast } from "../ui/bits";
import { Button } from "../ui/Button";
import { Field, TextInput } from "../ui/controls";
import { Sheet } from "../ui/Sheet";

export function AddRepoSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [text, setText] = useState("");
  const [tok, setTok] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e?: Event) => {
    e?.preventDefault();
    const src = parseSource(text, tok || undefined);
    if (!src) { setErr("Type owner/repo, a github.com link, or the address of a StackVitals Pages site."); return; }
    setBusy(true); setErr(null);
    const app = await json<AppJson>("app.json", src);
    setBusy(false);
    if (!app) {
      setErr(src.kind === "branch" ? (tok ? "No StackVitals data found: check the name and that the token can read this repo's contents."
        : "No public StackVitals data found. If the repo is private, add a token that can read its contents.")
        : "No StackVitals app.json at that address.");
      return;
    }
    const entry = entryFor(src, app.repo);
    openRepo(entry);
    toast(`Opened ${app.repo}`);
    setText(""); setTok("");
    onClose();
  };
  const isBranch = parseSource(text)?.kind === "branch";
  return <Sheet open={open} onClose={onClose} title="Add a repository" description="Open any repo that runs StackVitals: its data branch, or its Pages site."
    footer={<><Button variant="plain" onClick={onClose}>Cancel</Button><Button variant="filled" loading={busy} onClick={() => submit()}>Open</Button></>}>
    <form class="form" onSubmit={submit}>
      <Field label="Repository or Pages address" error={err} hint="For example octo-org/octo-repo, or https://owner.github.io/repo/">
        {(id) => <TextInput id={id} value={text} onInput={(v) => { setText(v); setErr(null); }} placeholder="owner/repo" autoFocus />}
      </Field>
      {isBranch ? <Field label="Token for a private repo (optional)" hint={<>A fine-grained token with Contents: read on this repo. It stays in this tab only and goes only to api.github.com.</>}>
        {(id) => <TextInput id={id} type="password" mono value={tok} onInput={setTok} placeholder="github_pat_…" />}
      </Field> : null}
      <button type="submit" hidden />
    </form>
  </Sheet>;
}

