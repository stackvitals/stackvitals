// Appearance: theme (light by default, dark when chosen) and reduced motion, remembered per viewer.
import { prefs, store } from "./store";

export type Theme = "light" | "dark";
// Light unless the viewer picked dark; the system setting is not followed (an old "system" choice reads as light).
export const theme = store<Theme>(prefs.get<string>("theme", "light") === "dark" ? "dark" : "light");
export const calm = store<boolean>(prefs.get("calm", false));
// Bumps whenever colours change, so canvas charts redraw with the new tokens.
export const paint = store(0);

export function setTheme(t: Theme): void {
  theme.set(t);
  prefs.set("theme", t);
  const root = document.documentElement;
  root.classList.add("is-theming");
  root.dataset.theme = t;
  setTimeout(() => root.classList.remove("is-theming"), 400);
  requestAnimationFrame(() => paint.set((n) => n + 1));
}

export function setCalm(on: boolean): void {
  calm.set(on);
  prefs.set("calm", on);
  document.documentElement.classList.toggle("calm", on);
}

if (typeof matchMedia === "function") {
  for (const q of ["(prefers-color-scheme: dark)", "(prefers-contrast: more)"]) {
    matchMedia(q).addEventListener("change", () => paint.set((n) => n + 1));
  }
}

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
