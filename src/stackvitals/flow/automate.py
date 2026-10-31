"""Team automation, on by default and switched under [automation]: one suggested reviewer requested on ready pull requests
nobody was asked to review, a size label on each, and a "low risk" label on docs-only ones. Planned before the data
branch's commit (so overlapping runs never ask twice) and sent after it."""
import re
from urllib.parse import quote

from stackvitals.flow.analyze import is_bot

# Line counts (added plus deleted) at each size's top; Kubernetes' and gitStream's usual cuts.
SIZES = (("size/XS", 10), ("size/S", 100), ("size/M", 500), ("size/L", 1000), ("size/XL", None))
DOCS_LABEL = "low risk: docs only"
# Markup files anywhere, anything under docs/, and the usual top files by exact name (requirements.txt is not docs).
DOCS = re.compile(r"(?i)(\.(md|mdx|rst|adoc)$|^docs?/|(^|/)(README|CHANGELOG|CONTRIBUTING|LICENSE|AUTHORS|NOTICE)"
                  r"(\.(md|rst|txt))?$)")
MAX_WRITES = 40


def size_label(lines: int) -> str:
    return next(name for name, top in SIZES if top is None or lines < top)


def plan(open_prs: list[dict], queue: list[dict], switches: dict, state: dict) -> tuple[list[dict], dict]:
    """The writes to make (at most MAX_WRITES) and the state to keep: PRs a reviewer was requested on."""
    acts, asked = [], list(state.get("requested") or [])
    by_n = {p["n"]: p for p in open_prs}
    for p in open_prs:
        if p.get("draft") or is_bot(p):
            continue
        labels = set(p.get("lb") or [])
        if switches.get("size_labels"):
            want = size_label((p.get("add") or 0) + (p.get("del") or 0))
            stale = {x for x in labels if x.startswith("size/") and x != want}
            if want not in labels:
                acts.append({"kind": "label", "n": p["n"], "body": {"labels": [want]}})
            acts += [{"kind": "unlabel", "n": p["n"], "label": x} for x in sorted(stale)]
        if switches.get("docs_label"):
            # Only when every changed file was read (the collector reads the first 50).
            paths = p.get("paths") or []
            docs = bool(paths) and len(paths) == (p.get("files") or len(paths)) and all(DOCS.search(x) for x in paths)
            if docs and DOCS_LABEL not in labels:
                acts.append({"kind": "label", "n": p["n"], "body": {"labels": [DOCS_LABEL]}})
            elif not docs and DOCS_LABEL in labels:
                acts.append({"kind": "unlabel", "n": p["n"], "label": DOCS_LABEL})
    if switches.get("review_requests"):
        for q in queue:
            p = by_n.get(q["n"])
            pick = next((s["login"] for s in q.get("suggested") or [] if s.get("login")), None)
            if p and pick and q["n"] not in asked and not p.get("draft") and not is_bot(p) and pick != p.get("au"):
                acts.append({"kind": "review", "n": q["n"], "body": {"reviewers": [pick]}})
                asked.append(q["n"])
    acts = acts[:MAX_WRITES]
    sent = {a["n"] for a in acts if a["kind"] == "review"}
    return acts, {"requested": [n for n in asked if n in sent or n in (state.get("requested") or [])][-500:]}


def send(api, acts: list[dict]) -> dict:
    """Make the planned writes; one refused for lack of permission is counted, the rest still go."""
    done, refused = {"label": 0, "unlabel": 0, "review": 0, "comment": 0}, []
    for a in acts:
        try:
            if a["kind"] == "label":
                api.send("POST", f"/repos/{api.repo}/issues/{a['n']}/labels", a["body"])
            elif a["kind"] == "comment":
                api.send("POST", f"/repos/{api.repo}/issues/{a['n']}/comments", a["body"])
            elif a["kind"] == "unlabel":
                api.send("DELETE", f"/repos/{api.repo}/issues/{a['n']}/labels/{quote(a['label'], safe='')}")
            else:
                api.send("POST", f"/repos/{api.repo}/pulls/{a['n']}/requested_reviewers", a["body"])
            done[a["kind"]] += 1
        except Exception as exc:  # noqa: BLE001
            refused.append(f"#{a['n']} {a['kind']}: {exc}")
    return {**done, "refused": refused[:5]}
