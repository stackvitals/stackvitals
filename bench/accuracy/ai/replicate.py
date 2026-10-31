"""Reproduce the published AI pull request acceptance gaps on the crawl, then show how much they shrink once pull requests
are compared like with like.

Modes follow AIDev's public rules: an agent-opened PR comes from an agent's branch (codex/, copilot/, cursor/, devin/,
claude/) or Devin's account; an assisted PR is a person's PR whose body carries an AI co-author trailer; dependency bots
are left out. The outcome is "merged", among closed and merged PRs.

1. Unadjusted merge rates by mode and tool (AIDev: people 76.8%; Codex 65.3%, Claude Code 52.5%, Cursor 51.4%,
   Devin 48.9%, Copilot 38.2%).
2. Agent-opened against people's PRs in the same repo, month and size band (Mantel-Haenszel risk difference, Sato's
   variance), with and without self-merges (merged by the PR's own author).
3. Assisted against the same author's unmarked PRs in the same repo and size band (Watanabe et al.: 83.8% against 91.0%,
   or 87.0% time-aligned), with the matched share.
4. Negative control: the assisted labels shuffled within each author's matched PRs; the estimate must sit at zero.

    python bench/accuracy/ai/replicate.py <folder of crawl prs parquet files> [--placebos 200] [--seed 13]
"""
import argparse
import json
import math
import random
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from stackvitals.core.stats import mh_risk_difference, wilson

AGENT_BRANCH = re.compile(r"^(copilot|codex|cursor|devin|claude)[/-]", re.I)
TOOLS = ("codex", "claude", "cursor", "devin", "copilot")


def _load(folder: Path) -> list[dict]:
    rows = duckdb.connect().execute(f"""
        SELECT repo_id, number, lower(author_login) AS author, author_type, head_ref, ai_tag, state,
               merged_at IS NOT NULL AS merged, lower(coalesce(merged_by, '')) AS merged_by,
               coalesce(additions, 0) + coalesce(deletions, 0) AS lines, strftime(created_at, '%Y-%m') AS month
        FROM read_parquet('{(folder / '*.parquet').as_posix()}', union_by_name = true)
        WHERE state IN ('MERGED', 'CLOSED')
        QUALIFY row_number() OVER (PARTITION BY repo_id, number ORDER BY fetched_at DESC) = 1
        ORDER BY repo_id, number""").fetchall()
    cols = ("repo", "number", "author", "author_type", "head", "tag", "state", "merged", "merged_by", "lines", "month")
    return [dict(zip(cols, r)) for r in rows]


def mode(p: dict) -> tuple[str, str | None]:
    """('agent' | 'assisted' | 'person' | 'bot', tool)."""
    branch = AGENT_BRANCH.match(p["head"] or "")
    if branch:
        return "agent", branch.group(1).lower()
    if p["tag"] == "devin":
        return "agent", "devin"
    if p["tag"] == "bot" or p["author_type"] == "Bot" or (p["author"] or "").endswith("[bot]"):
        return "bot", None
    if p["tag"] in TOOLS:
        return "assisted", p["tag"]
    return "person", None


def _band(lines: int) -> int:
    return int(math.log2(lines + 1))


def _strata(treated: list[dict], control: list[dict], key, outcome) -> tuple[list[tuple], int, int]:
    """(a, n1, c, n0) per group, the treated PRs in groups with a control, and all treated PRs."""
    groups = defaultdict(lambda: [0, 0, 0, 0])
    for p in treated:
        g = groups[key(p)]
        g[0] += outcome(p)
        g[1] += 1
    for p in control:
        k = key(p)
        if k in groups:
            groups[k][2] += outcome(p)
            groups[k][3] += 1
    matched = [tuple(g) for g in groups.values() if g[1] and g[3]]
    return matched, sum(g[1] for g in matched), len(treated)


def _estimate(groups: list[tuple], matched: int, total: int) -> dict:
    rd, se = mh_risk_difference(groups)
    if rd is None:
        return {"gap": None, "matched_share": round(matched / total, 4) if total else None}
    return {"gap": round(rd, 4), "low": round(rd - 1.96 * se, 4), "high": round(rd + 1.96 * se, 4),
            "detectable": round(2.8 * se, 4), "groups": len(groups), "matched": matched, "matched_share": round(matched / total, 4)}


def _rate(ps: list[dict], outcome) -> dict:
    k, n = sum(outcome(p) for p in ps), len(ps)
    lo, hi = wilson(k, n)
    return {"n": n, "merged": round(k / n, 4) if n else None, "low": round(lo, 4), "high": round(hi, 4)}


def run(folder: Path, placebos: int, seed: int) -> dict:
    rng = random.Random(seed)
    prs = _load(folder)
    for p in prs:
        p["mode"], p["tool"] = mode(p)
    merged = lambda p: int(p["merged"])  # noqa: E731
    # Self-merged: merged by the PR's own author, so nobody else accepted it.
    by_other = lambda p: int(p["merged"] and p["merged_by"] != p["author"])  # noqa: E731
    people = [p for p in prs if p["mode"] == "person"]
    out = {"prs": len(prs), "repos": len({p["repo"] for p in prs}), "seed": seed,
           "unadjusted": {"people": _rate(people, merged)}}
    for m in ("agent", "assisted"):
        for tool in TOOLS:
            ps = [p for p in prs if p["mode"] == m and p["tool"] == tool]
            if len(ps) >= 30:
                out["unadjusted"][f"{m}:{tool}"] = _rate(ps, merged)
    agents = [p for p in prs if p["mode"] == "agent"]
    assisted = [p for p in prs if p["mode"] == "assisted"]
    out["unadjusted"]["agent:all"], out["unadjusted"]["assisted:all"] = _rate(agents, merged), _rate(assisted, merged)
    out["self_merged_share_of_merged"] = {
        name: round(sum(p["merged"] and p["merged_by"] == p["author"] for p in ps) / max(1, sum(p["merged"] for p in ps)), 4)
        for name, ps in (("people", people), ("agent", agents), ("assisted", assisted))}
    raw = lambda t, c, f: round(_rate(t, f)["merged"] - _rate(c, f)["merged"], 4)  # noqa: E731
    same_repo = lambda p: (p["repo"], p["month"], _band(p["lines"]))  # noqa: E731
    same_author = lambda p: (p["repo"], p["author"], _band(p["lines"]))  # noqa: E731
    out["agent_vs_people"] = {
        "unadjusted_gap": raw(agents, people, merged),
        "same_repo_month_size": _estimate(*_strata(agents, people, same_repo, merged)),
        "unadjusted_gap_merged_by_someone_else": raw(agents, people, by_other),
        "same_repo_month_size_merged_by_someone_else": _estimate(*_strata(agents, people, same_repo, by_other))}
    by_tool = {}
    for tool in TOOLS:
        ps = [p for p in agents if p["tool"] == tool]
        if len(ps) >= 100:
            by_tool[tool] = {"unadjusted_gap": raw(ps, people, merged), **_estimate(*_strata(ps, people, same_repo, merged))}
    out["agent_vs_people"]["by_tool"] = by_tool
    groups, matched, total = _strata(assisted, people, same_author, merged)
    out["assisted_vs_same_author"] = {"unadjusted_gap": raw(assisted, people, merged),
                                      "same_repo_month_size": _estimate(*_strata(assisted, people, same_repo, merged)),
                                      "same_author_repo_size": _estimate(groups, matched, total),
                                      "same_author_merged_by_someone_else":
                                          _estimate(*_strata(assisted, people, same_author, by_other))}
    # Negative control: shuffle the assisted label among each matched group's PRs; the gap must vanish.
    pool = defaultdict(list)
    keys = {same_author(p) for p in assisted}
    for p in assisted + people:
        if same_author(p) in keys:
            pool[same_author(p)].append(p)
    fake = []
    for _ in range(placebos):
        groups = []
        for ps in pool.values():
            n1 = sum(p["mode"] == "assisted" for p in ps)
            if not n1 or n1 == len(ps):
                continue
            shuffled = ps[:]
            rng.shuffle(shuffled)
            t, c = shuffled[:n1], shuffled[n1:]
            groups.append((sum(merged(p) for p in t), len(t), sum(merged(p) for p in c), len(c)))
        rd, _se = mh_risk_difference(groups)
        if rd is not None:
            fake.append(rd)
    fake.sort()
    out["negative_control"] = {"placebos": len(fake), "mean_gap": round(sum(fake) / len(fake), 4) if fake else None,
                               "middle_95": [round(fake[int(0.025 * len(fake))], 4), round(fake[int(0.975 * len(fake)) - 1], 4)]
                               if fake else None}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--placebos", type=int, default=200)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("replicate-results.json"))
    args = ap.parse_args(argv)
    out = run(args.folder, args.placebos, args.seed)
    out["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
