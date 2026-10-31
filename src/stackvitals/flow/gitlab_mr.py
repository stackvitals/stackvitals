"""GitLab merge requests and deployments in the shapes Delivery reads for GitHub, so DORA and the review phases come
out the same way (Middleware's GitLab support, without a server):

    stackvitals delivery group/project --gitlab [--days 90]

Each merged merge request's notes tell when someone else first answered and when it was approved; its merge (or
squash) commit links it to the production deployment that shipped it. Public projects need no token."""
from datetime import datetime, timedelta

from stackvitals.ci.api import APIError
from stackvitals.ci.gitlab import GitLab

APPROVED = ("approved this merge request",)
READY = ("marked this merge request as ready", "marked as ready")
DRAFT = ("marked this merge request as draft", "marked as a draft", "marked this merge request as a draft")


def _iso(s: str | None) -> str | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%dT%H:%M:%SZ")


def mr_record(mr: dict, notes: list[dict]) -> dict:
    """One merge request as Team Flow's pull request record."""
    author = (mr.get("author") or {}).get("username")
    ev, talk = [], []
    for n in sorted(notes or [], key=lambda n: n.get("created_at") or ""):
        who, at, body = (n.get("author") or {}).get("username"), _iso(n.get("created_at")), (n.get("body") or "").lower()
        if n.get("system"):
            if any(body.startswith(x) for x in APPROVED):
                ev.append(["review", at, who, "APPROVED", "MEMBER", "User", False])
            elif any(body.startswith(x) for x in READY):
                ev.append(["ready", at])
            elif any(body.startswith(x) for x in DRAFT):
                ev.append(["draft", at])
        elif who and who != author:
            talk.append([at, who, "MEMBER", "User", False])
    if mr.get("merged_at"):
        ev.append(["merged", _iso(mr["merged_at"]), (mr.get("merged_by") or {}).get("username")])
    return {"t": "pr", "n": mr["iid"], "ti": (mr.get("title") or "")[:200], "draft": bool(mr.get("draft")),
            "st": "MERGED" if mr.get("merged_at") else (mr.get("state") or "").upper(), "cr": _iso(mr.get("created_at")),
            "up": _iso(mr.get("updated_at")), "mg": _iso(mr.get("merged_at")), "cl": _iso(mr.get("closed_at") or mr.get("merged_at")),
            "au": author, "at": "Bot" if (mr.get("author") or {}).get("bot") else "User", "as": "MEMBER",
            "base": mr.get("target_branch"), "head": mr.get("source_branch"),
            "mc": mr.get("squash_commit_sha") or mr.get("merge_commit_sha") or mr.get("sha"),
            "lb": list(mr.get("labels") or []), "paths": [], "rq": [], "ev": sorted(ev, key=lambda e: e[1] or ""),
            "cm": talk, "fa": None, "nc": None}


def deployment_record(d: dict) -> dict:
    """One GitLab deployment as the repo query's deployment."""
    state = {"success": "SUCCESS", "failed": "FAILURE", "canceled": None}.get(d.get("status"))
    return {"env": (d.get("environment") or {}).get("name"), "at": _iso(d.get("created_at")), "sha": d.get("sha"),
            "state": state, "done": _iso(d.get("finished_at") or d.get("updated_at")) if state == "SUCCESS" else None}


def collect(lab: GitLab, now: datetime, days: int = 90, max_mrs: int = 400) -> tuple[dict, dict]:
    """(flow, repo) for Delivery: merged merge requests of the window with their notes, and the deployments."""
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    info = lab.get("") or {}
    closed = []
    for mr in lab.pages("/merge_requests", {"state": "merged", "updated_after": since, "order_by": "updated_at"}):
        if len(closed) >= max_mrs:
            break
        try:
            notes = list(lab.pages(f"/merge_requests/{mr['iid']}/notes", {"sort": "asc"}, limit=3))
        except APIError:
            # gitlab.com shows notes only with a token, even on public projects: phases then end at the merge.
            notes = []
        closed.append(mr_record(mr, notes))
    deps = [deployment_record(d) for d in lab.pages("/deployments", {"updated_after": since, "order_by": "updated_at"}, limit=20)]
    repo = {"default_branch": info.get("default_branch"), "private": info.get("visibility") != "public",
            "deployments": [d for d in deps if d["state"]], "releases": []}
    return {"closed": closed, "open": []}, repo
