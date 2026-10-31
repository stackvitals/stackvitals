"""A short brief for coding agents (and people) about how changes get merged in one repo. Only measured facts that an
agent can't read off the repo's files: per-folder habits of merged PRs, who reviews there, known-flaky CI, and how
outside PRs fare against similar repos. Every number carries the count it comes from; thin history is said, not guessed.
Text that contributors control (test names, folder names) is neutralised before it reaches files agents obey."""
import hashlib
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from stackvitals import codeowners
from stackvitals.community.analyze import answered_at
from stackvitals.core.actors import People, kind_of
from stackvitals.core.stats import wilson
from stackvitals.flow import peers
from stackvitals.flow.analyze import _iso, _median, is_bot, stages
from stackvitals.flow.knowledge import _areas, expertise
from stackvitals.flow.preflight import CHANGELOG_FILE, HABIT, Habits, preflight

MIN_AREA_PRS = 10
ASK_MIN = 0.1  # an ask seen on fewer PRs than this is not a habit
MAX_AREAS = 6
LOW_SAMPLE = 30
SIZES = (("under 150 lines", 0, 150), ("150-500 lines", 150, 500), ("over 500 lines", 500, None))
LABELS = {"tests": "tests", "changelog": "a changelog entry", "docs": "docs"}
START, END = "<!-- stackvitals:brief -->", "<!-- /stackvitals:brief -->"
STAMP = "Written by StackVitals"
SAFE_PART = re.compile(r"^[A-Za-z0-9_@+-][A-Za-z0-9._@+-]*$")


class BriefError(RuntimeError):
    pass


def _clean(text, limit: int = 100) -> str:
    # Contributor-controlled text stays one plain line: no newlines, comment markers or code-format breaks.
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text)).replace("<!--", "").replace("-->", "").replace("`", "'").strip()
    return s if len(s) <= limit else s[:limit - 1] + "…"


def _code(text) -> str:
    return f"`{_clean(text)}`"


def _safe_area(name: str) -> bool:
    return name != "(root)" and all(SAFE_PART.match(part) for part in name.split("/"))


def _is_agent(p: dict) -> bool:
    # The crawl's own rule: agent accounts, or plain names (codex, claude) only when the account is a bot.
    return kind_of(p.get("au"), p.get("at")) == "agent"


def _hours(a: str, b: str) -> float | None:
    da, db = (datetime.fromisoformat(x.replace("Z", "+00:00")) for x in (a, b))
    return (db - da).total_seconds() / 3600 if db >= da else None


def _lines(p: dict) -> int | None:
    if p.get("add") is None and p.get("del") is None:
        return None
    return (p.get("add") or 0) + (p.get("del") or 0)


def _outside(prs: list[dict], since: str, now: datetime, bench, language, stars) -> dict:
    # Maintainers count by what they do too (a lead shown as CONTRIBUTOR who merges PRs is not an outsider).
    people = People(prs)
    ins = people.insiders()
    outside = [p for p in prs if people.is_outside(p)]
    closed = [p for p in outside if p.get("st") in ("MERGED", "CLOSED") and (p.get("cl") or "") >= since]
    merged = sum(p["st"] == "MERGED" for p in closed)
    n = len(closed)
    out = {"closed": n, "merged": merged, "rate": round(merged / n, 4) if n else None, "low_sample": n < LOW_SAMPLE}
    if n:
        lo, hi = wilson(merged, n)
        out.update(low=round(lo, 4), high=round(hi, 4))
    out["by_size"] = []
    sized = [(p, x) for p in closed if (x := _lines(p)) is not None]
    for label, lo_lines, hi_lines in SIZES:
        group = [p for p, x in sized if x >= lo_lines and (hi_lines is None or x < hi_lines)]
        if len(group) >= 5:
            out["by_size"].append({"size": label, "closed": len(group),
                                   "rate": round(sum(p["st"] == "MERGED" for p in group) / len(group), 4)})
    # A maintainer's first answer (review, comment or close by a maintainer) to outside PRs at least a day old.
    day_old = _iso(now - timedelta(days=1))
    asked = [p for p in outside if since <= p["cr"] < day_old]
    waits = [w for p in asked if (a := answered_at(p, ins)) and (w := _hours(p["cr"], a)) is not None]
    out.update(asked=len(asked), answered=len(waits),
               first_answer_hours=round(_median(waits), 1) if len(waits) >= 5 else None)
    found = peers.compare({"outsider_merge_rate": out["rate"]}, bench, language, stars) if n else None
    if found:
        m = found["metrics"][0]
        out["peers"] = {"group": found["group"], "repos": m["repos"], "place": m["place"], "typical": m["typical"]}
    return out


def _group(bench: dict | None, section: str, language: str | None, stars: int | None) -> tuple[str, dict] | None:
    from mergescout.bench.ci import tier
    from stackvitals.ci.bench import _label
    groups = (bench or {}).get(section) or {}
    size = tier(stars)
    key = next((k for k in (f"{language}|{size}", f"{language}|all", f"all|{size}", "all|all") if k in groups), None)
    return (_label(key), groups[key]) if key else None


def _agents(prs: list[dict], since: str) -> dict | None:
    mine = [p for p in prs if _is_agent(p) and p.get("st") in ("MERGED", "CLOSED") and (p.get("cl") or "") >= since]
    if len(mine) < 10:
        return None
    merged = sum(p["st"] == "MERGED" for p in mine)
    return {"closed": len(mine), "merged": merged, "rate": round(merged / len(mine), 4)}


def _areas_brief(prs: list[dict], asks: dict, rules, now: datetime, months: int) -> list[dict]:
    habits = Habits(prs, now, months)
    ex = expertise(prs, now)
    since = _iso(now - timedelta(days=30 * months))
    merged = [p for p in prs if p.get("mg") and p["mg"] >= since and not is_bot(p)]
    out = []
    for name, idx in sorted(habits.by_area.items(), key=lambda kv: -len(kv[1])):
        if len(idx) < MIN_AREA_PRS or len(out) >= MAX_AREAS:
            break
        if CHANGELOG_FILE.search(f"{name}/_"):
            continue  # a changelog-fragment folder (news/, changelog.d/): said once for the whole repo instead
        probe = "_" if name == "(root)" else f"{name}/_"
        norms = habits.norms([probe])
        pickups = [s["pickup"] / 3600 for p in merged if name in _areas(p.get("paths")) and (s := stages(p))["pickup"] is not None]
        asked = preflight(prs, asks, [probe], now, months)
        reviewers = sorted(ex.reviewed.get(name, {}).items(), key=lambda kv: -kv[1])
        out.append({"area": name, "merged_prs": norms["merged_prs"], "include": norms["include"], "size": norms["size"],
                    "asks": [x for x in asked["asks"] if x["share"] >= ASK_MIN and x["prs"] >= 3][:2]
                    if asked["scope"] != "whole repo" else [], "reviewed_prs": asked["reviewed_prs"],
                    "reviewers": [{"login": who, "reviews": c} for who, c in reviewers[:3] if c >= 3],
                    # A folder's review speed only when two or more people review there, so it is never one person's.
                    "first_review_hours": round(_median(pickups), 1) if len(pickups) >= 5 and len(reviewers) >= 2 else None,
                    "owners": codeowners.owners_for(probe, rules) if name != "(root)" and rules else []})
    return out


def _flaky(ci: dict | None) -> list[dict]:
    def ok(i):
        return i.get("state") == "flaky" and isinstance(i.get("flake_events"), int) and isinstance(i.get("runs"), int)
    items = [{"name": f"{(j.get('workflow') or '?').rsplit('/', 1)[-1]} / {j.get('job')}", "kind": "job",
              "flakes": j["flake_events"], "runs": j["runs"]} for j in (ci or {}).get("jobs") or [] if ok(j) and j.get("job")]
    items += [{"name": t["id"], "kind": "test", "flakes": t["flake_events"], "runs": t["runs"]}
              for t in (ci or {}).get("tests") or [] if ok(t) and t.get("id")]
    return sorted(items, key=lambda i: (i["kind"] != "job", -i["flakes"]))[:5]


def build_brief(repo: str, data: dict, repo_info: dict, asks: dict, ci: dict | None, bench: dict | None, now: datetime,
                months: int = 12) -> dict:
    prs = (data.get("open") or []) + (data.get("closed") or [])
    since = _iso(now - timedelta(days=30 * months))
    people = [p for p in prs if not is_bot(p) and (p.get("cr") or "") >= since]
    rules = codeowners.parse(repo_info.get("codeowners")) if repo_info.get("codeowners") else []
    outside = _outside(prs, since, now, bench, repo_info.get("language"), repo_info.get("stars"))
    # A repo's past merge rate runs high for its next PRs (many stay open); the crawl's backtest says by how much.
    bt = (bench or {}).get("odds_backtest") or {}
    if outside["rate"] is not None and outside["closed"] >= 5:
        cell = next((c for c in bt.get("calibration_raw") or [] if c["bin"] == f"{min(int(outside['rate'] * 10), 9) / 10:.1f}-"
                     f"{min(int(outside['rate'] * 10), 9) / 10 + 0.1:.1f}"), None)
        if cell:
            outside["estimate"] = cell["observed"]
    check = {"repos": bt.get("repos"), "mae": (bt.get("mae") or {}).get("calibrated")}
    return {"repo": repo, "generated": now.strftime("%Y-%m-%d"), "months": months, "prs": len(people),
            # The history actually read: a store first filled for 3 months is said as such, not as 12.
            "since": min((p["cr"] for p in people), default=now.strftime("%Y-%m-%d"))[:10],
            "outside": outside, "agents": _agents(prs, since), "repo_habits": Habits(prs, now, months).norms([]),
            "agents_nearby": _group(bench, "agent_prs", repo_info.get("language"), repo_info.get("stars")),
            "backtest": check if check.get("mae") is not None else None,
            "areas": _areas_brief(prs, asks or {}, rules, now, months), "flaky": _flaky(ci)}


def _h(hours) -> str:
    if hours is None:
        return "-"
    return f"{hours:.0f} h" if hours < 48 else f"{hours / 24:.1f} days"


def _area_lines(a: dict) -> list[str]:
    habits = [f"{LABELS[k]} ({v:.0%})" for k, v in a["include"].items() if v >= HABIT]
    size = a["size"]
    lines = [("Merged PRs here include " + ", ".join(habits) + "; " if habits else "Merged PRs here: ")
             + f"median {size['median_lines']} lines, 75% under {size['p75_lines']}."]
    if a["asks"]:
        lines.append("Maintainers most often ask for: " + ", ".join(
            f"{_clean(x['ask'])} ({x['share']:.0%} of {a['reviewed_prs']} PRs with maintainer comments)" for x in a["asks"]) + ".")
    who = ", ".join(f"@{_clean(r['login'], 40)} ({r['reviews']} reviews)" for r in a["reviewers"])
    parts = ([f"Reviewed most by {who}"] if who else []) + (
        [f"first review: median {_h(a['first_review_hours'])}"] if a["first_review_hours"] is not None else [])
    if a["owners"]:
        parts.append("CODEOWNERS: " + " ".join(_clean(o, 60) for o in a["owners"]))
    if parts:
        lines.append("; ".join(parts) + ".")
    return lines


def render(b: dict) -> str:
    """The brief as Markdown, at most about 40 lines."""
    o = b["outside"]
    out = [f"## How changes get merged in {_clean(b['repo'])}", "",
           f"Measured by StackVitals from {b['prs']} pull requests since {b['since']} ({b['generated']}); "
           "each number says how many PRs it comes from. Bots are left out.", ""]
    if o["closed"] >= 5:
        line = f"- **Outside contributors:** {o['merged']} of {o['closed']} closed PRs merged ({o['rate']:.0%}, likely {o['low']:.0%}-{o['high']:.0%})"
        if o.get("peers"):
            line += f"; {o['peers']['place']} of {o['peers']['group']} (typical {o['peers']['typical']:.0%})"
        line += "."
        if o["by_size"]:
            line += " By size: " + ", ".join(f"{s['size']} {s['rate']:.0%} (n={s['closed']})" for s in o["by_size"]) + "."
        if o["first_answer_hours"] is not None:
            line += f" First maintainer answer: median {_h(o['first_answer_hours'])} for the {o['answered']} answered"
            line += (f"; {o['asked'] - o['answered']} of {o['asked']} never answered." if o["asked"] > o["answered"] else ".")
        if o["low_sample"]:
            line += " Few outside PRs, so treat these as rough."
        out.append(line)
        if o.get("estimate") is not None:
            check = b.get("backtest")
            out.append(f"  Of new outside PRs here, about {o['estimate']:.0%} get merged within 3 months (this repo's record, "
                       "corrected by what happened next on other repos with a similar record, since many new PRs stay open"
                       + (f"; checked on {check['repos']} repos, off by {check['mae'] * 100:.0f} points on average" if check else "")
                       + ").")
    r = b.get("repo_habits") or {}
    habits = [f"{LABELS[k]} ({v:.0%})" for k, v in (r.get("include") or {}).items() if v >= HABIT]
    if r.get("merged_prs", 0) >= MIN_AREA_PRS and habits:
        out.append(f"- **Across the repo:** merged PRs include {', '.join(habits)}; median {r['size']['median_lines']} lines "
                   f"(n={r['merged_prs']}).")
    if b.get("agents"):
        a = b["agents"]
        out.append(f"- **PRs opened by coding agents here:** {a['merged']} of {a['closed']} merged ({a['rate']:.0%}).")
    if b.get("agents_nearby"):
        label, g = b["agents_nearby"]
        people = f" vs {g['outsider']['merged']:.0%} for people's outside PRs" if g["outsider"].get("merged") is not None else ""
        out.append(f"- **PRs opened by coding agents in {label}** (often started by the repos' own maintainers): the typical "
                   f"repo merges {g['agent']['merged']:.0%} of them{people} ({g['repos_with_agent_prs']} repos, "
                   f"n={g['agent']['decided']}).")
    if b["flaky"]:
        out.append("- **Known flaky CI (if one of these fails, check the error is not from your change, then re-run):** " + "; ".join(
            f"{_code(f['name'])} {f['flakes']} of {f['runs']} runs" for f in b["flaky"]) + ".")
    for a in b["areas"]:
        label = "files at the repo root" if a["area"] == "(root)" else _code(a["area"])
        out += ["", f"### {label} ({a['merged_prs']} merged PRs)"] + [f"- {x}" for x in _area_lines(a)]
    if not b["areas"] and o["closed"] < 5:
        out += ["", "Not enough history here yet to say how changes usually get merged."]
    return "\n".join(out) + "\n"


def _write(path: Path, text: str) -> None:
    # Written whole or not at all: an interrupted run never leaves half a file.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _agents_md(old: str, section: str) -> str:
    """The file with our section replaced (or added at the end); markers count only as whole lines. Anything else
    (one marker, reversed, two sections) is refused rather than guessed, so a maintainer's text is never lost."""
    lines = old.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == START]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if not starts and not ends:
        return (old.rstrip("\n") + "\n\n" if old.strip() else "") + section
    if len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0]:
        return "".join(lines[:starts[0]]) + section + "".join(lines[ends[0] + 1:])
    raise BriefError("AGENTS.md has StackVitals markers that don't pair up (one start line and one end line after it); "
                     "fix or remove them by hand, then run again.")


def write_files(b: dict, root: Path) -> list[str]:
    """Opt-in: the brief as a marked section of AGENTS.md (the rest of the file kept) and one Copilot path-instructions
    file per folder. Only files written by StackVitals are replaced or removed."""
    root = Path(root)
    agents = root / "AGENTS.md"
    old = agents.read_text(encoding="utf-8") if agents.exists() else ""
    _write(agents, _agents_md(old, f"{START}\n{render(b)}{END}\n"))
    written = ["AGENTS.md"]
    folder = root / ".github" / "instructions"
    keep = set()
    for a in b["areas"]:
        if not _safe_area(a["area"]):
            continue  # odd folder names never reach a file name or applyTo
        slug = re.sub(r"[^a-z0-9]+", "-", a["area"].lower()).strip("-")
        name = f"stackvitals-{slug}-{hashlib.sha1(a['area'].encode('utf-8')).hexdigest()[:6]}.instructions.md"
        keep.add(name)
        # A two-level area ("src/db") is everything under it; a one-level one ("src") only its own files.
        apply_to = f"{a['area']}/**" if "/" in a["area"] else f"{a['area']}/*"
        folder.mkdir(parents=True, exist_ok=True)
        body = "\n".join(f"- {x}" for x in _area_lines(a))
        _write(folder / name, f'---\napplyTo: "{apply_to}"\n---\n<!-- {STAMP} from {_clean(b["repo"])}\'s merged PRs '
                              f"({b['generated']}); run `stackvitals contribute brief` again to refresh. -->\n"
                              f"How merged PRs in {a['area']} look ({a['merged_prs']} merged PRs):\n{body}\n")
        written.append(f".github/instructions/{name}")
    if folder.is_dir():
        for old_file in folder.glob("stackvitals-*.instructions.md"):
            if old_file.name not in keep and STAMP in old_file.read_text(encoding="utf-8", errors="replace"):
                old_file.unlink()
    return written
