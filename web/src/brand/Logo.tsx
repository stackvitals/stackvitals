// The StackVitals cube; the image ships beside the app's scripts.
export const CUBE = "app/brand/cube-128.png";

export function LogoMark({ size = 30 }: { size?: number }) {
  return <img class="logo-mark" src={CUBE} width={size} height={size} alt="" aria-hidden="true" />;
}
