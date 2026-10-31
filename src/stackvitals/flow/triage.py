"""Private triage of open outside PRs for maintainers: the chance of a merge within 30 days and why.
Computed on demand with the maintainer's own token; never stored, never on a page, never on a PR (user decision D1)."""
from datetime import datetime, timedelta

from mergescout.signals.triage_math import FEATURES, buckets, explain, predict
from stackvitals.core.actors import People
from stackvitals.flow.analyze import _iso

MODEL_FILE = "triage-model.json"
NOTE = ("Private: computed on demand for maintainers with your own token; never shown publicly, stored or posted. "
        "It scores the PR's chances, not the person.")
MIN_REPO_PRS = 10
MIN_MODEL_PRS = 1000


def _repo_rate(prs: list[dict], opened: str, skip: int | None = None, people: People | None = None) -> float | None:
    # Same as training: outside PRs opened 30 to 395 days before this one, merged within 30 days of opening.
    at = datetime.fromisoformat(opened.replace("Z", "+00:00"))
    lo, hi = _iso(at - timedelta(days=395)), _iso(at - timedelta(days=30))
    if people is None:
        people = People(prs)
    pool = [p for p in prs if p["n"] != skip and people.is_outside(p) and lo <= p["cr"] <= hi]
    if len(pool) < MIN_REPO_PRS:
        return None
    merged = sum(1 for p in pool if p.get("mg") and p["mg"] <= _iso(datetime.fromisoformat(p["cr"].replace("Z", "+00:00"))
                                                                    + timedelta(days=30)))
    return merged / len(pool)


def features(target: dict, prs: list[dict], now: datetime, people: People | None = None) -> dict:
    """Only what this repo knew when the PR was opened, and the PR itself (the same rules as training)."""
    au = target.get("au")
    earlier = [p for p in prs if au and p.get("au") == au and p["cr"] < target["cr"]] if au else []
    here = sum(1 for p in earlier if p.get("mg") and p["mg"] < target["cr"])
    # A first contribution is judged from history: GitHub's label is computed when asked, so it isn't reliable.
    return buckets(here, (target.get("add") or 0) + (target.get("del") or 0), bool(target.get("iss")), not earlier,
                   _repo_rate(prs, target["cr"], skip=target["n"], people=people))


def valid(model) -> dict | None:
    # Refused: a model fitted on too few PRs (every PR gets about the same chance) or built with other inputs.
    ok = (isinstance(model, dict) and isinstance(model.get("intercept"), (int, float)) and isinstance(model.get("coef"), dict)
          and all(isinstance(v, (int, float)) for v in model["coef"].values()) and (model.get("prs") or 0) >= MIN_MODEL_PRS
          and model.get("features") == FEATURES)
    return model if ok else None


def triage(data: dict, model: dict, now: datetime) -> dict:
    """Score every open, non-draft PR from an outside contributor."""
    prs = data["open"] + data["closed"]
    people = People(prs)
    out = []
    for p in data["open"]:
        if not people.is_outside(p) or p.get("draft"):
            continue
        feats = features(p, prs, now, people)
        out.append({"pr": p["n"], "title": p.get("ti"), "author": p.get("au"), "chance": round(predict(model, feats), 3),
                    "reasons": explain(model, feats), "features": feats})
    ev = model.get("evaluation") or {}
    return {"note": NOTE, "prs": sorted(out, key=lambda x: -x["chance"]),
            "model": {"checked_on_prs": ev.get("test_prs"), "brier": ev.get("brier"), "baseline_brier": ev.get("baseline_brier"),
                      "built_at": model.get("built_at"), "features": list(FEATURES)}}
