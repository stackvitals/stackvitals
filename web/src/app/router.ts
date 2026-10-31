// Hash routes: #/ci, #/ci/test/<id>, #/settings/alerts?x=1. Back and forward work through the browser history.
import { store } from "../data/store";

export interface Route { page: string; rest: string[]; query: URLSearchParams; path: string }

export function parse(hash: string): Route {
  const raw = (hash || "#/").replace(/^#/, "");
  const [path = "", query = ""] = raw.split("?");
  // A mistyped % in a link keeps the text as it is instead of breaking the page.
  const decode = (x: string) => { try { return decodeURIComponent(x); } catch { return x; } };
  const parts = path.split("/").filter(Boolean).map(decode);
  const first = parts[0] || "", moved = OLD_ROUTES[first];
  return { page: moved || first || "overview", rest: parts.slice(1), query: new URLSearchParams(query), path: moved ? path.replace(first, moved) : path };
}

// Links from the earlier app (printable pages, chat messages, bookmarks) still open the right page.
export const OLD_ROUTES: Record<string, string> = { home: "overview", integrations: "connections" };

export const route = store<Route>(parse(location.hash));

addEventListener("hashchange", () => {
  const prev = route.get(), next = parse(location.hash);
  route.set(next);
  // A new page starts at the top; a tab or filter change on the same page keeps the scroll.
  if (prev.page !== next.page || prev.rest.join("/") !== next.rest.join("/")) scrollTo({ top: 0 });
});

export function href(page: string, ...rest: string[]): string {
  return "#/" + [page === "overview" ? "" : page, ...rest.map(encodeURIComponent)].filter((x, i) => i > 0 || x).join("/");
}

export function navigate(to: string): void {
  location.hash = to.replace(/^#/, "");
}

// Same page, new query (a tab): history keeps it, so back returns to the previous tab.
export function withQuery(r: Route, key: string, value: string | null): string {
  const q = new URLSearchParams(r.query);
  if (value === null) q.delete(key); else q.set(key, value);
  const s = q.toString();
  return "#/" + r.path.replace(/^\//, "") + (s ? "?" + s : "");
}
