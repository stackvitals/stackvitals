// Shapes of the files the Action publishes. Every field is optional: an older run's file may lack newer parts.
export type Stamp = string | null | undefined;
export type Num = number | null | undefined;

export interface AppModule { updated?: Stamp; file?: string; page?: string }
export interface AppJson {
  schema?: number; repo: string; default_branch?: string; visibility?: "public" | "private";
  modules?: Record<string, AppModule>; pages?: string[];
  facts?: Record<string, Num>;
  links?: { repo?: string; workflow?: string | null; actions?: string; settings_file?: string; edit_settings?: string; new_issue?: string };
  summary?: string | null;
  // Newer runs may add the last run and its notes; shown when present.
  run?: { number?: number; at?: Stamp; conclusion?: string; url?: string; next?: Stamp };
  notes?: string[];
}

export interface Decision { verb: string; kind: string; id: string; by?: string; until?: string | null; reason?: string | null; at?: Stamp; source?: string }
export interface DecisionsJson { state?: Record<string, Decision>; log?: Decision[] }

export interface Evidence { run: number; att: number; kind?: string }
export interface CiItem {
  id?: string; suite?: string; workflow?: string; job?: string; runs?: number; failures?: number; flake_events?: number;
  flake_rate?: Num; rate_low?: Num; rate_high?: Num; state?: string; monitors?: string[]; labels?: string[]; since?: Stamp;
  last_flake?: Stamp; message?: string | null; top_step?: string | null; owners?: string[]; retry_minutes?: number;
  prs_affected?: number[]; variants?: Record<string, number>; evidence?: Evidence[]; decision?: Decision | null; median_s?: Num; p95_s?: Num;
  slower?: { pct: number } | null; trend?: [string, number][]; first?: Stamp;
}
export interface CiWeek { week: string; job_runs?: number; flakes?: number; flake_share?: Num; push_median_s?: Num; first_try_share?: Num }
export interface CiChange {
  metric?: string; label: string; now: number; base?: Num; unit: string; note?: string | null; changed?: boolean;
  direction?: "up" | "down" | null; detectable?: Num; shown_with?: string;
}
export interface FailureGroup { id?: string; type?: string; where?: string; message?: string; failures?: number; tests?: number; runs?: number; first?: Stamp; last?: Stamp; prompt?: string }
export interface SlowTest { id: string; median_ms: number; p95_ms: number; samples?: number; slower?: { pct: number } | null; trend?: [string, number][] }
export interface Coverage {
  latest?: { pct: number; covered: number; lines: number; at?: Stamp } | null; change?: Num; trend?: [string, number][];
  prs?: { pr: number; pct: number; covered: number; lines: number; missed?: Record<string, number[]>; at?: Stamp }[];
}
export interface CiJson {
  window_days?: number; generated?: Stamp; runs?: number; rerun_share?: Num;
  queue?: { median_s?: Num; p95_s?: Num } | null; minutes?: Record<string, number>;
  pushes?: { pushes: number; median_s?: Num; p90_s?: Num; first_try_share?: Num; first_try_range?: [number, number]; median_range_s?: [number, number] } | null;
  tests?: CiItem[]; jobs?: CiItem[]; weekly?: CiWeek[]; changes?: CiChange[]; failure_groups?: FailureGroup[];
  slow_tests?: SlowTest[]; new_tests?: CiItem[]; skipped_tests?: { id: string; since?: Stamp; days?: number; suites?: number; new?: boolean }[];
  coverage?: Coverage | null; has_test_reports?: boolean; benchmark?: unknown;
  verdict_feedback?: Record<string, { confirmed: number; disputed: number; share: Num; low: Num; high: Num }>;
}

export interface Finding {
  kind: string; key?: string; title: string; action?: string; hours: number; n: number; open_since?: string; structural?: boolean;
  active_share_90d?: number; evidence?: { url: string; label: string }[]; decision?: Decision | null; part_of?: string;
}
export interface InsightsJson {
  findings?: Finding[]; opportunity?: { hours: number; findings: number; inside_another?: number };
  track_record?: { since: string; top_findings: number; shrank_by_half: number; cleared: number };
  red_ci?: { prs: number; red_prs: number; red_hours_total: number; rerun_hours_total: number; rerun_waits: number; without_checks: number; definition?: string };
  chains?: unknown[];
}

export interface FlowJson {
  window_days?: number; open?: number; stale?: number; merged?: number;
  queue?: { n: number; title: string; author?: string; why?: string; since?: Stamp }[];
  monthly?: { month: string; opened?: number; merged?: number }[];
}
export interface Phase { n?: number; enough?: boolean; p50_h?: Num; p75_h?: Num }
export interface DeliveryJson {
  window_days?: number; phases?: Record<string, Phase>;
  dora?: { deployments?: number; change_failure_rate?: Num; monthly?: { month: string; deployments: number }[] };
  stuck?: { hanging_review?: { pr: number; since?: Stamp }[] };
  ai?: { assisted_prs?: { share?: Num } };
}
export interface CommunityJson {
  waiting_total?: number; waiting?: { kind: string; n: number; days: number }[];
  score?: { score: number } | null; stars?: { weeks?: [string, number][]; stars?: number; gained_12w?: Num; growth_12w?: Num };
}
export interface DepsJson {
  open?: unknown[]; merge_median_hours?: Num;
  security_overdue?: { package: string; from?: string; to?: string; pr: number; age_hours: number }[];
}
export interface PortalJson { repos?: { name: string; owners?: { status?: string }; score?: { level?: string | null } }[] }
export interface AlertsJson { series?: Record<string, [string, Num, number?][]> }
export interface SettingsJson { notes?: string[] }

// Community page: answers with waiting items counted (Kaplan-Meier), funnel, quarters, cohorts, who carries the work, traffic.
export interface Km { median?: Num; low?: Num; high?: Num; at_least?: Num; answered?: number; waiting?: number; too_few?: boolean; closed_unanswered?: number }
export interface Peer { typical: number; low: number; high: number }
export interface CommunityFull extends CommunityJson {
  generated?: Stamp; facts?: { first_answer_hours?: Num; answered_1d_share?: Num; newcomer_return_rate?: Num };
  waiting?: { kind: string; n: number; days: number; created?: Stamp }[];
  funnel?: { newcomers?: number; judged: number; returned: number; regulars?: number; maintainers?: number } | null;
  answers?: { issues?: { km?: Km; responders?: number }; discussions?: { km?: Km; answer_chosen?: Num } | null } | null;
  forum?: { km?: Km; topics: number; days: number; anyone_answered?: Num; solved_share?: Num } | null;
  chat?: { km?: Km; topics: number; days: number; anyone_answered?: Num } | null;
  changes?: CiChange[];
  quarters?: { quarter: string; items?: Num; median_hours?: Num; within_1d?: Num; newcomers?: Num }[];
  cohorts?: { months?: { month: string; newcomers: number; back_by_90d: number | null; back_90_180d: number | null }[] } | null;
  dependency?: { days?: number; bus_factor: number; top_share?: Num; people: number; merged: number; peers?: { bus_factor?: Peer; top_share?: Peer } } | null;
  tenure?: { days?: number; newcomers?: { n: number; median_h?: Num; answered_1d_share?: Num }; regulars?: { n: number; median_h?: Num; answered_1d_share?: Num } } | null;
  orgs?: { factor?: number | null; unknown_share?: Num; people: number; merged: number; orgs: { org: string; prs: number; share: Num }[] } | null;
  context?: {
    governance?: boolean; security_policy?: boolean; code_of_conduct?: string | null; funding?: string[]; discussions?: boolean; maintainers_listed?: number;
    code_owners?: number; contributing?: boolean; response_policy?: { said: string; hours: number } | null; stated?: { capacity?: string; norms?: string } | null;
  } | null;
  traffic?: { days?: number; views?: [string, number, number?][]; clones?: [string, number, number?][]; views_total?: number; clones_total?: number;
    referrers?: ({ referrer?: string; count?: number } | [string, number])[] } | null;
}

// Dependencies page: update pull requests, known vulnerabilities and the supply chain.
export interface DepUpdate { pr: number; package?: string; security?: boolean; from?: string; to?: string; bump?: string; ecosystem?: string; age_hours?: number; decision?: Decision | null }
export interface DepsFull extends DepsJson { bots?: string[]; open?: DepUpdate[]; quiet_days?: number; merged_90d?: number; last_opened?: Stamp }
export interface Vuln { id: string; aliases?: string[]; dev?: boolean; fix_plan?: { to: string; bump: string; command: string }; reach?: { level: string; path: string[] }; ignored?: { until?: string | null; reason?: string }; package: string; version?: string; ecosystem?: string; severity?: string; malware?: boolean; fixed?: string | null;
  file?: string; first_seen?: string; imported?: boolean | null }
export interface VulnsJson { scanner?: string; files?: string[]; ref?: string; generated?: Stamp; offline?: boolean; open?: Vuln[]; closed?: unknown[]; skipped?: string[] }
export interface Reach { id: string; aliases?: string[]; reach: string; module?: string; version?: string; fixed?: string | null; path?: string[] }
export interface SupplyJson {
  generated?: Stamp; outside_lookups?: boolean; packages?: number; systems?: Record<string, number>; policy?: { deny?: string[]; min_scorecard?: number | null };
  licences?: { denied?: { name: string; version?: string; licence?: string; system?: string }[]; accepted?: unknown[]; unknown?: number };
  drift?: { name: string; from: string; from_quarter?: string; to: string; to_quarter?: string }[];
  scorecards?: { checked?: number; projects?: number; drops?: { project: string; before?: number; after?: number; since?: string; packages: string[] }[];
    low?: { project: string; score?: number; packages: string[] }[]; below_policy?: { project: string; score?: number; packages: string[] }[] };
  runtimes?: { runtime: string; version?: string; use?: string; status?: string; eol?: string | null; latest?: string; file?: string }[];
  reachability?: { error?: string; scanner?: string; findings?: Reach[]; counts?: { called: number; imported: number; required: number } } | null;
}

// Portal page: the org's repos with their rule results, catalog entities, campaigns, golden paths and the org view.
export interface PortalRule { id: string; level?: string; result?: string; evidence?: string }
export interface PortalEntity { kind?: string; name: string; title?: string; description?: string; system?: string; type?: string; lifecycle?: string; owner?: string;
  owner_check?: [string, ...unknown[]] | null; depends_on?: string[] }
export interface PortalRepo {
  name: string; private?: boolean; archived?: boolean; fork?: boolean; language?: string | null; runtime?: string[];
  owners?: { status?: string } | null; score?: { level?: string | null; results?: PortalRule[] } | null;
  modules?: { ci_first_try?: string; ci_first_try_share?: Num } | null; since?: { level?: string } | string | null;
  descriptor?: { present?: boolean; entities?: PortalEntity[]; problems?: string[] } | null; doc_pages?: string[];
}
export interface PortalFull {
  org?: string; mode?: string; built_at?: Stamp; repos?: PortalRepo[];
  campaigns?: { title: string; passing?: number; targets?: number; until?: string | null; burn_down?: [string, number][]; failing?: string[] }[];
  golden?: { id: string; title: string; kind: string; private?: boolean; description?: string }[]; golden_ready?: boolean;
  org_view?: { running?: number; repos?: number; medians: Record<string, Num>; totals: Record<string, Num>; counts: Record<string, number>;
    leaders: Record<string, { repo: string; value: number }[]> } | null;
}

// Explore page: the summary tables' manifest.
export interface SummaryManifest { generated?: Stamp; files?: Record<string, { rows?: number; generated?: Stamp }> }
