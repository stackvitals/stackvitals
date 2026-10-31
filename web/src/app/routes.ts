// Every page of the app: its route, label, icon, sidebar group, the module it reads and its lazily loaded code.
import type { FunctionComponent } from "preact";
import type { AppJson } from "../data/types";
import type { IconName } from "../ui/icons";
import type { Route } from "./router";

export interface PageProps { app: AppJson | null; route: Route }
type Loader = () => Promise<{ default: FunctionComponent<PageProps> }>;

export interface RouteDef {
  // module: the app.json module(s) the page reads; any one of "a|b" counts as set up.
  id: string; label: string; short?: string; icon: IconName; group: string; module?: string; load: Loader;
  badge?: (app: AppJson | null) => { n: number; tone: "bad" | "watch" | "accent"; label: string } | null;
}

const fact = (app: AppJson | null, k: string) => (app?.facts?.[k] ?? 0) as number;

export const ROUTES: RouteDef[] = [
  { id: "overview", label: "Overview", icon: "overview", group: "Health", load: () => import("../pages/overview") },
  { id: "insights", label: "Insights", icon: "insights", group: "Health", module: "insights", load: () => import("../pages/insights"),
    badge: (a) => fact(a, "findings") ? { n: fact(a, "findings"), tone: "accent", label: "findings to fix" } : null },
  { id: "ci", label: "CI Health", short: "CI", icon: "ci", group: "Health", module: "ci", load: () => import("../pages/ci"),
    badge: (a) => fact(a, "ci_flaky") + fact(a, "ci_broken") ? { n: fact(a, "ci_flaky") + fact(a, "ci_broken"), tone: "bad", label: "flaky or failing" } : null },
  { id: "prs", label: "Pull Requests", short: "PRs", icon: "prs", group: "Health", module: "flow", load: () => import("../pages/prs"),
    badge: (a) => fact(a, "stale_prs") ? { n: fact(a, "stale_prs"), tone: "watch", label: "stale" } : null },
  { id: "delivery", label: "Delivery", icon: "delivery", group: "Health", module: "delivery", load: () => import("../pages/delivery") },
  { id: "community", label: "Community", icon: "community", group: "Health", module: "community", load: () => import("../pages/community"),
    badge: (a) => fact(a, "newcomers_waiting") ? { n: fact(a, "newcomers_waiting"), tone: "watch", label: "newcomers waiting" } : null },
  { id: "deps", label: "Dependencies", short: "Deps", icon: "deps", group: "Health", module: "deps|vulns|supply", load: () => import("../pages/deps"),
    badge: (a) => fact(a, "vulns_serious") ? { n: fact(a, "vulns_serious"), tone: "bad", label: "serious alerts" } : null },
  { id: "investment", label: "Investment", short: "Invest", icon: "investment", group: "Organisation", module: "delivery", load: () => import("../pages/investment") },
  { id: "portal", label: "Portal", icon: "portal", group: "Organisation", module: "portal", load: () => import("../pages/portal") },
  { id: "standing", label: "Where you stand", short: "Standing", icon: "insights", group: "Organisation", load: () => import("../pages/standing") },
  { id: "explore", label: "Explore", icon: "explore", group: "Organisation", load: () => import("../pages/explore") },
  { id: "activity", label: "Activity", icon: "activity", group: "Team", load: () => import("../pages/activity") },
  { id: "health", label: "Data health", short: "Health", icon: "clock", group: "Team", load: () => import("../pages/health") },
  { id: "settings", label: "Settings", icon: "settings", group: "Team", load: () => import("../pages/settings") },
  { id: "setup", label: "Setup", icon: "setup", group: "Install", load: () => import("../pages/setup") },
  { id: "connections", label: "Connections", short: "Connect", icon: "connections", group: "Install", load: () => import("../pages/connections") },
  { id: "agents", label: "Agents", icon: "agents", group: "Install", load: () => import("../pages/agents") },
  { id: "help", label: "Help", icon: "help", group: "Install", load: () => import("../pages/help") },
  { id: "about", label: "About", icon: "about", group: "Install", load: () => import("../pages/about") },
];

// The phone tab bar shows these; the rest sit behind "More".
export const TABS = ["overview", "insights", "ci", "prs"];

export const routeById = (id: string) => ROUTES.find((r) => r.id === id);
