// The chosen mark, drawn with theme colours; it cross-fades when the choice changes.
import { useStore } from "../data/store";
import { logo } from "../data/theme";
import { logoSvg, type LogoDef } from "./mark";

export function LogoMark({ def, size = 30 }: { def?: LogoDef; size?: number }) {
  const chosen = useStore(logo);
  const d = def || chosen;
  return <span class="logo-mark" key={d.id} style={{ width: `${size}px`, height: `${size}px` }} aria-hidden="true"
    dangerouslySetInnerHTML={{ __html: logoSvg(d) }} />;
}
