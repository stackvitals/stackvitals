// "How often would this have fired?": the Action's alert rule (core/alerts.py evaluate and replay) over the 90 daily points
// alerts.json publishes, so a new threshold shows its effect before anyone saves it. A port of the old app's replay.js.
export type Point = [string, number | null | undefined, number?, (number | null)?];
const ORDER = ["ok", "heads_up", "miss"];

function level(value: number | null | undefined, n: number, limit: number, minN: number, headsUp: number, low: number | null | undefined): string {
  if (value === null || value === undefined || n < minN) return "not enough data";
  // Over, but the likely range still reaches under the limit: a heads-up until the evidence settles it.
  if (value > limit) return low === null || low === undefined || low > limit ? "miss" : "heads_up";
  return value >= headsUp * limit ? "heads_up" : "ok";
}

export function replay(series: Record<string, Point[]>, limits: Record<string, number>, { headsUp = 0.8, minN = 10 } = {}): Record<string, number> {
  const fired: Record<string, number> = Object.fromEntries(Object.keys(limits).map((m) => [m, 0]));
  const state: Record<string, { verdict?: string; open?: boolean }> = {};
  const days = Math.max(0, ...Object.keys(limits).map((m) => (series[m] || []).length));
  for (let k = 0; k < days; k++) {
    for (const [metric, limit] of Object.entries(limits)) {
      const point = (series[metric] || [])[k];
      if (!point) continue;
      const [, value, n, low] = point;
      const before = state[metric] || {};
      const last = before.verdict || "ok";
      // A point without a count passes the sample check, as the old app read it.
      let lv = level(value, n ?? Infinity, limit, minN, headsUp, low);
      // An open miss stays a miss while the value stays over the limit, however its range moves.
      if (lv === "heads_up" && before.open && value !== null && value !== undefined && value > limit) lv = "miss";
      let open = before.open || false;
      if ((lv === "heads_up" || lv === "miss") && ORDER.indexOf(lv) > ORDER.indexOf(last)) {
        fired[metric]!++;
        open = open || lv === "miss";
      } else if (lv === "ok" && before.open) {
        fired[metric]!++;
        open = false;
      }
      state[metric] = { verdict: lv === "not enough data" ? last : lv, open };
    }
  }
  return fired;
}
