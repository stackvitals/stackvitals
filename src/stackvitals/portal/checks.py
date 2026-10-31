"""Scorecards as a required check (opt-in): with `[checks] level = "silver"` in portal.toml and an org App that may write
checks, each repo's default branch and open pull requests get a "StackVitals portal" check that passes when the repo
meets the level, and says which rules keep it below. Branch protection can then require it. Written once a run, after
the catalog is saved; the result follows the daily catalog, so a fix shows on the next run."""
import tomllib

from stackvitals.ci.api import APIError, OutOfBudget
from stackvitals.portal.scorecard import LEVELS

NAME = "StackVitals portal"
CAP = 300  # check runs a run writes at most; the next run carries on with the rest
PRS = 20  # open pull requests a repo gets the check on


def load_level(text: str | None) -> str | None:
    try:
        level = ((tomllib.loads(text or "").get("checks") or {}).get("level") or "").lower()
    except tomllib.TOMLDecodeError:
        return None
    return level if level in LEVELS else None


def plan(catalog: dict, level: str) -> list[dict]:
    """One check per scored repo: success at or above the level, else failure with the rules that keep it below."""
    need = LEVELS.index(level)
    out = []
    for r in catalog.get("repos") or []:
        score = r.get("score")
        if r.get("archived") or r.get("fork") or not score:
            continue
        got = LEVELS.index(score["level"]) if score.get("level") in LEVELS else -1
        blocking = [x for x in score.get("results") or [] if x["result"] == "fail" and x["level"] in LEVELS[:need + 1]]
        ok = got >= need
        lines = [f"Meets {level}." if ok else f"Below {level} (now {score.get('level') or 'no level'})."]
        lines += [f"- `{x['id']}` ({x['level']}): {x['evidence']}" for x in blocking]
        out.append({"repo": r["name"], "branch": r.get("default_branch"), "conclusion": "success" if ok else "failure",
                    "title": f"{'Meets' if ok else 'Below'} {level}", "summary": "\n".join(lines)})
    return out


def send(api, checks: list[dict], cap: int = CAP) -> dict:
    """Posts each check on the default branch's head and the open pull requests' heads, up to `cap` writes."""
    posted, refused, stopped, repos = 0, [], False, 0
    for c in checks:
        try:
            heads = []
            if c["branch"]:
                heads.append(api._get(f"/repos/{c['repo']}/commits/{c['branch']}")["sha"])
            heads += [p["head"]["sha"] for p in api._get(f"/repos/{c['repo']}/pulls", {"state": "open", "per_page": PRS}) or []]
            for sha in heads:
                if posted >= cap:
                    stopped = True
                    break
                api.send("POST", f"/repos/{c['repo']}/check-runs",
                         {"name": NAME, "head_sha": sha, "status": "completed", "conclusion": c["conclusion"],
                          "output": {"title": c["title"], "summary": c["summary"]}})
                posted += 1
        except (APIError, OutOfBudget) as exc:
            refused.append(f"{c['repo']}: {str(exc)[:120]}")
        if stopped:
            break
        repos += 1
    return {"posted": posted, "refused": refused, "stopped": stopped, "repos": repos}
