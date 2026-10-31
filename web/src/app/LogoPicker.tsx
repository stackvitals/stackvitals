// The brand in the sidebar and top bar: the cube, with the name beside it in the sidebar.
import { LogoMark } from "../brand/Logo";

export function LogoButton({ withName }: { withName?: boolean }) {
  return <span class="brand"><LogoMark />{withName ? <span class="brand-name">StackVitals</span> : null}</span>;
}
