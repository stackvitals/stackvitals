from datetime import datetime

from stackvitals.core.actors import People
from stackvitals.flow.analyze import analyze
from stackvitals.flow.knowledge import codeowners_for, delivery, expertise, knowledge_map, suggest_reviewers
from stackvitals.flow.peers import compare, own_metrics
from stackvitals.flow.preflight import Habits, folder_habits, gaps, preflight


def build(data: dict, repo: dict, now: datetime, owner: str | None = None, people_speed: bool = False,
          window_days: int = 90, asks: dict | None = None, bench: dict | None = None, names: bool = True) -> dict:
    """Everything Team Flow shows: the queue (with reviewer suggestions where nobody was asked), review stages,
    the knowledge map and delivery. People's answer times are used and shown only when people_speed is set; the
    knowledge map names people only when names is set."""
    prs = data["open"] + data["closed"]
    # Who is an insider is decided once, by what people do, and shared by every part below.
    people = People(prs)
    result = analyze(data, now, window_days=window_days, people_speed=people_speed, owner=owner, people=people)
    ex = expertise(prs, now, people=people)
    load = {r["reviewer"]: r["open_requests"] for r in result["load"]}
    speed = {r["reviewer"]: r["median_s"] for r in result.get("responders", [])} if people_speed else None
    text = repo.get("codeowners")
    by_n = {p["n"]: p for p in data["open"]}
    habits_index = Habits(prs, now)
    for q in result["queue"]:
        p = by_n.get(q["n"])
        if p:
            # Where this PR differs from what merged PRs in its folders usually include.
            q["gaps"] = gaps(p, habits_index.norms(p.get("paths") or []))
        if p and q["actor"] == "maintainers" and q["step"] == "pickup" and not p["rq"]:
            owners = {path: codeowners_for(path, text) for path in p.get("paths") or []} if text else {}
            q["suggested"] = suggest_reviewers(p, ex, load, owners, speed)
    result["knowledge"] = knowledge_map(prs, now)
    if not names:
        # A public repo's pages are public: the map names areas, never the person behind them (route work, don't rate people).
        for a in result["knowledge"].get("areas") or []:
            a["owner"] = None
    result["delivery"] = delivery(prs, repo.get("releases") or [], now, window_days)
    habits = habits_index.norms([])
    # Maintainers' asks are shown only when they come up often enough to matter.
    common = [a for a in preflight(prs, asks or {}, [], now)["asks"] if a["share"] >= 0.05 and a["prs"] >= 3]
    # Per folder too, so the app's planned-PR check narrows to the folders it touches like the CLI does.
    result["habits"] = {**habits, "asks": common, "folders": folder_habits(prs, asks or {}, now, habits_index)}
    # Compared with similar public repos, only when a benchmarks file was found.
    result["peers"] = compare(own_metrics(prs, now, window_days, people=people), bench, repo.get("language"), repo.get("stars"))
    return result
