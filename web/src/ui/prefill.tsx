// Buttons that open a prefilled GitHub link (github/links.ts): the click handler and the note for the paste path.
import { PASTE_FILE, PASTE_FILE_BEFORE, PASTE_ISSUE, PASTE_ISSUE_BEFORE, type PrefillLink } from "../github/links";
import { copyText, toast } from "./bits";

// The click on a prefilled GitHub link: when the content didn't fit, copies it first so it can be pasted in GitHub's editor.
export function onPrefill(link: PrefillLink, opened: string): () => void {
  return () => {
    if (!link.paste) { toast(opened); return; }
    void copyText(link.paste).then((ok) => toast(ok ? (link.kind === "file" ? PASTE_FILE : PASTE_ISSUE)
      : link.kind === "file" ? "Copy failed: use Copy the file on this page, then paste it into GitHub's editor." : "Copy failed: try again, or apply it with a token.", ok ? "good" : "bad"));
  };
}

// What a paste-path link does, said before the click.
export function PasteNote({ link }: { link: PrefillLink | null }) {
  return link?.paste ? <p class="field-hint paste-note">{link.kind === "file" ? PASTE_FILE_BEFORE : PASTE_ISSUE_BEFORE}</p> : null;
}

